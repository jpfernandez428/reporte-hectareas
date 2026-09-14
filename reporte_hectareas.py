"""
reporte_hectareas.py

Calcula las hectareas trabajadas por dia y por maquina, sin necesidad de
definir campos ni marcos de plantacion a mano.

Como funciona, en resumen:
  1. Descarga el track GPS del dia desde Wialon (una maquina a la vez).
  2. Separa el track en tramos usando los giros (cambios de rumbo) como
     frontera: cada tramo recto entre dos giros es una pasada candidata
     por una hilera.
  3. Compara cada tramo contra las hileras ya conocidas de esa maquina
     (guardadas en un archivo de memoria) y lo asigna a la que corresponda,
     o crea una hilera nueva si no calza con ninguna. El largo conocido de
     cada hilera crece con cada pasada nueva.
  4. Agrupa las hileras cercanas y paralelas en cuarteles.
  5. Calcula el area de cada cuartel integrando el largo de sus hileras
     contra la distancia entre hileras vecinas (no hace falta un poligono
     dibujado a mano ni el area oficial del cuartel).
  6. Calcula, para el dia pedido, que tramo de cada hilera se cubrio
     (union de pasadas, no suma) y cuantas veces se paso por cada una.
  7. Exporta un Excel: Fecha | Cuartel | Hectareas trabajadas | Detalle de
     pasadas por hilera.

QUE FALTA PARA UNA SEGUNDA VERSION (no incluido todavia):
  - Cierre automatico de cuartel al terminar una campana de trabajo.
  - Deteccion mas fina si dos cuarteles vecinos quedan muy pegados.

COMO SE USA (ver tambien LEEME.txt):
  1. Completa el archivo config.json con tu token y los datos de tus
     maquinas.
  2. Corre en la terminal:  python3 reporte_hectareas.py
  3. Revisa el Excel que se genera en la carpeta "reportes".

La "memoria" de cada maquina se guarda en la carpeta "memoria_hileras/",
un archivo por maquina. No la borres: ahi es donde el programa va
aprendiendo el largo real de cada hilera con cada corrida, y guarda el
punto de referencia fijo que usa para medir distancias en metros.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Carga de configuracion
# ---------------------------------------------------------------------------

CARPETA_BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_CONFIG = os.path.join(CARPETA_BASE, "config.json")
CARPETA_MEMORIA = os.path.join(CARPETA_BASE, "memoria_hileras")
CARPETA_REPORTES = os.path.join(CARPETA_BASE, "reportes")
CARPETA_DATOS = os.path.join(CARPETA_BASE, "docs", "datos")
RUTA_HISTORICO = os.path.join(CARPETA_DATOS, "historico.json")

with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

WIALON_HOST = CONFIG.get("host", "https://hst-api.wialon.com")

# En la nube (GitHub Actions), el token viene del secreto WIALON_TOKEN, no
# del archivo config.json (que no debe llevar el token cuando se sube a
# GitHub). Localmente, sigue funcionando igual que siempre con config.json.
MODO_NUBE = bool(os.environ.get("WIALON_TOKEN"))
TOKEN = os.environ.get("WIALON_TOKEN") or CONFIG["token"]

UNIDADES = CONFIG["unidades"]           # lista de {"id": ..., "nombre": ...}

if MODO_NUBE:
    fecha_manual_inicio = os.environ.get("FECHA_INICIO_MANUAL", "").strip()
    fecha_manual_fin = os.environ.get("FECHA_FIN_MANUAL", "").strip()
    if fecha_manual_inicio and fecha_manual_fin:
        # Corrida manual con rango de fechas especifico (ej. relleno de historial)
        FECHA_INICIO = datetime.strptime(fecha_manual_inicio, "%Y-%m-%d")
        FECHA_FIN = datetime.strptime(fecha_manual_fin, "%Y-%m-%d")
    else:
        # Corrida automatica nocturna: siempre procesa el dia de ayer completo.
        FECHA_INICIO = FECHA_FIN = datetime.utcnow() - timedelta(days=1)
        FECHA_INICIO = FECHA_INICIO.replace(hour=0, minute=0, second=0, microsecond=0)
        FECHA_FIN = FECHA_FIN.replace(hour=0, minute=0, second=0, microsecond=0)
else:
    FECHA_INICIO = datetime.strptime(CONFIG["fecha_inicio"], "%Y-%m-%d")
    FECHA_FIN = datetime.strptime(CONFIG["fecha_fin"], "%Y-%m-%d")

# Parametros de calibracion (ajustables en config.json si hace falta)
UMBRAL_GIRO_GRADOS = CONFIG.get("umbral_giro_grados", 25)
TOLERANCIA_LATERAL_M = CONFIG.get("tolerancia_lateral_m", 1.5)
TOLERANCIA_ANGULO_GRADOS = CONFIG.get("tolerancia_angulo_grados", 20)
DISTANCIA_MAX_CUARTEL_M = CONFIG.get("distancia_max_cuartel_m", 60)
LARGO_MINIMO_TRAMO_M = CONFIG.get("largo_minimo_tramo_m", 8)
AREA_MINIMA_REPORTE_HA = CONFIG.get("area_minima_reporte_ha", 0.05)
MINIMO_HILERAS_CUARTEL = CONFIG.get("minimo_hileras_cuartel", 5)
GAP_MAXIMO_HILERA_M = CONFIG.get("gap_maximo_hilera_m", 100)
VELOCIDAD_MAXIMA_TRABAJO_KMH = CONFIG.get("velocidad_maxima_trabajo_kmh", 14)

os.makedirs(CARPETA_MEMORIA, exist_ok=True)
os.makedirs(CARPETA_REPORTES, exist_ok=True)
os.makedirs(CARPETA_DATOS, exist_ok=True)


# ---------------------------------------------------------------------------
# Paso 1: conexion con Wialon
# ---------------------------------------------------------------------------

def wialon_login(token):
    """Autentica con el token y devuelve el session id (sid)."""
    params = json.dumps({"token": token})
    r = requests.get(
        f"{WIALON_HOST}/wialon/ajax.html",
        params={"svc": "token/login", "params": params},
        timeout=30,
    )
    data = r.json()
    if "eid" not in data:
        raise RuntimeError(f"Error al conectar con Wialon: {data}")
    return data["eid"]


def obtener_mensajes(sid, unit_id, dia):
    """Descarga los mensajes GPS de una unidad para un dia completo (UTC)."""
    desde = dia
    hasta = dia + timedelta(days=1)
    params = json.dumps({
        "itemId": unit_id,
        "timeFrom": int(desde.replace(tzinfo=timezone.utc).timestamp()),
        "timeTo": int(hasta.replace(tzinfo=timezone.utc).timestamp()),
        "flags": 0,
        "flagsMask": 0,
        "loadCount": 0xFFFFFFFF,
    })
    r = requests.get(
        f"{WIALON_HOST}/wialon/ajax.html",
        params={"svc": "messages/load_interval", "params": params, "sid": sid},
        timeout=60,
    )
    data = r.json()
    return data.get("messages", [])


# ---------------------------------------------------------------------------
# Paso 2: separar el track en tramos usando los giros
# ---------------------------------------------------------------------------

def rumbo(p1, p2):
    """Rumbo en grados (0-360) entre dos puntos (lon, lat)."""
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def segmentar_pasadas(puntos, umbral_giro=UMBRAL_GIRO_GRADOS):
    """
    puntos: lista de dicts {"punto": (lon, lat), "t": timestamp}, ordenados
    por tiempo.
    Devuelve una lista de segmentos (cada uno, una lista de puntos) que
    representan tramos de rumbo estable entre dos giros.
    """
    if len(puntos) < 3:
        return []

    segmentos = []
    segmento_actual = [puntos[0]]

    for i in range(1, len(puntos) - 1):
        r1 = rumbo(puntos[i - 1]["punto"], puntos[i]["punto"])
        r2 = rumbo(puntos[i]["punto"], puntos[i + 1]["punto"])
        cambio = abs((r2 - r1 + 180) % 360 - 180)

        segmento_actual.append(puntos[i])

        if cambio > umbral_giro:
            segmentos.append(segmento_actual)
            segmento_actual = [puntos[i]]

    segmento_actual.append(puntos[-1])
    segmentos.append(segmento_actual)
    return segmentos


# ---------------------------------------------------------------------------
# Conversion a metros (aproximacion plana local, sin dependencias externas)
# ---------------------------------------------------------------------------
# Valida para distancias de hasta varios kilometros alrededor del punto de
# referencia, que es mas que suficiente para el tamano de un cuartel/campo.

METROS_POR_GRADO_LAT = 110574.0


def punto_a_metros(punto_lonlat, referencia):
    lon, lat = punto_lonlat
    lon0, lat0 = referencia
    metros_por_grado_lon = 111320.0 * math.cos(math.radians(lat0))
    dx = (lon - lon0) * metros_por_grado_lon
    dy = (lat - lat0) * METROS_POR_GRADO_LAT
    return (dx, dy)


def metros_a_punto(punto_m, referencia):
    lon0, lat0 = referencia
    metros_por_grado_lon = 111320.0 * math.cos(math.radians(lat0))
    lon = lon0 + punto_m[0] / metros_por_grado_lon
    lat = lat0 + punto_m[1] / METROS_POR_GRADO_LAT
    return (lon, lat)


# ---------------------------------------------------------------------------
# Paso 3: deteccion y actualizacion de hileras
# ---------------------------------------------------------------------------

class Hilera:
    def __init__(self, id_, origen, direccion, min_proy, max_proy, intervalos=None):
        self.id = id_
        self.origen = origen          # (x, y) en metros, punto de referencia
        self.direccion = direccion    # vector unitario (dx, dy)
        self.min_proy = min_proy
        self.max_proy = max_proy
        self.intervalos = intervalos or []   # pasadas del periodo actual, sin fusionar

    def to_dict(self):
        return {
            "id": self.id, "origen": self.origen, "direccion": self.direccion,
            "min_proy": self.min_proy, "max_proy": self.max_proy,
            "intervalos": self.intervalos,
        }

    @staticmethod
    def from_dict(d):
        return Hilera(d["id"], tuple(d["origen"]), tuple(d["direccion"]),
                       d["min_proy"], d["max_proy"], d.get("intervalos", []))

    @property
    def largo_conocido(self):
        return self.max_proy - self.min_proy


def proyectar(punto_m, hilera):
    dx = punto_m[0] - hilera.origen[0]
    dy = punto_m[1] - hilera.origen[1]
    proy = dx * hilera.direccion[0] + dy * hilera.direccion[1]
    lateral = abs(dx * hilera.direccion[1] - dy * hilera.direccion[0])
    return proy, lateral


def asignar_o_crear_hilera(segmento_m, hileras, siguiente_id):
    p_ini, p_fin = segmento_m[0], segmento_m[-1]
    largo = math.hypot(p_fin[0] - p_ini[0], p_fin[1] - p_ini[1])
    if largo < LARGO_MINIMO_TRAMO_M:
        return None, siguiente_id  # tramo muy corto (giro, ruido): se descarta

    direccion = ((p_fin[0] - p_ini[0]) / largo, (p_fin[1] - p_ini[1]) / largo)

    mejor_hilera, mejor_dist = None, TOLERANCIA_LATERAL_M
    for h in hileras:
        cos_ang = direccion[0] * h.direccion[0] + direccion[1] * h.direccion[1]
        angulo = math.degrees(math.acos(max(-1, min(1, abs(cos_ang)))))
        if angulo > TOLERANCIA_ANGULO_GRADOS:
            continue

        proy_ini, lat_ini = proyectar(p_ini, h)
        proy_fin, lat_fin = proyectar(p_fin, h)

        # Descarta candidatos que apuntan igual pero estan lejos a lo largo
        # de la propia hilera (ej. otra hilera paralela, kilometros mas alla).
        proy_min_seg, proy_max_seg = min(proy_ini, proy_fin), max(proy_ini, proy_fin)
        if proy_max_seg < h.min_proy - GAP_MAXIMO_HILERA_M:
            continue
        if proy_min_seg > h.max_proy + GAP_MAXIMO_HILERA_M:
            continue

        dist_prom = (lat_ini + lat_fin) / 2
        if dist_prom < mejor_dist:
            mejor_dist, mejor_hilera = dist_prom, h

    if mejor_hilera:
        return mejor_hilera, siguiente_id

    nueva = Hilera(siguiente_id, p_ini, direccion, 0, largo)
    hileras.append(nueva)
    return nueva, siguiente_id + 1


def actualizar_hilera(hilera, segmento_m):
    proyecciones = [proyectar(p, hilera)[0] for p in segmento_m]
    p_min, p_max = min(proyecciones), max(proyecciones)
    hilera.min_proy = min(hilera.min_proy, p_min)
    hilera.max_proy = max(hilera.max_proy, p_max)
    hilera.intervalos.append([round(p_min, 1), round(p_max, 1)])


# ---------------------------------------------------------------------------
# Paso 4: agrupar hileras en cuarteles (cercanas y paralelas)
# ---------------------------------------------------------------------------

def agrupar_en_cuarteles(hileras):
    padre = {h.id: h.id for h in hileras}

    def encontrar(x):
        while padre[x] != x:
            x = padre[x]
        return x

    def unir(a, b):
        ra, rb = encontrar(a), encontrar(b)
        if ra != rb:
            padre[ra] = rb

    for i, h1 in enumerate(hileras):
        centro1 = (
            h1.origen[0] + h1.direccion[0] * (h1.min_proy + h1.max_proy) / 2,
            h1.origen[1] + h1.direccion[1] * (h1.min_proy + h1.max_proy) / 2,
        )
        for h2 in hileras[i + 1:]:
            cos_ang = h1.direccion[0] * h2.direccion[0] + h1.direccion[1] * h2.direccion[1]
            angulo = math.degrees(math.acos(max(-1, min(1, abs(cos_ang)))))
            if angulo > TOLERANCIA_ANGULO_GRADOS:
                continue
            centro2 = (
                h2.origen[0] + h2.direccion[0] * (h2.min_proy + h2.max_proy) / 2,
                h2.origen[1] + h2.direccion[1] * (h2.min_proy + h2.max_proy) / 2,
            )
            dist = math.hypot(centro1[0] - centro2[0], centro1[1] - centro2[1])
            if dist <= DISTANCIA_MAX_CUARTEL_M:
                unir(h1.id, h2.id)

    grupos = {}
    for h in hileras:
        raiz = encontrar(h.id)
        grupos.setdefault(raiz, []).append(h)
    return list(grupos.values())


# ---------------------------------------------------------------------------
# Paso 5: area del cuartel por integracion entre hileras vecinas
# ---------------------------------------------------------------------------

def envolvente_convexa(puntos):
    """Casco convexo (algoritmo monotone chain), sin dependencias externas."""
    puntos = sorted(set(puntos))
    if len(puntos) <= 2:
        return puntos

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior = []
    for p in puntos:
        while len(inferior) >= 2 and cruz(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)

    superior = []
    for p in reversed(puntos):
        while len(superior) >= 2 and cruz(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)

    return inferior[:-1] + superior[:-1]


def area_poligono_m2(vertices):
    if len(vertices) < 3:
        return 0.0
    doble_area = 0.0
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        doble_area += x1 * y2 - x2 * y1
    return abs(doble_area) / 2


def calcular_area_cuartel_m2(hileras_cuartel):
    """
    Area del contorno que envuelve todas las hileras conocidas del cuartel
    (como dibujar el poligono a mano sobre el mapa satelital), calculada
    con la envolvente convexa de los extremos de cada hilera.
    """
    puntos = []
    for h in hileras_cuartel:
        p1 = (h.origen[0] + h.direccion[0] * h.min_proy, h.origen[1] + h.direccion[1] * h.min_proy)
        p2 = (h.origen[0] + h.direccion[0] * h.max_proy, h.origen[1] + h.direccion[1] * h.max_proy)
        puntos.append(p1)
        puntos.append(p2)

    hull = envolvente_convexa(puntos)
    area = area_poligono_m2(hull)
    if area > 0:
        return area

    # Caso degenerado (una sola hilera, o todas perfectamente alineadas):
    # no hay contorno real que envolver, se estima con un ancho minimo.
    largo_total = sum(h.largo_conocido for h in hileras_cuartel)
    ancho_estimado = 3.0
    return largo_total * ancho_estimado


# ---------------------------------------------------------------------------
# Paso 6: cobertura del dia y conteo de pasadas
# ---------------------------------------------------------------------------

def union_intervalos(intervalos):
    if not intervalos:
        return [], 0.0
    ordenados = sorted(intervalos)
    fusionados = [list(ordenados[0])]
    for ini, fin in ordenados[1:]:
        if ini <= fusionados[-1][1]:
            fusionados[-1][1] = max(fusionados[-1][1], fin)
        else:
            fusionados.append([ini, fin])
    largo_total = sum(f[1] - f[0] for f in fusionados)
    return fusionados, largo_total


def contar_pasadas_max(intervalos):
    if not intervalos:
        return 0
    eventos = []
    for ini, fin in intervalos:
        eventos.append((ini, 1))
        eventos.append((fin, -1))
    eventos.sort()
    conteo, maximo = 0, 0
    for _, delta in eventos:
        conteo += delta
        maximo = max(maximo, conteo)
    return maximo


# ---------------------------------------------------------------------------
# Persistencia: memoria por unidad (referencia de medicion + hileras)
# ---------------------------------------------------------------------------

def ruta_memoria(unit_id):
    return os.path.join(CARPETA_MEMORIA, f"unidad_{unit_id}.json")


def cargar_estado(unit_id):
    ruta = ruta_memoria(unit_id)
    if not os.path.exists(ruta):
        return None, []
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    referencia = tuple(data["referencia"]) if data.get("referencia") else None
    hileras = [Hilera.from_dict(d) for d in data.get("hileras", [])]
    return referencia, hileras


def guardar_estado(unit_id, referencia, hileras):
    ruta = ruta_memoria(unit_id)
    data = {
        "referencia": list(referencia) if referencia else None,
        "hileras": [h.to_dict() for h in hileras],
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Exportacion a KML para revisar visualmente contra la foto satelital
# ---------------------------------------------------------------------------

VERDE_TRABAJADO = "ff00ff00"
AMARILLO_DESCARTADO = "ff00ffff"


def exportar_kml(ruta_salida, unidades_procesadas):
    """
    unidades_procesadas: lista de (nombre_unidad, referencia, hileras, descartados)
    Genera un archivo KML: verde = tramo contado como hilera trabajada,
    amarillo = tramo descartado (camino/traslado o tramo muy corto).
    """
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>']

    for nombre_unidad, referencia, hileras, descartados in unidades_procesadas:
        if referencia is None:
            continue
        partes.append(f'<Folder><name>{nombre_unidad}</name>')

        descartados_extra = list(descartados)
        cuarteles = agrupar_en_cuarteles(hileras) if hileras else []
        for grupo in cuarteles:
            ref_id = min(h.id for h in grupo)
            area_ok = calcular_area_cuartel_m2(grupo) / 10000 >= AREA_MINIMA_REPORTE_HA
            cuenta_en_reporte = len(grupo) >= MINIMO_HILERAS_CUARTEL and area_ok

            for h in grupo:
                p1_m = (
                    h.origen[0] + h.direccion[0] * h.min_proy,
                    h.origen[1] + h.direccion[1] * h.min_proy,
                )
                p2_m = (
                    h.origen[0] + h.direccion[0] * h.max_proy,
                    h.origen[1] + h.direccion[1] * h.max_proy,
                )
                lon1, lat1 = metros_a_punto(p1_m, referencia)
                lon2, lat2 = metros_a_punto(p2_m, referencia)

                if cuenta_en_reporte:
                    partes.append(
                        f'<Placemark><name>Trabajado - Cuartel {ref_id} - Hilera {h.id}</name>'
                        f'<Style><LineStyle><color>{VERDE_TRABAJADO}</color><width>3</width>'
                        f'</LineStyle></Style>'
                        f'<LineString><coordinates>{lon1},{lat1},0 {lon2},{lat2},0'
                        f'</coordinates></LineString></Placemark>'
                    )
                else:
                    partes.append(
                        f'<Placemark><name>Descartado (grupo chico) - Hilera {h.id}</name>'
                        f'<Style><LineStyle><color>{AMARILLO_DESCARTADO}</color><width>3</width>'
                        f'</LineStyle></Style>'
                        f'<LineString><coordinates>{lon1},{lat1},0 {lon2},{lat2},0'
                        f'</coordinates></LineString></Placemark>'
                    )

        for (lon1, lat1), (lon2, lat2) in descartados_extra:
            partes.append(
                '<Placemark><name>Descartado</name>'
                f'<Style><LineStyle><color>{AMARILLO_DESCARTADO}</color><width>3</width>'
                '</LineStyle></Style>'
                f'<LineString><coordinates>{lon1},{lat1},0 {lon2},{lat2},0'
                '</coordinates></LineString></Placemark>'
            )

        partes.append('</Folder>')

    partes.append('</Document></kml>')

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write("".join(partes))


# ---------------------------------------------------------------------------
# Historico acumulado (para la pagina web)
# ---------------------------------------------------------------------------

def cargar_historico():
    if not os.path.exists(RUTA_HISTORICO):
        return []
    with open(RUTA_HISTORICO, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_historico(registros):
    with open(RUTA_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def actualizar_historico(df_resumen):
    """Combina las filas nuevas con el historico ya guardado, reemplazando
    (no duplicando) cualquier fila con la misma fecha+maquina+cuartel."""
    historico = cargar_historico()
    indice = {
        (r["fecha"], r["maquina"], r["cuartel"]): i
        for i, r in enumerate(historico)
    }

    for _, fila in df_resumen.iterrows():
        registro = {
            "fecha": fila["Fecha"],
            "maquina": fila["Máquina"],
            "cuartel": int(fila["Cuartel (ref.)"]),
            "n_hileras": int(fila["N° hileras conocidas"]),
            "area_total_ha": float(fila["Área estimada total cuartel (ha)"]),
            "area_trabajada_ha": float(fila["Hectáreas trabajadas del cuartel"]),
        }
        clave = (registro["fecha"], registro["maquina"], registro["cuartel"])
        if clave in indice:
            historico[indice[clave]] = registro
        else:
            historico.append(registro)
            indice[clave] = len(historico) - 1

    guardar_historico(historico)


# ---------------------------------------------------------------------------
# Orquestacion principal
# ---------------------------------------------------------------------------

def velocidad_kmh_segmento(segmento, segmento_m):
    """Velocidad promedio del tramo, calculada de la distancia real y el tiempo."""
    if len(segmento) < 2:
        return 0.0
    dist_total = 0.0
    for i in range(len(segmento_m) - 1):
        dist_total += math.hypot(
            segmento_m[i + 1][0] - segmento_m[i][0],
            segmento_m[i + 1][1] - segmento_m[i][1],
        )
    t0, t1 = segmento[0].get("t"), segmento[-1].get("t")
    if not t0 or not t1 or t1 <= t0:
        return 0.0
    horas = (t1 - t0) / 3600
    return (dist_total / 1000) / horas


def procesar_puntos(puntos, referencia, hileras, descartados):
    segmentos = segmentar_pasadas(puntos)

    siguiente_id = (max((h.id for h in hileras), default=0)) + 1
    hileras_tocadas_hoy = set()

    for seg in segmentos:
        seg_m = [punto_a_metros(p["punto"], referencia) for p in seg]

        if velocidad_kmh_segmento(seg, seg_m) > VELOCIDAD_MAXIMA_TRABAJO_KMH:
            descartados.append((seg[0]["punto"], seg[-1]["punto"]))
            continue

        hilera, siguiente_id = asignar_o_crear_hilera(seg_m, hileras, siguiente_id)
        if hilera is None:
            descartados.append((seg[0]["punto"], seg[-1]["punto"]))
            continue
        actualizar_hilera(hilera, seg_m)
        hileras_tocadas_hoy.add(hilera.id)

    return list(hileras_tocadas_hoy)


def generar_reporte(sid):
    filas_resumen = []
    filas_detalle = []
    descartados_por_unidad = {}

    for unidad in UNIDADES:
        referencia, hileras = cargar_estado(unidad["id"])
        descartados = []
        descartados_por_unidad[unidad["id"]] = descartados

        dia = FECHA_INICIO
        while dia <= FECHA_FIN:
            mensajes = obtener_mensajes(sid, unidad["id"], dia)
            puntos = [
                {"punto": (m["pos"]["x"], m["pos"]["y"]), "t": m.get("t")}
                for m in mensajes if m.get("pos")
            ]

            if len(puntos) >= 3:
                if referencia is None:
                    referencia = puntos[0]["punto"]

                cobertura_antes = {h.id: union_intervalos(h.intervalos)[1] for h in hileras}
                hileras_tocadas_hoy = procesar_puntos(puntos, referencia, hileras, descartados)

                if hileras_tocadas_hoy:
                    cuarteles = agrupar_en_cuarteles(hileras)
                    for grupo in cuarteles:
                        ids_grupo = {h.id for h in grupo}
                        if not (ids_grupo & set(hileras_tocadas_hoy)):
                            continue

                        if len(grupo) < MINIMO_HILERAS_CUARTEL:
                            continue  # muy pocas hileras: probable tramo de traslado o maniobra, no un cuartel real

                        area_total_m2 = calcular_area_cuartel_m2(grupo)
                        area_total_ha = area_total_m2 / 10000
                        if area_total_ha < AREA_MINIMA_REPORTE_HA:
                            continue  # probable ruido (maniobra/tramo suelto), no un cuartel real

                        largo_total = sum(h.largo_conocido for h in grupo)
                        largo_cubierto_hoy = 0.0
                        filas_detalle_grupo = []
                        for h in grupo:
                            _, cubierto_total = union_intervalos(h.intervalos)
                            cubierto_antes = cobertura_antes.get(h.id, 0.0)
                            delta_hoy = max(0.0, cubierto_total - cubierto_antes)
                            largo_cubierto_hoy += delta_hoy
                            pasadas = contar_pasadas_max(h.intervalos)
                            filas_detalle_grupo.append({
                                "Fecha": dia.strftime("%Y-%m-%d"),
                                "Máquina": unidad["nombre"],
                                "Cuartel (ref.)": min(g.id for g in grupo),
                                "Hilera": h.id,
                                "Largo conocido (m)": round(h.largo_conocido, 1),
                                "Máx. pasadas (acumulado)": pasadas,
                            })

                        area_trabajada_ha = (
                            area_total_ha * (largo_cubierto_hoy / largo_total)
                            if largo_total else 0
                        )
                        if round(area_trabajada_ha, 2) <= 0:
                            continue  # sin hectáreas nuevas ese día: no aporta al informe

                        filas_detalle.extend(filas_detalle_grupo)
                        filas_resumen.append({
                            "Fecha": dia.strftime("%Y-%m-%d"),
                            "Máquina": unidad["nombre"],
                            "Cuartel (ref.)": min(g.id for g in grupo),
                            "N° hileras conocidas": len(grupo),
                            "Área estimada total cuartel (ha)": round(area_total_ha, 2),
                            "Hectáreas trabajadas del cuartel": round(area_trabajada_ha, 2),
                        })

            dia += timedelta(days=1)

        guardar_estado(unidad["id"], referencia, hileras)

    return pd.DataFrame(filas_resumen), pd.DataFrame(filas_detalle), descartados_por_unidad


def main():
    print("Conectando con Wialon...")
    sid = wialon_login(TOKEN)
    print("Conectado.")

    print(f"Procesando del {FECHA_INICIO.date()} al {FECHA_FIN.date()}...")
    df_resumen, df_detalle, descartados_por_unidad = generar_reporte(sid)

    if not df_resumen.empty:
        actualizar_historico(df_resumen)
        print(f"Historico actualizado en: {RUTA_HISTORICO}")

    nombre_salida = os.path.join(
        CARPETA_REPORTES,
        f"hectareas_{FECHA_INICIO.date()}_a_{FECHA_FIN.date()}.xlsx",
    )
    with pd.ExcelWriter(nombre_salida) as writer:
        df_resumen.to_excel(writer, sheet_name="Resumen por cuartel", index=False)
        df_detalle.to_excel(writer, sheet_name="Detalle por hilera", index=False)

    print(f"Listo. Reporte generado en: {nombre_salida}")
    if df_resumen.empty:
        print("No se encontro actividad de trabajo en el periodo indicado.")
    else:
        print(df_resumen.to_string(index=False))

    unidades_para_kml = []
    for unidad in UNIDADES:
        referencia, hileras = cargar_estado(unidad["id"])
        descartados = descartados_por_unidad.get(unidad["id"], [])
        unidades_para_kml.append((unidad["nombre"], referencia, hileras, descartados))

    ruta_kml = os.path.join(CARPETA_DATOS, "hileras_detectadas.kml")
    exportar_kml(ruta_kml, unidades_para_kml)
    print(f"Mapa de revision generado en: {ruta_kml}")
    print("Abrelo con Google Earth o subelo a Google My Maps para comparar contra la foto satelital.")


if __name__ == "__main__":
    main()
