"""
reporte_hectareas.py

Calcula las hectareas trabajadas por dia y por maquina, usando geocercas
reales (dibujadas por el usuario en Wialon) como borde de cada cuartel, y
deteccion automatica de hileras para saber cuanto se avanzo cuando el
cuartel no se completa entero.

Como funciona, en resumen:
  1. Descarga las geocercas (cuarteles reales) desde Wialon, con su nombre,
     su contorno y su area exacta.
  2. Descarga el track GPS del dia desde Wialon (una maquina a la vez).
  3. Para cada geocerca, filtra los puntos del track que caen DENTRO de su
     contorno. Todo lo que quede afuera (caminos, galpon, traslados) se
     descarta automaticamente, sin depender de reglas de velocidad ni
     distancias.
  4. Dentro de cada geocerca, separa el track en tramos usando los giros
     (cambios de rumbo) como frontera: cada tramo recto entre dos giros es
     una pasada candidata por una hilera. Se descartan ademas los tramos
     muy rapidos (traslado dentro de la misma geocerca, ej. camino interno).
  5. Compara cada tramo contra las hileras ya conocidas de esa
     maquina+geocerca (guardadas en un archivo de memoria) y lo asigna a
     la que corresponda, o crea una hilera nueva si no calza con ninguna.
     El largo conocido de cada hilera crece con cada pasada nueva.
  6. Mide la cobertura sobre una grilla de celdas de 1 m dentro de cada
     geocerca: cada hilera marca una franja de un espaciado de ancho
     (alargada hasta el borde si llega a la cabecera), se rellenan las
     franjas sin marcar mas angostas que un espaciado, y se unen las
     celdas de TODAS las maquinas (una hilera repetida cuenta una vez).
  7. Avance del cuartel = celdas trabajadas / celdas de la geocerca. Las
     hectareas nuevas de cada dia se acreditan a la maquina que cubrio
     primero esas celdas (los dias se procesan en orden cronologico).
  8. Exporta un Excel y un mapa KML para revisar.

COMO SE USA (ver tambien LEEME.txt):
  1. Dibuja una geocerca en Wialon por cada cuartel real (Geocercas ->
     Crear geocerca -> poligono sobre el contorno del cuartel).
  2. Completa config.json con tu token y los datos de tus maquinas.
  3. Corre en la terminal:  python3 reporte_hectareas.py
  4. Revisa el Excel que se genera en la carpeta "reportes".

La "memoria" de cada combinacion maquina+cuartel se guarda en la carpeta
"memoria_hileras/". No la borres: ahi es donde el programa va aprendiendo
el largo real de cada hilera con cada corrida.
"""

import json
import math
import os
import re
import statistics
import unicodedata
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
RUTA_AVANCE_CUARTELES = os.path.join(CARPETA_DATOS, "avance_cuarteles.json")

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
        FECHA_INICIO = datetime.strptime(fecha_manual_inicio, "%Y-%m-%d")
        FECHA_FIN = datetime.strptime(fecha_manual_fin, "%Y-%m-%d")
    else:
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
LARGO_MINIMO_TRAMO_M = CONFIG.get("largo_minimo_tramo_m", 8)
GAP_MAXIMO_HILERA_M = CONFIG.get("gap_maximo_hilera_m", 100)
VELOCIDAD_MAXIMA_TRABAJO_KMH = CONFIG.get("velocidad_maxima_trabajo_kmh", 14)
MINIMO_PUNTOS_EN_GEOCERCA = CONFIG.get("minimo_puntos_en_geocerca", 3)
# Distancia maxima entre el extremo de una hilera y el borde de la geocerca
# (en la posicion de ESA hilera) para considerar que la hilera llego al final
# (cabecera + distancia entre puntos GPS).
TOLERANCIA_CABECERA_M = CONFIG.get("tolerancia_cabecera_m", 20)
CUARTELES_INCLUIDOS = [n.strip().lower() for n in CONFIG.get("cuarteles_incluidos", [])]
UMBRAL_CIERRE_PORCENTAJE = CONFIG.get("umbral_cierre_porcentaje", 0.95)
# Pasadas a menos de esta distancia lateral se consideran la misma hilera
# fisica (el GPS a veces parte una hilera en varias lineas paralelas).
TOLERANCIA_MISMA_HILERA_M = CONFIG.get("tolerancia_misma_hilera_m", 1.5)
# Grilla para medir la cobertura, y espaciado a usar cuando no se puede medir.
TAMANO_CELDA_M = CONFIG.get("tamano_celda_m", 1.0)
ESPACIADO_HILERAS_DEFECTO_M = CONFIG.get("espaciado_hileras_defecto_m", 4.0)

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
# Paso 1b: geocercas (cuarteles reales dibujados en Wialon)
# ---------------------------------------------------------------------------

def obtener_resource_ids(sid):
    """Busca todos los recursos/cuentas de Wialon donde puede haber geocercas."""
    params = json.dumps({
        "spec": {
            "itemsType": "avl_resource",
            "propName": "sys_name",
            "propValueMask": "*",
            "sortType": "sys_name",
        },
        "force": 1,
        "flags": 1,
        "from": 0,
        "to": 0,
    })
    r = requests.get(
        f"{WIALON_HOST}/wialon/ajax.html",
        params={"svc": "core/search_items", "params": params, "sid": sid},
        timeout=30,
    )
    data = r.json()
    return [item["id"] for item in data.get("items", [])]


def area_poligono_m2(vertices_metros):
    if len(vertices_metros) < 3:
        return 0.0
    doble_area = 0.0
    n = len(vertices_metros)
    for i in range(n):
        x1, y1 = vertices_metros[i]
        x2, y2 = vertices_metros[(i + 1) % n]
        doble_area += x1 * y2 - x2 * y1
    return abs(doble_area) / 2


def obtener_geocercas(sid):
    """
    Devuelve una lista de cuarteles reales (geocercas de tipo poligono),
    con su nombre, su contorno (lon, lat) y su area real en hectareas
    (calculada por nosotros mismos a partir del contorno, en metros).
    """
    geocercas = []
    for resource_id in obtener_resource_ids(sid):
        params = json.dumps({"itemId": resource_id, "flags": 0x1C})
        r = requests.get(
            f"{WIALON_HOST}/wialon/ajax.html",
            params={"svc": "resource/get_zone_data", "params": params, "sid": sid},
            timeout=30,
        )
        data = r.json()
        if not isinstance(data, list):
            continue
        for zona in data:
            if zona.get("t") != 2:
                continue  # solo poligonos (1=linea, 2=poligono, 3=circulo)
            nombre = zona.get("n", "")
            if CUARTELES_INCLUIDOS and nombre.strip().lower() not in CUARTELES_INCLUIDOS:
                continue  # no esta en la lista de cuarteles reales de config.json
            puntos = zona.get("p") or []
            if len(puntos) < 3:
                continue
            contorno = [(p["x"], p["y"]) for p in puntos]
            referencia = contorno[0]
            contorno_m = [punto_a_metros(p, referencia) for p in contorno]
            area_m2 = area_poligono_m2(contorno_m)
            if area_m2 <= 0:
                continue
            geocercas.append({
                "nombre": zona.get("n", f"Geocerca {zona.get('id')}"),
                "contorno": contorno,
                "area_ha": area_m2 / 10000,
            })
    return geocercas


def punto_en_poligono(punto, poligono):
    """Ray casting: True si el punto (lon, lat) cae dentro del poligono."""
    x, y = punto
    dentro = False
    n = len(poligono)
    j = n - 1
    for i in range(n):
        xi, yi = poligono[i]
        xj, yj = poligono[j]
        if (yi > y) != (yj > y):
            x_interseccion = (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi
            if x < x_interseccion:
                dentro = not dentro
        j = i
    return dentro


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


# ---------------------------------------------------------------------------
# Paso 3: deteccion y actualizacion de hileras
# ---------------------------------------------------------------------------

class Hilera:
    def __init__(self, id_, origen, direccion, min_proy, max_proy, intervalos=None, fechas=None,
                 primera_vez=None):
        self.id = id_
        self.origen = origen          # (x, y) en metros, punto de referencia
        self.direccion = direccion    # vector unitario (dx, dy)
        self.min_proy = min_proy
        self.max_proy = max_proy
        self.intervalos = intervalos or []   # pasadas del periodo actual, sin fusionar
        self.fechas = set(fechas) if fechas else set()   # dias (AAAA-MM-DD) en que se toco
        self.primera_vez = primera_vez   # hora (unix, UTC) de la primera pasada

    def to_dict(self):
        return {
            "id": self.id, "origen": self.origen, "direccion": self.direccion,
            "min_proy": self.min_proy, "max_proy": self.max_proy,
            "intervalos": self.intervalos,
            "fechas": sorted(self.fechas),
            "primera_vez": self.primera_vez,
        }

    @staticmethod
    def from_dict(d):
        return Hilera(d["id"], tuple(d["origen"]), tuple(d["direccion"]),
                       d["min_proy"], d["max_proy"], d.get("intervalos", []),
                       d.get("fechas", []), d.get("primera_vez"))

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


def actualizar_hilera(hilera, segmento_m, fecha_str, hora_unix=None):
    proyecciones = [proyectar(p, hilera)[0] for p in segmento_m]
    p_min, p_max = min(proyecciones), max(proyecciones)
    hilera.min_proy = min(hilera.min_proy, p_min)
    hilera.max_proy = max(hilera.max_proy, p_max)
    hilera.intervalos.append([round(p_min, 1), round(p_max, 1)])
    hilera.fechas.add(fecha_str)
    if hora_unix is not None and (hilera.primera_vez is None or hora_unix < hilera.primera_vez):
        hilera.primera_vez = hora_unix


def procesar_puntos(puntos, referencia, hileras, descartados, fecha_str):
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
        actualizar_hilera(hilera, seg_m, fecha_str, seg[0].get("t"))
        hileras_tocadas_hoy.add(hilera.id)

    return list(hileras_tocadas_hoy)


# ---------------------------------------------------------------------------
# Paso 6: cobertura del dia y conteo de pasadas
# ---------------------------------------------------------------------------

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


def angulo_entre_hileras(h1, h2):
    """Angulo (0 a 90 grados) entre las direcciones de dos hileras."""
    cos_ang = h1.direccion[0] * h2.direccion[0] + h1.direccion[1] * h2.direccion[1]
    return math.degrees(math.acos(max(-1, min(1, abs(cos_ang)))))


def hilera_referencia(hileras):
    """
    Hilera que marca la direccion real de las hileras del cuartel: la que
    tiene mas metros de hileras alineadas con ella. No se usa simplemente la
    mas larga, porque un traslado en diagonal cruzando el cuartel puede
    quedar registrado como la "hilera" mas larga y torcer todos los calculos.
    """
    def metros_alineados(h):
        return sum(
            otra.largo_conocido for otra in hileras
            if angulo_entre_hileras(h, otra) <= TOLERANCIA_ANGULO_GRADOS
        )
    return max(hileras, key=lambda h: (metros_alineados(h), h.largo_conocido))


def filtrar_hileras_regulares(hileras):
    """
    Separa las hileras alineadas con la direccion del cuartel de los tramos
    cruzados (traslados en diagonal, vueltas de cabecera), que no son
    hileras. Devuelve (alineadas, cruzadas).
    """
    if len(hileras) < 2:
        return hileras, []
    ref = hilera_referencia(hileras)
    alineadas, cruzadas = [], []
    for h in hileras:
        (alineadas if angulo_entre_hileras(h, ref) <= TOLERANCIA_ANGULO_GRADOS else cruzadas).append(h)
    return alineadas, cruzadas


def espaciado_real_m(hileras_alineadas):
    """
    Espaciado entre hileras fisicas vecinas (mediana). Antes se agrupan las
    pasadas a menos de TOLERANCIA_MISMA_HILERA_M, que son la misma hilera
    partida por el GPS; si no, el espaciado sale mucho menor que el real.
    """
    if len(hileras_alineadas) < 2:
        return ESPACIADO_HILERAS_DEFECTO_M
    ref = hilera_referencia(hileras_alineadas)
    posiciones = sorted(
        (h.origen[0] - ref.origen[0]) * (-ref.direccion[1]) + (h.origen[1] - ref.origen[1]) * ref.direccion[0]
        for h in hileras_alineadas
    )
    grupos = [[posiciones[0]]]
    for pos in posiciones[1:]:
        if pos - grupos[-1][-1] < TOLERANCIA_MISMA_HILERA_M:
            grupos[-1].append(pos)
        else:
            grupos.append([pos])
    centros = [statistics.mean(g) for g in grupos]
    gaps = [b - a for a, b in zip(centros, centros[1:])]
    return statistics.median(gaps) if gaps else ESPACIADO_HILERAS_DEFECTO_M


def tramo_geocerca_en_hilera(hilera, contorno_m):
    """
    Devuelve (ini, fin), en la misma escala que min_proy/max_proy, del tramo
    de la recta de la hilera que queda dentro de la geocerca, en la posicion
    de ESA hilera. Como el contorno no siempre es rectangular, cada hilera
    tiene su propio largo real. Devuelve None si no se puede calcular.
    """
    cruces = []
    n = len(contorno_m)
    for i in range(n):
        a, b = contorno_m[i], contorno_m[(i + 1) % n]
        lat_a = (a[0] - hilera.origen[0]) * hilera.direccion[1] - (a[1] - hilera.origen[1]) * hilera.direccion[0]
        lat_b = (b[0] - hilera.origen[0]) * hilera.direccion[1] - (b[1] - hilera.origen[1]) * hilera.direccion[0]
        if (lat_a > 0) != (lat_b > 0):
            t = lat_a / (lat_a - lat_b)
            proy_a, proy_b = proyectar(a, hilera)[0], proyectar(b, hilera)[0]
            cruces.append(proy_a + t * (proy_b - proy_a))
    cruces.sort()
    tramos = [(cruces[i], cruces[i + 1]) for i in range(0, len(cruces) - 1, 2)]
    if not tramos:
        return None

    centro = (hilera.min_proy + hilera.max_proy) / 2
    return min(tramos, key=lambda t: 0 if t[0] <= centro <= t[1] else min(abs(centro - t[0]), abs(centro - t[1])))


def hilera_llega_a_los_bordes(hilera, contorno_m):
    """True si la hilera se recorrio de borde a borde de la geocerca (en su
    propia posicion), con la tolerancia de cabecera."""
    tramo = tramo_geocerca_en_hilera(hilera, contorno_m)
    if tramo is None:
        return False
    return (
        hilera.min_proy - tramo[0] <= TOLERANCIA_CABECERA_M
        and tramo[1] - hilera.max_proy <= TOLERANCIA_CABECERA_M
    )


# ---------------------------------------------------------------------------
# Paso 7: cobertura sobre una grilla de celdas
# ---------------------------------------------------------------------------

_grillas = {}


def grilla_geocerca(geo):
    """Celdas (i, j) de TAMANO_CELDA_M que caen dentro de la geocerca, en
    metros respecto del primer punto de su contorno. Se calcula una vez."""
    if geo["nombre"] not in _grillas:
        referencia = geo["contorno"][0]
        contorno_m = [punto_a_metros(p, referencia) for p in geo["contorno"]]
        xs = [p[0] for p in contorno_m]
        ys = [p[1] for p in contorno_m]
        celdas = set()
        for i in range(int(math.floor(min(xs) / TAMANO_CELDA_M)), int(math.ceil(max(xs) / TAMANO_CELDA_M)) + 1):
            for j in range(int(math.floor(min(ys) / TAMANO_CELDA_M)), int(math.ceil(max(ys) / TAMANO_CELDA_M)) + 1):
                centro = ((i + 0.5) * TAMANO_CELDA_M, (j + 0.5) * TAMANO_CELDA_M)
                if punto_en_poligono(centro, contorno_m):
                    celdas.add((i, j))
        _grillas[geo["nombre"]] = (referencia, celdas)
    return _grillas[geo["nombre"]]


def marcar_franja_hilera(hilera, referencia, geo, ancho_m, marcadas):
    """Marca las celdas de la franja de `ancho_m` alrededor de la hilera,
    alargada hasta el borde de la geocerca en los extremos que llegan a la
    cabecera (TOLERANCIA_CABECERA_M)."""
    referencia_grilla, celdas = grilla_geocerca(geo)
    contorno_m = [punto_a_metros(p, referencia) for p in geo["contorno"]]
    ini, fin = hilera.min_proy, hilera.max_proy
    tramo = tramo_geocerca_en_hilera(hilera, contorno_m)
    if tramo is not None:
        if ini - tramo[0] <= TOLERANCIA_CABECERA_M:
            ini = min(ini, tramo[0])
        if tramo[1] - fin <= TOLERANCIA_CABECERA_M:
            fin = max(fin, tramo[1])

    def a_grilla(proy):
        punto = (hilera.origen[0] + hilera.direccion[0] * proy, hilera.origen[1] + hilera.direccion[1] * proy)
        return punto_a_metros(metros_a_punto(punto, referencia), referencia_grilla)

    a, b = a_grilla(ini), a_grilla(fin)
    largo = math.hypot(b[0] - a[0], b[1] - a[1])
    if largo < 0.5:
        return
    ux, uy = (b[0] - a[0]) / largo, (b[1] - a[1]) / largo
    paso = TAMANO_CELDA_M / 2
    n_largo = int(largo / paso) + 1
    n_ancho = int(ancho_m / paso) + 1
    for k in range(n_largo + 1):
        t = min(k * paso, largo)
        for m in range(n_ancho + 1):
            d = -ancho_m / 2 + min(m * paso, ancho_m)
            x = a[0] + ux * t - uy * d
            y = a[1] + uy * t + ux * d
            celda = (int(math.floor(x / TAMANO_CELDA_M)), int(math.floor(y / TAMANO_CELDA_M)))
            if celda in celdas:
                marcadas.add(celda)


def rellenar_franjas_angostas(marcadas, celdas, radio_celdas):
    """Cierre morfologico: rellena las franjas sin marcar de menos de
    2 x radio (entre hileras no del todo paralelas, o contra el borde). Un
    hueco mas ancho, como una hilera saltada entera, queda sin rellenar."""
    if radio_celdas < 1 or not marcadas:
        return set(marcadas)
    disco = [(di, dj) for di in range(-radio_celdas, radio_celdas + 1)
             for dj in range(-radio_celdas, radio_celdas + 1) if di * di + dj * dj <= radio_celdas * radio_celdas]
    dilatadas = set()
    for i, j in marcadas:
        for di, dj in disco:
            dilatadas.add((i + di, j + dj))
    # Fuera de la geocerca cuenta como marcado, para que el borde no se "coma".
    cerradas = {
        c for c in celdas
        if c in dilatadas and all(
            (c[0] + di, c[1] + dj) in dilatadas or (c[0] + di, c[1] + dj) not in celdas
            for di, dj in disco
        )
    }
    return cerradas | (marcadas & celdas)


def celdas_trabajadas(geo, trabajos):
    """
    Celdas trabajadas de una geocerca, uniendo todas las maquinas.
    trabajos: lista de (referencia, hileras) de cada maquina.
    """
    _, celdas = grilla_geocerca(geo)
    marcadas = set()
    espaciados = []
    for referencia, hileras in trabajos:
        if referencia is None or not hileras:
            continue
        alineadas, _ = filtrar_hileras_regulares(hileras)
        espaciado = espaciado_real_m(alineadas)
        espaciados.append(espaciado)
        for h in alineadas:
            marcar_franja_hilera(h, referencia, geo, espaciado, marcadas)
    if not espaciados:
        return set()
    radio = int(round(max(espaciados) / 2 / TAMANO_CELDA_M))
    return rellenar_franjas_angostas(marcadas, celdas, radio)


def fraccion_trabajada(geo, celdas_cubiertas):
    _, celdas = grilla_geocerca(geo)
    return len(celdas_cubiertas) / len(celdas) if celdas else 0.0


def slug(texto):
    """Convierte un nombre en un identificador simple para nombres de archivo."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto).strip("_")
    return texto or "cuartel"


def escapar_xml(texto):
    """Escapa caracteres especiales para que el texto sea valido dentro de un KML."""
    texto = str(texto)
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ---------------------------------------------------------------------------
# Exportacion a KML para revisar visualmente contra la foto satelital
# ---------------------------------------------------------------------------

# Colores KML (formato aabbggrr)
VERDE_CUARTEL_COMPLETO = "ff00ff00"
AZUL_HILERA_COMPLETA = "ffff8000"
ROJO_HILERA_PARCIAL = "ff0000ff"
GRIS_NO_CUENTA = "ff888888"
AMARILLO_DESCARTADO = "ff00ffff"
NEGRO_GEOCERCA = "ff000000"


def avance_total_por_geocerca(unidades_procesadas, geocercas):
    """
    Avance de cada geocerca con el trabajo de TODAS las maquinas (union de
    celdas: una hilera repetida por dos maquinas cuenta una sola vez).
    Devuelve {nombre_geocerca: {"trabajado_ha", "area_total_ha",
    "porcentaje", "completo", "maquinas"}}.
    """
    trabajos = {}
    for nombre_maquina, hileras_por_geocerca, _ in unidades_procesadas:
        for nombre_geo, (referencia, hileras, _) in hileras_por_geocerca.items():
            if referencia is not None and hileras:
                trabajos.setdefault(nombre_geo, []).append((nombre_maquina, referencia, hileras))

    avance = {}
    for geo in geocercas:
        lista = trabajos.get(geo["nombre"])
        if not lista:
            continue
        fraccion = fraccion_trabajada(geo, celdas_trabajadas(geo, [(ref, hs) for _, ref, hs in lista]))
        avance[geo["nombre"]] = {
            "trabajado_ha": round(fraccion * geo["area_ha"], 4),
            "area_total_ha": round(geo["area_ha"], 4),
            "porcentaje": round(fraccion * 100, 1),
            "completo": fraccion >= UMBRAL_CIERRE_PORCENTAJE,
            "maquinas": sorted({m for m, _, _ in lista}),
        }
    return avance


def exportar_kml(ruta_salida, unidades_procesadas, geocercas, avance_total):
    """
    unidades_procesadas: lista de (nombre_unidad, hileras_por_geocerca, descartados)
        hileras_por_geocerca: dict {nombre_geocerca: (referencia, hileras)}
    avance_total: resultado de avance_total_por_geocerca (suma de TODAS las
        maquinas, aunque este KML muestre solo algunas).
    Genera un archivo KML: contorno de cada geocerca (marcada COMPLETA si
    entre todas las maquinas se llego al umbral de cierre). Hileras: verde
    si el cuartel esta terminado, azul si la hilera llego de borde a borde,
    rojo si es parcial, gris si es un tramo cruzado que no cuenta. Tramos
    descartados en amarillo.
    """
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>']

    partes.append('<Folder><name>Cuarteles (geocercas)</name>')
    for geo in geocercas:
        completa = avance_total.get(geo["nombre"], {}).get("completo", False)

        color_borde = NEGRO_GEOCERCA
        etiqueta = "COMPLETA" if completa else f"{geo['area_ha']:.2f} ha"
        coords = " ".join(f"{lon},{lat},0" for lon, lat in geo["contorno"] + [geo["contorno"][0]])
        nombre_geo_seguro = escapar_xml(geo["nombre"])
        partes.append(
            f'<Placemark><name>{nombre_geo_seguro} ({etiqueta})</name>'
            f'<Style><LineStyle><color>{color_borde}</color><width>6</width></LineStyle>'
            f'<PolyStyle><fill>0</fill></PolyStyle></Style>'
            f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}'
            f'</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>'
        )
    partes.append('</Folder>')

    for nombre_unidad, hileras_por_geocerca, descartados in unidades_procesadas:
        nombre_unidad_seguro = escapar_xml(nombre_unidad)
        partes.append(f'<Folder><name>{nombre_unidad_seguro}</name>')

        for nombre_geo, (referencia, hileras, area_acumulada_ha) in hileras_por_geocerca.items():
            if referencia is None:
                continue
            geo = next((g for g in geocercas if g["nombre"] == nombre_geo), None)
            geocerca_completa = avance_total.get(nombre_geo, {}).get("completo", False)
            _, cruzadas = filtrar_hileras_regulares(hileras)
            ids_cruzadas = {h.id for h in cruzadas}
            contorno_m = [punto_a_metros(p, referencia) for p in geo["contorno"]] if geo else []

            nombre_geo_seguro = escapar_xml(nombre_geo)
            for h in hileras:
                p1_m = (h.origen[0] + h.direccion[0] * h.min_proy, h.origen[1] + h.direccion[1] * h.min_proy)
                p2_m = (h.origen[0] + h.direccion[0] * h.max_proy, h.origen[1] + h.direccion[1] * h.max_proy)
                if math.hypot(p2_m[0] - p1_m[0], p2_m[1] - p1_m[1]) < 1.0:
                    continue
                lon1, lat1 = metros_a_punto(p1_m, referencia)
                lon2, lat2 = metros_a_punto(p2_m, referencia)
                if not all(math.isfinite(v) for v in (lon1, lat1, lon2, lat2)):
                    continue
                if geocerca_completa:
                    color_hilera, etiqueta = VERDE_CUARTEL_COMPLETO, " (cuartel completo)"
                elif h.id in ids_cruzadas:
                    color_hilera, etiqueta = GRIS_NO_CUENTA, " (no cuenta)"
                elif contorno_m and hilera_llega_a_los_bordes(h, contorno_m):
                    color_hilera, etiqueta = AZUL_HILERA_COMPLETA, " (hilera completa)"
                else:
                    color_hilera, etiqueta = ROJO_HILERA_PARCIAL, " (hilera parcial)"
                partes.append(
                    f'<Placemark><name>{nombre_geo_seguro} - Hilera {h.id}{etiqueta}</name>'
                    f'<Style><LineStyle><color>{color_hilera}</color><width>3</width>'
                    f'</LineStyle></Style>'
                    f'<LineString><coordinates>{lon1},{lat1},0 {lon2},{lat2},0'
                    f'</coordinates></LineString></Placemark>'
                )

        for (lon1, lat1), (lon2, lat2) in descartados:
            if not all(math.isfinite(v) for v in (lon1, lat1, lon2, lat2)):
                continue
            if lon1 == lon2 and lat1 == lat2:
                continue
            partes.append(
                '<Placemark><name>Descartado (fuera de geocerca o traslado)</name>'
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
# Persistencia: memoria por unidad + geocerca
# ---------------------------------------------------------------------------

def ruta_memoria(unit_id, nombre_geocerca):
    return os.path.join(CARPETA_MEMORIA, f"unidad_{unit_id}_cuartel_{slug(nombre_geocerca)}.json")


def cargar_estado(unit_id, nombre_geocerca):
    ruta = ruta_memoria(unit_id, nombre_geocerca)
    if not os.path.exists(ruta):
        return None, [], 0.0
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    referencia = tuple(data["referencia"]) if data.get("referencia") else None
    hileras = [Hilera.from_dict(d) for d in data.get("hileras", [])]
    area_acumulada_ha = data.get("area_acumulada_ha", 0.0)
    return referencia, hileras, area_acumulada_ha


def guardar_estado(unit_id, nombre_geocerca, referencia, hileras, area_acumulada_ha):
    ruta = ruta_memoria(unit_id, nombre_geocerca)
    data = {
        "referencia": list(referencia) if referencia else None,
        "hileras": [h.to_dict() for h in hileras],
        "area_acumulada_ha": area_acumulada_ha,
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
    historico = cargar_historico()
    indice = {(r["fecha"], r["maquina"], r["cuartel"]): i for i, r in enumerate(historico)}

    for _, fila in df_resumen.iterrows():
        registro = {
            "fecha": fila["Fecha"],
            "maquina": fila["Máquina"],
            "cuartel": str(fila["Cuartel"]),
            "n_hileras": int(fila["N° hileras conocidas"]),
            "area_total_ha": float(fila["Área real del cuartel (ha)"]),
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

def generar_reporte(sid, geocercas):
    """
    Procesa los dias en orden cronologico. Cada dia, en cada geocerca, las
    maquinas se procesan en el orden en que entraron a ella; las hectareas
    nuevas se acreditan a la maquina que cubrio primero esas celdas, asi el
    trabajo repetido por otra maquina no suma dos veces.
    """
    filas_resumen = []
    filas_detalle = []
    diagnostico = {geo["nombre"]: 0 for geo in geocercas}  # puntos totales vistos por geocerca
    descartados = {u["id"]: [] for u in UNIDADES}
    estado = {}  # (unit_id, nombre_geo) -> [referencia, hileras, area_acreditada_ha]

    def estado_de(unidad, geo):
        clave = (unidad["id"], geo["nombre"])
        if clave not in estado:
            estado[clave] = list(cargar_estado(unidad["id"], geo["nombre"]))
        return estado[clave]

    cobertura = {}  # nombre_geo -> celdas trabajadas actuales (todas las maquinas)

    def cobertura_actual(geo):
        if geo["nombre"] not in cobertura:
            trabajos = []
            for u in UNIDADES:
                referencia, hileras, _ = estado_de(u, geo)
                if referencia is not None and hileras:
                    trabajos.append((referencia, hileras))
            cobertura[geo["nombre"]] = celdas_trabajadas(geo, trabajos)
        return cobertura[geo["nombre"]]

    dia = FECHA_INICIO
    while dia <= FECHA_FIN:
        fecha_str = dia.strftime("%Y-%m-%d")
        entradas = {geo["nombre"]: [] for geo in geocercas}  # geo -> [(hora_entrada, unidad, puntos)]
        for unidad in UNIDADES:
            mensajes = obtener_mensajes(sid, unidad["id"], dia)
            puntos = [
                {"punto": (m["pos"]["x"], m["pos"]["y"]), "t": m.get("t")}
                for m in mensajes if m.get("pos")
            ]
            if len(puntos) < 3:
                continue
            for geo in geocercas:
                puntos_geo = [p for p in puntos if punto_en_poligono(p["punto"], geo["contorno"])]
                diagnostico[geo["nombre"]] += len(puntos_geo)
                if len(puntos_geo) >= MINIMO_PUNTOS_EN_GEOCERCA:
                    hora_entrada = min((p["t"] for p in puntos_geo if p["t"] is not None), default=0)
                    entradas[geo["nombre"]].append((hora_entrada, unidad, puntos_geo))

        for geo in geocercas:
            for _, unidad, puntos_geo in sorted(entradas[geo["nombre"]], key=lambda e: e[0]):
                referencia, hileras, area_acreditada_ha = estado_de(unidad, geo)
                if referencia is None:
                    referencia = puntos_geo[0]["punto"]
                ids_antes = {h.id for h in hileras}
                celdas_antes = cobertura_actual(geo)

                hileras_tocadas_hoy = procesar_puntos(
                    puntos_geo, referencia, hileras, descartados[unidad["id"]], fecha_str
                )
                if hileras_tocadas_hoy:
                    estado[(unidad["id"], geo["nombre"])][0] = referencia
                    cobertura.pop(geo["nombre"], None)
                    celdas_despues = cobertura_actual(geo)
                    _, celdas_geo = grilla_geocerca(geo)
                    nuevas = len(celdas_despues - celdas_antes)
                    area_trabajada_ha = nuevas / len(celdas_geo) * geo["area_ha"] if celdas_geo else 0.0
                    area_acreditada_ha += area_trabajada_ha
                    alineadas, _ = filtrar_hileras_regulares(hileras)

                    if round(area_trabajada_ha, 2) > 0:
                        for h in alineadas:
                            if h.id not in ids_antes:
                                filas_detalle.append({
                                    "Fecha": fecha_str,
                                    "Máquina": unidad["nombre"],
                                    "Cuartel": geo["nombre"],
                                    "Hilera": h.id,
                                    "Máx. pasadas (acumulado)": contar_pasadas_max(h.intervalos),
                                })
                        filas_resumen.append({
                            "Fecha": fecha_str,
                            "Máquina": unidad["nombre"],
                            "Cuartel": geo["nombre"],
                            "N° hileras conocidas": len(alineadas),
                            "Área acumulada trabajada (ha)": round(area_acreditada_ha, 2),
                            "Área real del cuartel (ha)": round(geo["area_ha"], 2),
                            "Hectáreas trabajadas del cuartel": round(area_trabajada_ha, 2),
                        })
                    else:
                        print(
                            f"  [sin avance nuevo] {fecha_str} - {unidad['nombre']} - {geo['nombre']}: "
                            f"{len(puntos_geo)} puntos, {len(hileras)} hileras conocidas, "
                            f"avance del cuartel {fraccion_trabajada(geo, celdas_despues) * 100:.1f}%"
                        )

                estado[(unidad["id"], geo["nombre"])] = [referencia, hileras, area_acreditada_ha]
                guardar_estado(unidad["id"], geo["nombre"], referencia, hileras, area_acreditada_ha)

        dia += timedelta(days=1)

    # Incluye tambien los cuarteles trabajados antes de este periodo (memoria),
    # para que sigan apareciendo en los mapas y en la geometria de la web.
    resultado_por_unidad = []
    for unidad in UNIDADES:
        hileras_por_geocerca = {}
        for geo in geocercas:
            referencia, hileras, area_acreditada_ha = estado_de(unidad, geo)
            if referencia is not None and hileras:
                hileras_por_geocerca[geo["nombre"]] = (referencia, hileras, area_acreditada_ha)
        resultado_por_unidad.append((unidad["nombre"], hileras_por_geocerca, descartados[unidad["id"]]))

    return pd.DataFrame(filas_resumen), pd.DataFrame(filas_detalle), resultado_por_unidad, diagnostico


def main():
    print("Conectando con Wialon...")
    sid = wialon_login(TOKEN)
    print("Conectado.")

    print("Descargando geocercas (cuarteles reales)...")
    geocercas = obtener_geocercas(sid)
    print(f"Se encontraron {len(geocercas)} geocercas de tipo poligono que califican como cuartel.")
    for geo in geocercas:
        print(f"  - {geo['nombre']}: {geo['area_ha']:.2f} ha, {len(geo['contorno'])} puntos de contorno")
    if not geocercas:
        print("ADVERTENCIA: no hay geocercas creadas en Wialon todavia (o ninguna calza con "
              "'cuarteles_incluidos' en config.json). Revisa el nombre exacto.")

    print(f"Procesando del {FECHA_INICIO.date()} al {FECHA_FIN.date()}...")
    df_resumen, df_detalle, resultado_por_unidad, diagnostico = generar_reporte(sid, geocercas)

    print("\nDiagnostico: puntos GPS (de cualquier maquina, sumados) encontrados dentro de cada geocerca:")
    for nombre, cantidad in diagnostico.items():
        print(f"  - {nombre}: {cantidad} puntos")
    print()

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

    ruta_kml = os.path.join(CARPETA_DATOS, "hileras_detectadas.kml")
    avance_total = avance_total_por_geocerca(resultado_por_unidad, geocercas)
    print("\nAvance por cuartel (todas las maquinas, sin contar dos veces lo repetido):")
    for nombre_geo, info in sorted(avance_total.items()):
        print(f"  - {nombre_geo}: {info['trabajado_ha']:.2f} de {info['area_total_ha']:.2f} ha"
              f" ({info['porcentaje']:.1f}%){' -> COMPLETO' if info['completo'] else ''}")
    with open(RUTA_AVANCE_CUARTELES, "w", encoding="utf-8") as f:
        json.dump({"umbral_cierre": UMBRAL_CIERRE_PORCENTAJE, "cuarteles": avance_total},
                  f, ensure_ascii=False, indent=2)

    exportar_kml(ruta_kml, resultado_por_unidad, geocercas, avance_total)
    print(f"Mapa de revision generado en: {ruta_kml}")

    carpeta_kml_por_unidad = os.path.join(CARPETA_DATOS, "kml")
    os.makedirs(carpeta_kml_por_unidad, exist_ok=True)
    for nombre_unidad, hileras_por_geocerca, descartados in resultado_por_unidad:
        if not hileras_por_geocerca:
            continue
        ruta_kml_unidad = os.path.join(carpeta_kml_por_unidad, f"{slug(nombre_unidad)}.kml")
        exportar_kml(ruta_kml_unidad, [(nombre_unidad, hileras_por_geocerca, descartados)], geocercas, avance_total)
    print(f"Mapas por maquina generados en: {carpeta_kml_por_unidad}")
    print("Abrelo con Google Earth o subelo a Google My Maps para comparar contra la foto satelital.")

    carpeta_geometria = os.path.join(CARPETA_DATOS, "geometria")
    os.makedirs(carpeta_geometria, exist_ok=True)
    geocercas_por_nombre = {g["nombre"]: g for g in geocercas}
    for nombre_unidad, hileras_por_geocerca, _ in resultado_por_unidad:
        if not hileras_por_geocerca:
            continue
        cuarteles_json = {}
        for nombre_geo, (referencia, hileras, area_acumulada_ha) in hileras_por_geocerca.items():
            if referencia is None:
                continue
            geo = geocercas_por_nombre.get(nombre_geo)
            completo = avance_total.get(nombre_geo, {}).get("completo", False)
            _, cruzadas = filtrar_hileras_regulares(hileras)
            ids_cruzadas = {h.id for h in cruzadas}

            contorno_m = [punto_a_metros(p, referencia) for p in geo["contorno"]] if geo else []
            filas = []
            for h in hileras:
                p1_m = (h.origen[0] + h.direccion[0] * h.min_proy, h.origen[1] + h.direccion[1] * h.min_proy)
                p2_m = (h.origen[0] + h.direccion[0] * h.max_proy, h.origen[1] + h.direccion[1] * h.max_proy)
                if math.hypot(p2_m[0] - p1_m[0], p2_m[1] - p1_m[1]) < 1.0:
                    continue
                lon1, lat1 = metros_a_punto(p1_m, referencia)
                lon2, lat2 = metros_a_punto(p2_m, referencia)
                if not all(math.isfinite(v) for v in (lon1, lat1, lon2, lat2)):
                    continue
                filas.append({
                    "id": h.id, "p1": [lon1, lat1], "p2": [lon2, lat2],
                    "fechas": sorted(h.fechas),
                    "completa": bool(contorno_m) and hilera_llega_a_los_bordes(h, contorno_m),
                    "cuenta": h.id not in ids_cruzadas,
                })
            if filas:
                cuarteles_json[nombre_geo] = {
                    "completo": completo,
                    "contorno": geo["contorno"] if geo else [],
                    "hileras": filas,
                }
        if cuarteles_json:
            ruta_geo = os.path.join(carpeta_geometria, f"{slug(nombre_unidad)}.json")
            with open(ruta_geo, "w", encoding="utf-8") as f:
                json.dump(cuarteles_json, f, ensure_ascii=False)
    print(f"Geometria para filtrar por fecha generada en: {carpeta_geometria}")


if __name__ == "__main__":
    main()
