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

import hashlib
import json
import math
import os
import re
import statistics
import unicodedata
from datetime import datetime, timedelta, timezone

import numpy as np
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
# Estado del avance por geocerca + labor (maximo alcanzado, pasadas de barrido).
RUTA_ESTADO_AVANCE = os.path.join(CARPETA_MEMORIA, "_avance_por_labor.json")
# Geocercas ya conocidas (por id de Wialon): las nuevas se calculan con los
# ultimos DIAS_GEOCERCA_NUEVA dias.
RUTA_GEOCERCAS_CONOCIDAS = os.path.join(CARPETA_MEMORIA, "_geocercas_conocidas.json")
# Panel de la web: maquinas en el patio y trabajo fuera de geocercas.
RUTA_ESTADO_MAQUINAS = os.path.join(CARPETA_DATOS, "estado_maquinas.json")

with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

WIALON_HOST = CONFIG.get("host", "https://hst-api.wialon.com")

# En la nube (GitHub Actions), el token viene del secreto WIALON_TOKEN, no
# del archivo config.json (que no debe llevar el token cuando se sube a
# GitHub). Localmente, sigue funcionando igual que siempre con config.json.
MODO_NUBE = bool(os.environ.get("WIALON_TOKEN"))
TOKEN = os.environ.get("WIALON_TOKEN") or CONFIG["token"]

# Lista de {"id", "nombre", "labor"}. La labor se edita en config.json. Las
# maquinas con labor "No incluir" no se procesan.
LABOR_NO_INCLUIR = "No incluir"
LABOR_CON_PASADAS = CONFIG.get("labor_con_pasadas", "Barrido")
UNIDADES = [u for u in CONFIG["unidades"] if u.get("labor") != LABOR_NO_INCLUIR]
LABOR_POR_MAQUINA = {u["nombre"]: u.get("labor") or "Sin labor" for u in UNIDADES}


def labor_de(unidad):
    return unidad.get("labor") or "Sin labor"

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
# Geocercas que no son cuarteles (patios, agregados "Completo"/"Total"): por
# nombre exacto o por patron (expresion regular, sin distinguir mayusculas).
GEOCERCAS_EXCLUIDAS = {n.strip().lower() for n in CONFIG.get("geocercas_excluidas", [])}
PATRONES_GEOCERCAS_EXCLUIDAS = [re.compile(p, re.IGNORECASE) for p in CONFIG.get("patrones_geocercas_excluidas", [])]
UMBRAL_CIERRE_PORCENTAJE = CONFIG.get("umbral_cierre_porcentaje", 0.95)
# Pasadas a menos de esta distancia lateral se consideran la misma hilera
# fisica (el GPS a veces parte una hilera en varias lineas paralelas).
TOLERANCIA_MISMA_HILERA_M = CONFIG.get("tolerancia_misma_hilera_m", 1.5)
# Grilla para medir la cobertura, y espaciado a usar cuando no se puede medir.
TAMANO_CELDA_M = CONFIG.get("tamano_celda_m", 1.0)
# En geocercas muy grandes la celda se agranda para no pasar de este numero
# de celdas (memoria y tiempo acotados).
MAXIMO_CELDAS_GRILLA = CONFIG.get("maximo_celdas_grilla", 400000)
MAXIMO_HILERAS_KML_GENERAL = CONFIG.get("maximo_hileras_kml_general", 150000)
# Modo diagnostico: solo lee de Wialon (geocercas y disponibilidad de datos
# GPS) e imprime un resumen; no calcula ni guarda nada.
MODO_DIAGNOSTICO = os.environ.get("MODO_DIAGNOSTICO", "").strip().lower() in ("1", "true", "si")
ESPACIADO_HILERAS_DEFECTO_M = CONFIG.get("espaciado_hileras_defecto_m", 4.0)
# Ancho que se asume para cada hilera: el espaciado medido, acotado a este
# rango (nunca mas de 5 m). Con menos de MINIMO_HILERAS_ESPACIADO hileras se
# usa el valor por defecto.
ESPACIADO_MINIMO_M = CONFIG.get("espaciado_minimo_m", 2.5)
ESPACIADO_MAXIMO_M = CONFIG.get("espaciado_maximo_m", 5.0)
MINIMO_HILERAS_ESPACIADO = CONFIG.get("minimo_hileras_espaciado", 10)
# Una pasada cuenta si tiene al menos MINIMO_PARALELAS_SERIE pasadas paralelas
# de la misma maquina a menos de DISTANCIA_MAXIMA_SERIE_M (trabajo en serie,
# aunque se salte hileras). Las pasadas aisladas (traslados por el borde o por
# el medio) no cuentan.
MINIMO_PARALELAS_SERIE = CONFIG.get("minimo_paralelas_serie", 2)
# Franja junto al limite de la geocerca (cabeceras, bordes que no se
# alcanzan a marcar): cuenta como trabajada hasta esta distancia del limite,
# solo donde el trabajo cubierto llega hasta ella.
FRANJA_BORDE_M = CONFIG.get("franja_borde_m", 8)
# Patio donde se guardan las maquinas (no es cuartel; se usa para el panel).
GEOCERCA_PATIO = CONFIG.get("geocerca_patio", "C&H Maquinaria")
# Trabajo fuera de geocercas: una zona cuenta como trabajo si tiene al menos
# MINIMO_PASADAS_TRABAJO pasadas que cuentan (rectas, paralelas, a velocidad
# de trabajo; las mismas reglas de las hileras). Las alertas se guardan
# DIAS_ALERTAS dias.
MINIMO_PASADAS_TRABAJO = CONFIG.get("minimo_pasadas_trabajo", 6)
DISTANCIA_ZONA_TRABAJO_M = CONFIG.get("distancia_zona_trabajo_m", 150)
PAUSA_GIRO_CABECERA_S = CONFIG.get("pausa_giro_cabecera_min", 5) * 60
DIAS_ALERTAS = CONFIG.get("dias_alertas", 30)
# Filtros del panel (se aplican al mostrar; las alertas se guardan completas):
#   - horas minimas de trabajo por dia en esa zona;
#   - que parezca un campo y no un camino de acceso: al menos
#     MINIMO_LINEAS_TRABAJO lineas distintas (a mas de 1,5 m entre si) que
#     cubran al menos ANCHO_MINIMO_TRABAJO_M de ancho.
HORAS_MINIMAS_ALERTA = CONFIG.get("horas_minimas_alerta", 1.0)
MINIMO_LINEAS_TRABAJO = CONFIG.get("minimo_lineas_trabajo", 4)
ANCHO_MINIMO_TRABAJO_M = CONFIG.get("ancho_minimo_trabajo_m", 12)
# Una misma maquina en el mismo lugar (a menos de esta distancia) en dias
# distintos es una sola linea del panel.
DISTANCIA_MISMO_LUGAR_M = CONFIG.get("distancia_mismo_lugar_m", 600)
DIAS_GEOCERCA_NUEVA = CONFIG.get("dias_geocerca_nueva", 30)
# Barrido: los dias se cuentan en hora de Chile.
try:
    from zoneinfo import ZoneInfo
    ZONA_HORARIA = ZoneInfo(CONFIG.get("zona_horaria", "America/Santiago"))
except Exception:
    ZONA_HORARIA = timezone(timedelta(hours=-4))
# Barrido: despues de completar una pasada, lo barrido ese mismo dia cuenta
# como pasada nueva (repaso) solo si por si solo cubre al menos esta fraccion
# del cuartel; si no, es terminar la pasada (el 5 % restante).
FRACCION_REPASO_MISMO_DIA = CONFIG.get("fraccion_repaso_mismo_dia", 0.5)


def dia_local(hora_unix):
    return datetime.fromtimestamp(hora_unix, ZONA_HORARIA).date()
DISTANCIA_MAXIMA_SERIE_M = CONFIG.get("distancia_maxima_serie_m", 40)

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


def geocerca_excluida(nombre):
    return (nombre.strip().lower() in GEOCERCAS_EXCLUIDAS
            or any(p.search(nombre) for p in PATRONES_GEOCERCAS_EXCLUIDAS))


def obtener_geocercas(sid, filtrar=True):
    """
    Devuelve una lista de cuarteles reales (geocercas de tipo poligono),
    con su nombre, su contorno (lon, lat), su area real en hectareas
    (calculada por nosotros mismos a partir del contorno, en metros) y su
    rectangulo envolvente (bbox). Con filtrar=False no aplica
    cuarteles_incluidos.
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
            if filtrar and CUARTELES_INCLUIDOS and nombre.strip().lower() not in CUARTELES_INCLUIDOS:
                continue  # no esta en la lista de cuarteles reales de config.json
            if filtrar and geocerca_excluida(nombre):
                continue  # patio o agregado: se usa siempre el cuartel mas detallado
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
                "id_wialon": f"{resource_id}-{zona.get('id')}",
                "nombre": zona.get("n", f"Geocerca {zona.get('id')}"),
                "contorno": contorno,
                "area_ha": area_m2 / 10000,
                "bbox": (min(p[0] for p in contorno), min(p[1] for p in contorno),
                         max(p[0] for p in contorno), max(p[1] for p in contorno)),
                "vertices": len(contorno),
            })

    # El nombre identifica al cuartel (memoria, reportes): los nombres
    # repetidos en Wialon se distinguen agregando su id.
    cuenta_nombres = {}
    for geo in geocercas:
        clave = geo["nombre"].strip().lower()
        cuenta_nombres[clave] = cuenta_nombres.get(clave, 0) + 1
    for geo in geocercas:
        if cuenta_nombres[geo["nombre"].strip().lower()] > 1:
            geo["nombre"] = f"{geo['nombre']} (id {geo['id_wialon']})"
    return geocercas


GRADOS_CUBETA_INDICE = 0.005  # ~500 m


def indice_geocercas(geocercas):
    """Indice espacial simple: cubeta (lon, lat) -> geocercas cuyo bbox la
    toca. Evita comparar cada punto GPS contra todas las geocercas."""
    indice = {}
    for geo in geocercas:
        x1, y1, x2, y2 = geo["bbox"]
        for i in range(int(math.floor(x1 / GRADOS_CUBETA_INDICE)), int(math.floor(x2 / GRADOS_CUBETA_INDICE)) + 1):
            for j in range(int(math.floor(y1 / GRADOS_CUBETA_INDICE)), int(math.floor(y2 / GRADOS_CUBETA_INDICE)) + 1):
                indice.setdefault((i, j), []).append(geo)
    return indice


def repartir_puntos_por_geocerca(puntos, indice):
    """Devuelve {nombre_geocerca: [puntos dentro]} usando el indice espacial."""
    por_geocerca = {}
    for p in puntos:
        lon, lat = p["punto"]
        clave = (int(math.floor(lon / GRADOS_CUBETA_INDICE)), int(math.floor(lat / GRADOS_CUBETA_INDICE)))
        for geo in indice.get(clave, ()):
            x1, y1, x2, y2 = geo["bbox"]
            if x1 <= lon <= x2 and y1 <= lat <= y2 and punto_en_poligono(p["punto"], geo["contorno"]):
                por_geocerca.setdefault(geo["nombre"], []).append(p)
    return por_geocerca


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


def procesar_puntos(puntos, referencia, hileras, descartados, fecha_str, tramos_aceptados=None):
    """Asigna los tramos del dia a hileras. Si se pasa `tramos_aceptados`, le
    agrega (hora, punto_inicio, punto_fin) de cada tramo que quedo en una
    hilera (se usa para contar las pasadas de barrido)."""
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
        if tramos_aceptados is not None:
            tramos_aceptados.append((seg[0].get("t") or 0, seg[0]["punto"], seg[-1]["punto"]))

    return list(hileras_tocadas_hoy)


# ---------------------------------------------------------------------------
# Paso 6: cobertura del dia y conteo de pasadas
# ---------------------------------------------------------------------------

def detectar_trabajo_fuera(unidad, fecha_str, puntos, dentro_ids):
    """
    Zonas donde la maquina trabajo ese dia fuera de toda geocerca (y fuera
    del patio). `dentro_ids`: ids de los puntos que caen en alguna geocerca
    o en el patio. Se usa el mismo criterio de las hileras: tramos rectos a
    velocidad de trabajo, alineados y en serie (al menos 2 paralelas a menos
    de 40 m); ir y volver por un camino no cuenta. Devuelve una lista de
    alertas (dicts).
    """
    if len(puntos) < 3:
        return []
    referencia = puntos[0]["punto"]
    candidatos = []  # (segmento, hilera en metros)
    for seg in segmentar_pasadas(puntos):
        if sum(1 for p in seg if id(p) not in dentro_ids) < 0.8 * len(seg):
            continue
        seg_m = [punto_a_metros(p["punto"], referencia) for p in seg]
        if velocidad_kmh_segmento(seg, seg_m) > VELOCIDAD_MAXIMA_TRABAJO_KMH:
            continue
        (x0, y0), (x1, y1) = seg_m[0], seg_m[-1]
        largo = math.hypot(x1 - x0, y1 - y0)
        if largo < LARGO_MINIMO_TRAMO_M:
            continue
        candidatos.append((seg, Hilera(len(candidatos), (x0, y0), ((x1 - x0) / largo, (y1 - y0) / largo), 0, largo)))
    if len(candidatos) < MINIMO_PASADAS_TRABAJO:
        return []

    # Zonas: tramos cuyos puntos medios estan a menos de DISTANCIA_ZONA_TRABAJO_M.
    medios = np.array([(h.origen[0] + h.direccion[0] * h.max_proy / 2, h.origen[1] + h.direccion[1] * h.max_proy / 2)
                       for _, h in candidatos])
    zona = list(range(len(candidatos)))
    def raiz(i):
        while zona[i] != i:
            zona[i] = zona[zona[i]]
            i = zona[i]
        return i
    for i in range(len(candidatos)):
        cerca = np.nonzero(np.hypot(*(medios[i + 1:] - medios[i]).T) <= DISTANCIA_ZONA_TRABAJO_M)[0] + i + 1
        for j in cerca:
            zona[raiz(j)] = raiz(i)
    zonas = {}
    for i in range(len(candidatos)):
        zonas.setdefault(raiz(i), []).append(candidatos[i])

    alertas = []
    for miembros in zonas.values():
        cuentan, _ = filtrar_hileras_regulares([h for _, h in miembros])
        if len(cuentan) < MINIMO_PASADAS_TRABAJO:
            continue
        ids = {h.id for h in cuentan}
        segs = sorted((seg for seg, h in miembros if h.id in ids), key=lambda sg: sg[0]["t"] or 0)
        segundos, fin_anterior = 0.0, None
        for seg in segs:
            t0, t1 = seg[0]["t"] or 0, seg[-1]["t"] or 0
            segundos += max(0, t1 - t0)
            if fin_anterior is not None and 0 < t0 - fin_anterior <= PAUSA_GIRO_CABECERA_S:
                segundos += t0 - fin_anterior  # giro en cabecera
            fin_anterior = t1
        largo_total = sum(h.largo_conocido for h in cuentan)
        # Lineas distintas recorridas y ancho que cubren (un camino de acceso,
        # aunque se recorra lento o varias veces, son 1 o 2 lineas y pocos metros).
        ref = hilera_referencia(cuentan)
        laterales = sorted(
            ((h.origen[0] + h.direccion[0] * h.max_proy / 2) - ref.origen[0]) * -ref.direccion[1]
            + ((h.origen[1] + h.direccion[1] * h.max_proy / 2) - ref.origen[1]) * ref.direccion[0]
            for h in cuentan)
        lineas = 1 + sum(1 for a, b in zip(laterales, laterales[1:]) if b - a >= TOLERANCIA_MISMA_HILERA_M)
        puntos_zona = [p["punto"] for seg in segs for p in seg]
        lon = sum(p[0] for p in puntos_zona) / len(puntos_zona)
        lat = sum(p[1] for p in puntos_zona) / len(puntos_zona)
        muestras = [seg[len(seg) // 2]["punto"] for seg in segs]
        paso = max(1, len(muestras) // 40)
        alertas.append({
            "fecha": fecha_str,
            "maquina": unidad["nombre"],
            "labor": labor_de(unidad),
            "horas": round(segundos / 3600, 2),
            "pasadas": len(cuentan),
            "lineas": lineas,
            "ancho_m": round(laterales[-1] - laterales[0], 1),
            "km_h": round(sum(h.largo_conocido for h in cuentan) / 1000
                          / max(1e-6, sum(max(1, (sg[-1]["t"] or 0) - (sg[0]["t"] or 0)) for sg in segs) / 3600), 1),
            "ha_aprox": round(largo_total * espaciado_real_m(cuentan) / 10000, 2),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "mapa": f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
            "muestras": [[round(x, 6), round(y, 6)] for x, y in muestras[::paso]],
        })
    return alertas


def alerta_resuelta(alerta, geocercas):
    """True si la mayoria de las pasadas de la alerta caen dentro de alguna
    geocerca (por ejemplo, una creada despues)."""
    for geo in geocercas:
        x1, y1, x2, y2 = geo["bbox"]
        dentro = sum(1 for lon, lat in alerta["muestras"]
                     if x1 <= lon <= x2 and y1 <= lat <= y2 and punto_en_poligono((lon, lat), geo["contorno"]))
        if dentro >= 0.5 * len(alerta["muestras"]):
            return True
    return False


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
    if len(hileras) == 1:
        return hileras[0]
    # Angulo de cada hilera (0-180) y metros de hileras dentro de +-tolerancia,
    # con sumas acumuladas sobre los angulos ordenados (circular en 180).
    angulos = np.array([math.degrees(math.atan2(h.direccion[1], h.direccion[0])) % 180.0 for h in hileras])
    largos = np.array([h.largo_conocido for h in hileras])
    orden = np.argsort(angulos)
    ang_ext = np.concatenate([angulos[orden] - 180.0, angulos[orden], angulos[orden] + 180.0])
    acumulado = np.concatenate([[0.0], np.cumsum(np.tile(largos[orden], 3))])
    izq = np.searchsorted(ang_ext, angulos - TOLERANCIA_ANGULO_GRADOS, side="left")
    der = np.searchsorted(ang_ext, angulos + TOLERANCIA_ANGULO_GRADOS, side="right")
    metros_alineados = acumulado[der] - acumulado[izq]
    mejor = max(range(len(hileras)), key=lambda i: (metros_alineados[i], largos[i]))
    return hileras[mejor]


def filtrar_hileras_regulares(hileras):
    """
    Devuelve (hileras que cuentan, tramos que no cuentan). No cuentan:
      - los tramos cruzados respecto de la direccion del cuartel (traslados
        en diagonal, vueltas de cabecera);
      - las pasadas aisladas: sin al menos MINIMO_PARALELAS_SERIE pasadas
        paralelas de la misma maquina a menos de DISTANCIA_MAXIMA_SERIE_M
        (ej. un traslado por el borde de la geocerca).
    """
    if len(hileras) < 2:
        return [], list(hileras)
    ref = hilera_referencia(hileras)
    alineadas, descartadas = [], []
    for h in hileras:
        (alineadas if angulo_entre_hileras(h, ref) <= TOLERANCIA_ANGULO_GRADOS else descartadas).append(h)
    if not alineadas:
        return [], descartadas

    # Posicion de cada pasada respecto de la direccion del cuartel: lateral
    # (centro) y tramo a lo largo. Se ordenan por posicion lateral y cada una
    # se compara solo con las cercanas.
    origen = np.array([h.origen for h in alineadas])
    direccion = np.array([h.direccion for h in alineadas])
    ini = origen + direccion * np.array([h.min_proy for h in alineadas])[:, None]
    fin = origen + direccion * np.array([h.max_proy for h in alineadas])[:, None]
    base = np.array(ref.origen)
    eje = np.array(ref.direccion)
    normal = np.array([-eje[1], eje[0]])
    lateral = (((ini + fin) / 2) - base) @ normal
    desde_a = np.minimum((ini - base) @ eje, (fin - base) @ eje)
    hasta_a = np.maximum((ini - base) @ eje, (fin - base) @ eje)
    orden = np.argsort(lateral)
    lat_o, desde_o, hasta_o = lateral[orden], desde_a[orden], hasta_a[orden]
    izq = np.searchsorted(lat_o, lat_o - DISTANCIA_MAXIMA_SERIE_M, side="left")
    der = np.searchsorted(lat_o, lat_o + DISTANCIA_MAXIMA_SERIE_M, side="right")
    cuenta_ordenada = np.zeros(len(alineadas), dtype=bool)
    for k in range(len(alineadas)):
        v = slice(izq[k], der[k])
        distancia = np.abs(lat_o[v] - lat_o[k])
        solape = np.minimum(hasta_o[v], hasta_o[k]) - np.maximum(desde_o[v], desde_o[k])
        paralelas = (distancia >= TOLERANCIA_MISMA_HILERA_M) & (solape > 0)
        cuenta_ordenada[k] = int(paralelas.sum()) >= MINIMO_PARALELAS_SERIE
    cuenta = np.zeros(len(alineadas), dtype=bool)
    cuenta[orden] = cuenta_ordenada
    cuentan = [h for h, c in zip(alineadas, cuenta) if c]
    descartadas += [h for h, c in zip(alineadas, cuenta) if not c]
    return cuentan, descartadas


def espaciado_real_m(hileras_alineadas):
    """
    Espaciado entre hileras fisicas vecinas (mediana). Antes se agrupan las
    pasadas a menos de TOLERANCIA_MISMA_HILERA_M, que son la misma hilera
    partida por el GPS; si no, el espaciado sale mucho menor que el real.
    """
    if len(hileras_alineadas) < MINIMO_HILERAS_ESPACIADO:
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
    medido = statistics.median(gaps) if gaps else ESPACIADO_HILERAS_DEFECTO_M
    return min(ESPACIADO_MAXIMO_M, max(ESPACIADO_MINIMO_M, medido))


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


def dentro_poligono_np(x, y, poligono):
    """Version vectorizada de punto_en_poligono para arreglos x, y."""
    dentro = np.zeros(x.shape, dtype=bool)
    n = len(poligono)
    j = n - 1
    for i in range(n):
        xi, yi = poligono[i]
        xj, yj = poligono[j]
        cruza = (yi > y) != (yj > y)
        x_interseccion = (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi
        dentro ^= cruza & (x < x_interseccion)
        j = i
    return dentro


def grilla_geocerca(geo):
    """
    Grilla de celdas cuadradas sobre la geocerca, en metros respecto del
    primer punto de su contorno. Devuelve un dict con: referencia, lado
    (m), i0/j0 (indice de la primera celda), mascara (celdas dentro de la
    geocerca) y n_celdas. La celda es de TAMANO_CELDA_M, o mas grande en
    geocercas enormes para no pasar de MAXIMO_CELDAS_GRILLA. Se calcula una
    vez por geocerca.
    """
    if geo["nombre"] not in _grillas:
        referencia = geo["contorno"][0]
        contorno_m = [punto_a_metros(p, referencia) for p in geo["contorno"]]
        xs = [p[0] for p in contorno_m]
        ys = [p[1] for p in contorno_m]
        area_bbox = (max(xs) - min(xs)) * (max(ys) - min(ys))
        lado = max(TAMANO_CELDA_M, math.sqrt(area_bbox / MAXIMO_CELDAS_GRILLA))
        i0, i1 = int(math.floor(min(xs) / lado)), int(math.ceil(max(xs) / lado))
        j0, j1 = int(math.floor(min(ys) / lado)), int(math.ceil(max(ys) / lado))
        ci = (np.arange(i0, i1 + 1) + 0.5) * lado
        cj = (np.arange(j0, j1 + 1) + 0.5) * lado
        cx, cy = np.meshgrid(ci, cj, indexing="ij")
        mascara = dentro_poligono_np(cx, cy, contorno_m)
        # Celdas a menos de FRANJA_BORDE_M del limite.
        distancia = np.full(cx.shape, np.inf)
        for k in range(len(contorno_m)):
            (ax, ay), (bx, by) = contorno_m[k], contorno_m[(k + 1) % len(contorno_m)]
            dx, dy = bx - ax, by - ay
            t = np.clip(((cx - ax) * dx + (cy - ay) * dy) / max(dx * dx + dy * dy, 1e-9), 0, 1)
            distancia = np.minimum(distancia, np.hypot(cx - ax - t * dx, cy - ay - t * dy))
        _grillas[geo["nombre"]] = {
            "referencia": referencia, "lado": lado, "i0": i0, "j0": j0,
            "mascara": mascara, "n_celdas": int(mascara.sum()),
            "franja_borde": mascara & (distancia <= FRANJA_BORDE_M),
        }
    return _grillas[geo["nombre"]]


def marcar_franja_hilera(hilera, referencia, geo, ancho_m, marcadas):
    """Marca (en el arreglo `marcadas`) las celdas de la franja de `ancho_m`
    alrededor de la hilera, alargada hasta el borde de la geocerca en los
    extremos que llegan a la cabecera (TOLERANCIA_CABECERA_M)."""
    grilla = grilla_geocerca(geo)
    lado = grilla["lado"]
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
        return punto_a_metros(metros_a_punto(punto, referencia), grilla["referencia"])

    a, b = a_grilla(ini), a_grilla(fin)
    largo = math.hypot(b[0] - a[0], b[1] - a[1])
    if largo < 0.5:
        return
    ux, uy = (b[0] - a[0]) / largo, (b[1] - a[1]) / largo
    paso = lado / 2
    t = np.linspace(0.0, largo, int(largo / paso) + 2)
    d = np.linspace(-ancho_m / 2, ancho_m / 2, int(ancho_m / paso) + 2)
    tt, dd = np.meshgrid(t, d, indexing="ij")
    ii = np.floor((a[0] + ux * tt - uy * dd) / lado).astype(np.int64) - grilla["i0"]
    jj = np.floor((a[1] + uy * tt + ux * dd) / lado).astype(np.int64) - grilla["j0"]
    validas = (ii >= 0) & (ii < marcadas.shape[0]) & (jj >= 0) & (jj < marcadas.shape[1])
    marcadas[ii[validas], jj[validas]] = True


def marcar_trabajo_maquina(geo, referencia, hileras):
    """Celdas marcadas por las hileras de UNA maquina (sin rellenar) y su
    espaciado entre hileras. Devuelve (arreglo, espaciado_m) o None."""
    if referencia is None or not hileras:
        return None
    grilla = grilla_geocerca(geo)
    alineadas, _ = filtrar_hileras_regulares(hileras)
    espaciado = espaciado_real_m(alineadas)
    marcadas = np.zeros(grilla["mascara"].shape, dtype=bool)
    for h in alineadas:
        marcar_franja_hilera(h, referencia, geo, espaciado, marcadas)
    return marcadas & grilla["mascara"], espaciado


def desplazados(arreglo, radio, relleno):
    """Genera el arreglo desplazado en cada offset de un disco de `radio`."""
    ancho, alto = arreglo.shape
    ampliado = np.pad(arreglo, radio, constant_values=relleno)
    for di in range(-radio, radio + 1):
        for dj in range(-radio, radio + 1):
            if di * di + dj * dj <= radio * radio:
                yield ampliado[radio + di:radio + di + ancho, radio + dj:radio + dj + alto]


def rellenar_franjas_angostas(marcadas, mascara, radio_celdas):
    """Cierre morfologico: rellena las franjas sin marcar de menos de
    2 x radio (entre hileras no del todo paralelas, o contra el borde). Un
    hueco mas ancho, como una hilera saltada entera, queda sin rellenar."""
    if radio_celdas < 1 or not marcadas.any():
        return marcadas & mascara
    dilatadas = np.zeros_like(marcadas)
    for vecino in desplazados(marcadas, radio_celdas, False):
        dilatadas |= vecino
    # Fuera de la geocerca cuenta como marcado, para que el borde no se "coma".
    base = dilatadas | ~mascara
    cerradas = np.ones_like(marcadas)
    for vecino in desplazados(base, radio_celdas, True):
        cerradas &= vecino
    return (cerradas & mascara) | (marcadas & mascara)


def unir_trabajos(geo, marcas):
    """Une las marcas de varias maquinas [(arreglo, espaciado)] y rellena
    las franjas angostas. Devuelve el arreglo de celdas trabajadas."""
    grilla = grilla_geocerca(geo)
    marcas = [m for m in marcas if m is not None]
    if not marcas:
        return np.zeros(grilla["mascara"].shape, dtype=bool)
    union = np.zeros(grilla["mascara"].shape, dtype=bool)
    for arreglo, _ in marcas:
        union |= arreglo
    radio = int(round(max(e for _, e in marcas) / 2 / grilla["lado"]))
    cerradas = rellenar_franjas_angostas(union, grilla["mascara"], radio)
    # La franja junto al limite cuenta donde el trabajo cubierto llega hasta ella.
    alcance = np.zeros_like(cerradas)
    for vecino in desplazados(cerradas, int(round(FRANJA_BORDE_M / grilla["lado"])), False):
        alcance |= vecino
    return cerradas | (alcance & grilla["franja_borde"])


def celdas_trabajadas(geo, trabajos):
    """Celdas trabajadas de una geocerca, uniendo todas las maquinas.
    trabajos: lista de (referencia, hileras) de cada maquina."""
    return unir_trabajos(geo, [marcar_trabajo_maquina(geo, ref, hs) for ref, hs in trabajos])


def fraccion_trabajada(geo, celdas_cubiertas):
    n_celdas = grilla_geocerca(geo)["n_celdas"]
    return int(celdas_cubiertas.sum()) / n_celdas if n_celdas else 0.0


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


def avance_total_por_geocerca(unidades_procesadas, geocercas, estado_avance):
    """
    Avance de cada geocerca POR LABOR. Dentro de una labor se unen las
    maquinas (lo repetido cuenta una vez); entre labores se cuenta aparte.
    El avance nunca baja: se usa el maximo alcanzado. En la labor de barrido
    se informan las pasadas completas y el % de la pasada en curso.
    Devuelve {nombre_geocerca: {"area_total_ha", "labores": {labor: {...}}}}.
    """
    trabajos = {}
    for nombre_maquina, hileras_por_geocerca, _ in unidades_procesadas:
        labor = LABOR_POR_MAQUINA.get(nombre_maquina, "Sin labor")
        for nombre_geo, (referencia, hileras, _) in hileras_por_geocerca.items():
            if referencia is not None and hileras:
                trabajos.setdefault((nombre_geo, labor), []).append((nombre_maquina, referencia, hileras))

    geos = {g["nombre"]: g for g in geocercas}
    avance = {}
    for (nombre_geo, labor), lista in sorted(trabajos.items()):
        geo = geos.get(nombre_geo)
        if geo is None:
            continue
        estado = estado_avance_de(estado_avance, nombre_geo, labor)
        info = {"maquinas": sorted({m for m, _, _ in lista})}
        if labor == LABOR_CON_PASADAS:
            info.update({
                "pasadas_completas": len(estado["pasadas"]),
                "porcentaje_en_curso": round(estado["fraccion_en_curso"] * 100, 1),
                "trabajado_ha": round(estado["fraccion_en_curso"] * geo["area_ha"], 4),
                "porcentaje": round(estado["fraccion_en_curso"] * 100, 1),
                "completo": len(estado["pasadas"]) > 0,
            })
        else:
            fraccion = max(estado["max_fraccion"], fraccion_trabajada(
                geo, celdas_trabajadas(geo, [(ref, hs) for _, ref, hs in lista])))
            estado["max_fraccion"] = fraccion
            info.update({
                "trabajado_ha": round(fraccion * geo["area_ha"], 4),
                "porcentaje": round(fraccion * 100, 1),
                "completo": fraccion >= UMBRAL_CIERRE_PORCENTAJE,
            })
        entrada = avance.setdefault(nombre_geo, {"area_total_ha": round(geo["area_ha"], 4), "labores": {}})
        entrada["labores"][labor] = info
    return avance


def labor_completa(avance_total, nombre_geo, labor):
    return avance_total.get(nombre_geo, {}).get("labores", {}).get(labor, {}).get("completo", False)


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
        labores = avance_total.get(geo["nombre"], {}).get("labores", {})
        completas = sorted(l for l, info in labores.items() if info.get("completo"))

        color_borde = NEGRO_GEOCERCA
        etiqueta = (f"COMPLETA: {', '.join(completas)}" if completas else f"{geo['area_ha']:.2f} ha")
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
            geocerca_completa = labor_completa(avance_total, nombre_geo, LABOR_POR_MAQUINA.get(nombre_unidad))
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

def ruta_memoria(unit_id, nombre_geocerca, labor):
    # La labor va en el nombre: si una maquina cambia de labor, lo ya hecho
    # queda en la labor anterior. El codigo corto evita que dos nombres
    # parecidos (ej. con y sin tilde) compartan el mismo archivo.
    codigo = hashlib.md5(nombre_geocerca.encode("utf-8")).hexdigest()[:6]
    return os.path.join(CARPETA_MEMORIA,
                        f"unidad_{unit_id}_{slug(labor)}_cuartel_{slug(nombre_geocerca)}_{codigo}.json")


def cargar_estado(unit_id, nombre_geocerca, labor):
    ruta = ruta_memoria(unit_id, nombre_geocerca, labor)
    if not os.path.exists(ruta):
        return None, [], 0.0
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    referencia = tuple(data["referencia"]) if data.get("referencia") else None
    hileras = [Hilera.from_dict(d) for d in data.get("hileras", [])]
    area_acumulada_ha = data.get("area_acumulada_ha", 0.0)
    return referencia, hileras, area_acumulada_ha


def guardar_estado(unit_id, nombre_geocerca, labor, referencia, hileras, area_acumulada_ha):
    ruta = ruta_memoria(unit_id, nombre_geocerca, labor)
    data = {
        "referencia": list(referencia) if referencia else None,
        "labor": labor,
        "hileras": [h.to_dict() for h in hileras],
        "area_acumulada_ha": area_acumulada_ha,
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cargar_estado_avance():
    if not os.path.exists(RUTA_ESTADO_AVANCE):
        return {}
    with open(RUTA_ESTADO_AVANCE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_estado_avance(estado):
    with open(RUTA_ESTADO_AVANCE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False)


def cargar_geocercas_conocidas():
    """{id_wialon: nombre} de las geocercas ya procesadas, o None la primera vez."""
    if not os.path.exists(RUTA_GEOCERCAS_CONOCIDAS):
        return None
    with open(RUTA_GEOCERCAS_CONOCIDAS, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_geocercas_conocidas(geocercas):
    with open(RUTA_GEOCERCAS_CONOCIDAS, "w", encoding="utf-8") as f:
        json.dump({g["id_wialon"]: g["nombre"] for g in geocercas}, f, ensure_ascii=False, indent=1)


def alerta_visible(alerta):
    """Filtros del panel: horas minimas y forma de campo (no camino)."""
    return (alerta["horas"] >= HORAS_MINIMAS_ALERTA
            and alerta.get("lineas", 99) >= MINIMO_LINEAS_TRABAJO
            and alerta.get("ancho_m", 999) >= ANCHO_MINIMO_TRABAJO_M)


def agrupar_alertas(alertas, fecha_panel):
    """Una linea por maquina y lugar: 'trabajando hace N dias sin geocerca',
    con N = dias desde la primera vez (dentro del plazo) que trabajo ahi."""
    grupos = []
    for a in sorted(alertas, key=lambda a: a["fecha"]):
        for g in grupos:
            if g["maquina"] == a["maquina"] and math.hypot(
                    (a["lat"] - g["lat"]) * METROS_POR_GRADO_LAT,
                    (a["lon"] - g["lon"]) * 111320.0 * math.cos(math.radians(a["lat"]))) <= DISTANCIA_MISMO_LUGAR_M:
                g["dias_trabajados"].add(a["fecha"])
                g["horas"] += a["horas"]
                g["ha_aprox"] += a["ha_aprox"]
                g["ultima_fecha"] = a["fecha"]
                break
        else:
            grupos.append({"maquina": a["maquina"], "labor": a["labor"], "lat": a["lat"], "lon": a["lon"],
                           "mapa": a["mapa"], "primera_fecha": a["fecha"], "ultima_fecha": a["fecha"],
                           "dias_trabajados": {a["fecha"]}, "horas": a["horas"], "ha_aprox": a["ha_aprox"]})
    panel = datetime.strptime(fecha_panel, "%Y-%m-%d").date()
    for g in grupos:
        g["hace_dias"] = (panel - datetime.strptime(g["primera_fecha"], "%Y-%m-%d").date()).days
        g["dias_trabajados"] = len(g["dias_trabajados"])
        g["horas"] = round(g["horas"], 1)
        g["ha_aprox"] = round(g["ha_aprox"], 1)
    return sorted(grupos, key=lambda g: (-g["hace_dias"], g["maquina"]))


def actualizar_estado_maquinas(extra, fecha_inicio, fecha_fin, geocercas, patio):
    """Panel de la web: maquinas en el patio el ultimo dia y trabajo fuera de
    geocercas de los ultimos DIAS_ALERTAS dias, una linea por maquina y
    lugar. Las alertas de los dias recien procesados se reemplazan; las que
    ya caen dentro de alguna geocerca (creada despues) se eliminan."""
    anteriores = []
    if os.path.exists(RUTA_ESTADO_MAQUINAS):
        with open(RUTA_ESTADO_MAQUINAS, "r", encoding="utf-8") as f:
            anteriores = json.load(f).get("alertas", [])
    desde, hasta = fecha_inicio.strftime("%Y-%m-%d"), fecha_fin.strftime("%Y-%m-%d")
    limite = (fecha_fin - timedelta(days=DIAS_ALERTAS - 1)).strftime("%Y-%m-%d")
    alertas = [a for a in anteriores if not (desde <= a["fecha"] <= hasta)] + extra["alertas"]
    referencia = geocercas + ([patio] if patio else [])
    alertas = [a for a in alertas if a["fecha"] >= limite and not alerta_resuelta(a, referencia)]
    alertas.sort(key=lambda a: (a["fecha"], a["maquina"]), reverse=True)
    estado = {
        "fecha": hasta,
        "patio": GEOCERCA_PATIO,
        "en_patio": sorted(extra["en_patio"]),
        "maquinas_con_datos": len(extra["con_datos"]),
        "sin_geocerca": agrupar_alertas([a for a in alertas if alerta_visible(a)], hasta),
        "alertas": alertas,
    }
    with open(RUTA_ESTADO_MAQUINAS, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    return estado


def clave_avance(nombre_geo, labor):
    return f"{nombre_geo}||{labor}"


def estado_avance_de(estado, nombre_geo, labor):
    return estado.setdefault(clave_avance(nombre_geo, labor), {
        "max_fraccion": 0.0, "pasadas": [], "tramos_ultima": [], "en_curso": [], "fraccion_en_curso": 0.0,
    })


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
    indice = {(r["fecha"], r["maquina"], r["cuartel"], r.get("labor")): i for i, r in enumerate(historico)}

    for _, fila in df_resumen.iterrows():
        registro = {
            "fecha": fila["Fecha"],
            "maquina": fila["Máquina"],
            "cuartel": str(fila["Cuartel"]),
            "labor": str(fila["Labor"]),
            "n_hileras": int(fila["N° hileras conocidas"]),
            "area_total_ha": float(fila["Área real del cuartel (ha)"]),
            "area_trabajada_ha": float(fila["Hectáreas trabajadas del cuartel"]),
        }
        clave = (registro["fecha"], registro["maquina"], registro["cuartel"], registro["labor"])
        if clave in indice:
            historico[indice[clave]] = registro
        else:
            historico.append(registro)
            indice[clave] = len(historico) - 1

    guardar_historico(historico)


# ---------------------------------------------------------------------------
# Orquestacion principal
# ---------------------------------------------------------------------------

def generar_reporte(sid, geocercas, estado_avance, fecha_inicio=None, fecha_fin=None,
                    geocercas_referencia=None, patio=None, detectar_fuera=True):
    """
    Procesa los dias en orden cronologico. El avance se calcula por geocerca
    y LABOR: dentro de una labor se unen las maquinas (lo repetido cuenta una
    vez) y las hectareas nuevas se acreditan a la maquina que las cubrio
    primero (cada dia, las maquinas se procesan en el orden en que entraron
    a la geocerca). El avance de cada geocerca + labor nunca baja. En la
    labor de barrido se cuentan pasadas completas (ver avanzar_pasadas).

    Ademas, si detectar_fuera: registra el trabajo fuera de toda geocerca de
    `geocercas_referencia` (y fuera del patio) de los ultimos DIAS_ALERTAS
    dias, y que maquinas terminan el ultimo dia en el patio.
    Devuelve (resumen, detalle, resultado_por_unidad, diagnostico, extra).
    """
    fecha_inicio = fecha_inicio or FECHA_INICIO
    fecha_fin = fecha_fin or FECHA_FIN
    if geocercas_referencia is None:
        geocercas_referencia = geocercas
    extra = {"alertas": [], "en_patio": [], "con_datos": []}
    filas_resumen = []
    filas_detalle = []
    diagnostico = {geo["nombre"]: 0 for geo in geocercas}  # puntos totales vistos por geocerca
    descartados = {u["id"]: [] for u in UNIDADES}
    estado = {}  # (unit_id, nombre_geo) -> [referencia, hileras, area_acreditada_ha]

    def estado_de(unidad, geo):
        clave = (unidad["id"], geo["nombre"])
        if clave not in estado:
            estado[clave] = list(cargar_estado(unidad["id"], geo["nombre"], labor_de(unidad)))
        return estado[clave]

    marcas = {}  # (unit_id, nombre_geo) -> marcas de esa maquina (se recalculan si trabaja)
    cobertura = {}  # (nombre_geo, labor) -> celdas trabajadas actuales de esa labor

    def cobertura_actual(geo, labor):
        clave_cobertura = (geo["nombre"], labor)
        if clave_cobertura not in cobertura:
            lista = []
            for u in UNIDADES:
                if labor_de(u) != labor:
                    continue
                clave = (u["id"], geo["nombre"])
                if clave not in marcas:
                    referencia, hileras, _ = estado_de(u, geo)
                    marcas[clave] = marcar_trabajo_maquina(geo, referencia, hileras)
                lista.append(marcas[clave])
            cobertura[clave_cobertura] = unir_trabajos(geo, lista)
        return cobertura[clave_cobertura]

    indice = indice_geocercas(geocercas)
    indice_referencia = indice if geocercas_referencia is geocercas else indice_geocercas(geocercas_referencia)
    # Solo trabajo reciente: en un recalculo del año no se detecta en dias viejos.
    desde_alertas = (datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                     - timedelta(days=DIAS_ALERTAS))
    dia = fecha_inicio
    while dia <= fecha_fin:
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
            por_geocerca = repartir_puntos_por_geocerca(puntos, indice)
            if detectar_fuera:
                if dia == fecha_fin:
                    extra["con_datos"].append(unidad["nombre"])
                    if patio and punto_en_poligono(puntos[-1]["punto"], patio["contorno"]):
                        extra["en_patio"].append(unidad["nombre"])
                if dia >= desde_alertas:
                    por_referencia = (por_geocerca if indice_referencia is indice
                                      else repartir_puntos_por_geocerca(puntos, indice_referencia))
                    dentro = {id(p) for lista in por_referencia.values() for p in lista}
                    if patio:
                        x1, y1, x2, y2 = patio["bbox"]
                        dentro |= {id(p) for p in puntos
                                   if x1 <= p["punto"][0] <= x2 and y1 <= p["punto"][1] <= y2
                                   and punto_en_poligono(p["punto"], patio["contorno"])}
                    extra["alertas"] += detectar_trabajo_fuera(unidad, fecha_str, puntos, dentro)
            for nombre_geo, puntos_geo in por_geocerca.items():
                diagnostico[nombre_geo] += len(puntos_geo)
                if len(puntos_geo) >= MINIMO_PUNTOS_EN_GEOCERCA:
                    hora_entrada = min((p["t"] for p in puntos_geo if p["t"] is not None), default=0)
                    entradas[nombre_geo].append((hora_entrada, unidad, puntos_geo))

        for geo in geocercas:
            barrido_hoy = []  # [(unidad, tramos, hileras, ids_antes, n_puntos)] de las barredoras

            def registrar(unidad, labor, hileras, ids_antes, n_puntos, area_trabajada_ha, resumen_avance):
                clave = (unidad["id"], geo["nombre"])
                estado[clave][2] += area_trabajada_ha
                alineadas, _ = filtrar_hileras_regulares(hileras)
                if round(area_trabajada_ha, 2) > 0:
                    for h in alineadas:
                        if h.id not in ids_antes:
                            filas_detalle.append({
                                "Fecha": fecha_str,
                                "Máquina": unidad["nombre"],
                                "Labor": labor,
                                "Cuartel": geo["nombre"],
                                "Hilera": h.id,
                                "Máx. pasadas (acumulado)": contar_pasadas_max(h.intervalos),
                            })
                    filas_resumen.append({
                        "Fecha": fecha_str,
                        "Máquina": unidad["nombre"],
                        "Labor": labor,
                        "Cuartel": geo["nombre"],
                        "N° hileras conocidas": len(alineadas),
                        "Área acumulada trabajada (ha)": round(estado[clave][2], 2),
                        "Área real del cuartel (ha)": round(geo["area_ha"], 2),
                        "Hectáreas trabajadas del cuartel": round(area_trabajada_ha, 2),
                    })
                else:
                    print(
                        f"  [sin avance nuevo] {fecha_str} - {unidad['nombre']} ({labor}) - {geo['nombre']}: "
                        f"{n_puntos} puntos, {len(hileras)} hileras conocidas, {resumen_avance}"
                    )
                guardar_estado(unidad["id"], geo["nombre"], labor, *estado[clave])

            for _, unidad, puntos_geo in sorted(entradas[geo["nombre"]], key=lambda e: e[0]):
                labor = labor_de(unidad)
                referencia, hileras, _ = estado_de(unidad, geo)
                if referencia is None:
                    referencia = puntos_geo[0]["punto"]
                    estado[(unidad["id"], geo["nombre"])][0] = referencia
                ids_antes = {h.id for h in hileras}
                tramos_hoy = []

                hileras_tocadas_hoy = procesar_puntos(
                    puntos_geo, referencia, hileras, descartados[unidad["id"]], fecha_str, tramos_hoy
                )
                if not hileras_tocadas_hoy:
                    guardar_estado(unidad["id"], geo["nombre"], labor, *estado[(unidad["id"], geo["nombre"])])
                    continue
                marcas.pop((unidad["id"], geo["nombre"]), None)
                cobertura.pop((geo["nombre"], labor), None)
                if labor == LABOR_CON_PASADAS:
                    # Se procesa al final, con todas las barredoras del dia juntas.
                    barrido_hoy.append((unidad, tramos_hoy, hileras, ids_antes, len(puntos_geo)))
                    continue
                # El avance nunca baja: solo se acredita lo que supera el maximo.
                avance = estado_avance_de(estado_avance, geo["nombre"], labor)
                fraccion = fraccion_trabajada(geo, cobertura_actual(geo, labor))
                area_trabajada_ha = max(0.0, fraccion - avance["max_fraccion"]) * geo["area_ha"]
                avance["max_fraccion"] = max(avance["max_fraccion"], fraccion)
                registrar(unidad, labor, hileras, ids_antes, len(puntos_geo), area_trabajada_ha,
                          f"avance {avance['max_fraccion'] * 100:.1f}%")

            if barrido_hoy:
                avance = estado_avance_de(estado_avance, geo["nombre"], LABOR_CON_PASADAS)
                todos = [t for _, tramos, _, _, _ in barrido_hoy for t in tramos]
                area_total_ha = avanzar_pasadas(geo, avance, todos)
                resumen = (f"{len(avance['pasadas'])} pasadas completas, "
                           f"en curso {avance['fraccion_en_curso'] * 100:.1f}%")
                # Las hectareas barridas del dia se reparten segun los metros barridos por cada una.
                def metros(tramos):
                    return sum(math.hypot(*punto_a_metros(t[2], t[1])) for t in tramos)
                total_metros = sum(metros(tr) for _, tr, _, _, _ in barrido_hoy) or 1.0
                for unidad, tramos, hileras, ids_antes, n_puntos in barrido_hoy:
                    registrar(unidad, LABOR_CON_PASADAS, hileras, ids_antes, n_puntos,
                              area_total_ha * metros(tramos) / total_metros, resumen)

        dia += timedelta(days=1)

    # Incluye tambien        dia += timedelta(days=1)

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

    return pd.DataFrame(filas_resumen), pd.DataFrame(filas_detalle), resultado_por_unidad, diagnostico, extra


def primer_mensaje(sid, unit_id, desde, hasta):
    """Hora (unix) del primer mensaje GPS de la unidad en el intervalo, o
    None. Solo lectura: pide un unico mensaje."""
    params = json.dumps({
        "itemId": unit_id,
        "timeFrom": int(desde.replace(tzinfo=timezone.utc).timestamp()),
        "timeTo": int(hasta.replace(tzinfo=timezone.utc).timestamp()),
        "flags": 0, "flagsMask": 0, "loadCount": 1,
    })
    r = requests.get(
        f"{WIALON_HOST}/wialon/ajax.html",
        params={"svc": "messages/load_interval", "params": params, "sid": sid},
        timeout=60,
    )
    mensajes = r.json().get("messages", []) if r.ok else []
    return mensajes[0].get("t") if mensajes else None


def diagnostico_wialon(sid):
    """Imprime todas las geocercas poligono y, por maquina, la primera
    fecha con datos GPS desde el 2026-01-01 (y si hay datos antes)."""
    geocercas = obtener_geocercas(sid, filtrar=False)
    print(f"DIAG geocercas poligono en Wialon: {len(geocercas)}")
    for g in sorted(geocercas, key=lambda g: g["nombre"].lower()):
        ancho = (g["bbox"][2] - g["bbox"][0]) * 111320.0 * math.cos(math.radians(g["bbox"][1]))
        alto = (g["bbox"][3] - g["bbox"][1]) * METROS_POR_GRADO_LAT
        print(f"DIAG geocerca | {g['nombre']} | {g['area_ha']:.2f} ha | {g['vertices']} vertices | "
              f"{ancho:.0f} x {alto:.0f} m")

    inicio = datetime(2026, 1, 1)
    ahora = datetime.utcnow()
    for unidad in UNIDADES:
        t = primer_mensaje(sid, unidad["id"], inicio, ahora)
        t_antes = primer_mensaje(sid, unidad["id"], datetime(2025, 12, 1), inicio)
        primera = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d") if t else "sin datos"
        print(f"DIAG unidad | {unidad['nombre']} | primer dato 2026: {primera} | "
              f"datos en dic-2025: {'si' if t_antes else 'no'}")


def obtener_unidades_wialon(sid):
    """Todas las unidades visibles en Wialon (solo lectura): [(id, nombre)]."""
    params = json.dumps({
        "spec": {"itemsType": "avl_unit", "propName": "sys_name", "propValueMask": "*", "sortType": "sys_name"},
        "force": 1, "flags": 1, "from": 0, "to": 0,
    })
    r = requests.get(f"{WIALON_HOST}/wialon/ajax.html",
                     params={"svc": "core/search_items", "params": params, "sid": sid}, timeout=60)
    return [(item["id"], item.get("nm", "")) for item in r.json().get("items", [])]


def tramos_a_hileras(geo, tramos):
    """Convierte tramos [(hora, (lon, lat) inicio, (lon, lat) fin)] en hileras
    en metros respecto del primer punto del contorno de la geocerca."""
    referencia = geo["contorno"][0]
    hileras = []
    for _, p_ini, p_fin in tramos:
        (x0, y0), (x1, y1) = punto_a_metros(p_ini, referencia), punto_a_metros(p_fin, referencia)
        largo = math.hypot(x1 - x0, y1 - y0)
        if largo >= LARGO_MINIMO_TRAMO_M:
            hileras.append(Hilera(0, (x0, y0), ((x1 - x0) / largo, (y1 - y0) / largo), 0, largo))
    return hileras


def celdas_de_tramos(geo, tramos):
    """Celdas cubiertas por los tramos, con las mismas reglas que el resto
    (tramos cruzados y pasadas aisladas no cuentan)."""
    return celdas_trabajadas(geo, [(geo["contorno"][0], tramos_a_hileras(geo, tramos))])


def fraccion_de_tramos(geo, tramos):
    return fraccion_trabajada(geo, celdas_de_tramos(geo, tramos)) if tramos else 0.0


def avanzar_pasadas(geo, estado, nuevos_tramos):
    """
    Pasadas completas de barrido (todas las barredoras juntas). `estado`:
    {"pasadas": [[inicio, fin], ...], "hora_cierre", "tramos_ultima": [...],
    "en_curso": [...], "fraccion_en_curso"}. Reglas:
      - Una pasada se cierra cuando entre todas las barredoras cubren el
        umbral de cierre (95 %) de la geocerca.
      - Lo que sigan barriendo ese mismo dia (hora de Chile) sigue siendo esa
        pasada (terminar el 5 % restante).
      - La pasada nueva empieza cuando vuelven otro dia.
      - Excepcion: si el mismo dia, ya cerrada la pasada, vuelven a barrer
        el cuartel (lo barrido despues del cierre cubre por si solo al menos
        FRACCION_REPASO_MISMO_DIA del cuartel), eso es una pasada nueva. Cuando la pasada en curso cubre el umbral de
    cierre (95 %) se cuenta como completa y la siguiente empieza desde cero.
    Devuelve las hectareas barridas nuevas (una pasada completa cuenta el
    area entera).
    """
    estado.setdefault("tramos_ultima", [])
    fraccion_antes = estado.get("fraccion_en_curso", 0.0)
    completadas = 0
    pendientes = sorted(nuevos_tramos, key=lambda t: t[0])
    while pendientes:
        if not estado["en_curso"] and estado["tramos_ultima"]:
            dia_cierre = dia_local(estado.get("hora_cierre") or estado["pasadas"][-1][1])
            mismo_dia = [t for t in pendientes if dia_local(t[0]) == dia_cierre]
            if mismo_dia:
                pendientes = pendientes[len(mismo_dia):]
                despues_cierre = estado.get("despues_cierre", []) + mismo_dia
                if fraccion_de_tramos(geo, despues_cierre) >= FRACCION_REPASO_MISMO_DIA:
                    # Repaso el mismo dia: lo barrido despues del cierre es una pasada nueva.
                    # Los tramos de despues del cierre estan al final de la pasada cerrada.
                    n_previos = len(estado.get("despues_cierre", []))
                    if n_previos:
                        estado["tramos_ultima"] = estado["tramos_ultima"][:-n_previos]
                    estado["despues_cierre"] = []
                    estado["en_curso"] = []
                    pendientes = despues_cierre + pendientes
                else:
                    # Terminar la pasada ya cerrada (el 5 % restante).
                    estado["tramos_ultima"] += mismo_dia
                    estado["despues_cierre"] = despues_cierre
                    estado["pasadas"][-1][1] = mismo_dia[-1][0]
                    if not pendientes:
                        break
            estado["despues_cierre"] = []
            if not pendientes:
                break
        en_curso = estado["en_curso"]
        if fraccion_de_tramos(geo, en_curso + pendientes) < UMBRAL_CIERRE_PORCENTAJE:
            estado["en_curso"] = en_curso + pendientes
            break
        # Busca el primer tramo con el que la pasada llega al umbral.
        bajo, alto = 1, len(pendientes)
        while bajo < alto:
            medio = (bajo + alto) // 2
            if fraccion_de_tramos(geo, en_curso + pendientes[:medio]) >= UMBRAL_CIERRE_PORCENTAJE:
                alto = medio
            else:
                bajo = medio + 1
        tramos_pasada = en_curso + pendientes[:bajo]
        estado["pasadas"].append([tramos_pasada[0][0], tramos_pasada[-1][0]])
        estado["hora_cierre"] = tramos_pasada[-1][0]
        estado["despues_cierre"] = []
        estado["tramos_ultima"] = tramos_pasada
        estado["en_curso"] = []
        pendientes = pendientes[bajo:]
        completadas += 1
    estado["fraccion_en_curso"] = fraccion_de_tramos(geo, estado["en_curso"])
    return max(0.0, completadas - fraccion_antes + estado["fraccion_en_curso"]) * geo["area_ha"]


def contar_pasadas_completas(geo, tramos):
    """Pasadas completas de una lista cronologica de tramos (para pruebas)."""
    estado = {"pasadas": [], "tramos_ultima": [], "en_curso": [], "fraccion_en_curso": 0.0}
    avanzar_pasadas(geo, estado, tramos)
    return [tuple(p) for p in estado["pasadas"]], estado["fraccion_en_curso"]


def prueba_pasadas(sid, nombre):
    """Cuenta las pasadas completas en el periodo (solo lectura). `nombre` es
    una maquina o una labor (ej. "Barrido": todas las barredoras juntas)."""
    unidades = [u for u in UNIDADES if u["nombre"] == nombre or u.get("labor") == nombre]
    desde = datetime.strptime(os.environ.get("PRUEBA_DESDE", "") or "2026-01-01", "%Y-%m-%d")
    hasta = datetime.strptime(os.environ.get("PRUEBA_HASTA", "") or
                              (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"), "%Y-%m-%d")
    print(f"DIAG prueba de pasadas: {len(unidades)} maquinas, {desde:%Y-%m-%d} a {hasta:%Y-%m-%d}")
    geocercas = obtener_geocercas(sid)
    indice = indice_geocercas(geocercas)
    por_geocerca = {}  # nombre_geo -> {unit_id: [puntos]}
    for unidad in unidades:
        dia = desde
        while dia <= hasta:
            mensajes = obtener_mensajes(sid, unidad["id"], dia)
            puntos = [{"punto": (m["pos"]["x"], m["pos"]["y"]), "t": m.get("t")} for m in mensajes if m.get("pos")]
            for nombre_geo, puntos_geo in repartir_puntos_por_geocerca(puntos, indice).items():
                if len(puntos_geo) >= MINIMO_PUNTOS_EN_GEOCERCA:
                    por_geocerca.setdefault(nombre_geo, {}).setdefault(unidad["id"], []).extend(puntos_geo)
            dia += timedelta(days=1)
    geos = {g["nombre"]: g for g in geocercas}
    volcado = {}  # tramos por geocerca, para probar reglas sin volver a descargar
    for nombre_geo, por_unidad in sorted(por_geocerca.items()):
        geo = geos[nombre_geo]
        referencia = geo["contorno"][0]
        segmentos = []
        for puntos_unidad in por_unidad.values():  # los tramos se segmentan por maquina
            for seg in segmentar_pasadas(sorted(puntos_unidad, key=lambda p: p["t"] or 0)):
                seg_m = [punto_a_metros(p["punto"], referencia) for p in seg]
                if velocidad_kmh_segmento(seg, seg_m) <= VELOCIDAD_MAXIMA_TRABAJO_KMH:
                    segmentos.append((seg[0]["t"] or 0, seg[0]["punto"], seg[-1]["punto"]))
        segmentos.sort(key=lambda s: s[0])
        puntos_geo = [p for pu in por_unidad.values() for p in pu]
        volcado[nombre_geo] = {"contorno": geo["contorno"], "area_ha": geo["area_ha"], "tramos": segmentos}
        estado = {"pasadas": [], "tramos_ultima": [], "en_curso": [], "fraccion_en_curso": 0.0}
        por_dia = {}
        for tramo in segmentos:
            por_dia.setdefault(dia_local(tramo[0]), []).append(tramo)
        for dia_tramos in sorted(por_dia):
            avanzar_pasadas(geo, estado, por_dia[dia_tramos])
        pasadas, en_curso = estado["pasadas"], estado["fraccion_en_curso"]
        fechas = lambda t: dia_local(t).isoformat()
        detalle = "; ".join(f"pasada {i + 1}: {fechas(a)} a {fechas(b)}" for i, (a, b) in enumerate(pasadas))
        dias = sorted({fechas(p["t"]) for p in puntos_geo if p["t"]})
        print(f"DIAG pasadas | {nombre_geo} | {geo['area_ha']:.2f} ha | maquinas: {len(por_unidad)} | dias con puntos: {len(dias)} "
              f"({dias[0]} a {dias[-1]}) | pasadas completas: {len(pasadas)} | en curso: {en_curso * 100:.0f}% | {detalle}")
    with open(os.environ.get("RUTA_TRAMOS_DIAGNOSTICO", "tramos_diagnostico.json"), "w", encoding="utf-8") as f:
        json.dump(volcado, f)


def prueba_estado_y_geocerca_nueva(sid):
    """
    Prueba (solo lectura; nada se guarda en el repositorio):
      - PRUEBA_ESTADO=1: panel de maquinas del dia FECHA_FIN.
      - PRUEBA_GEOCERCA_NUEVA=<nombre>: hace de cuenta que esa geocerca no
        existia: muestra el trabajo que habria salido como alerta, la calcula
        como geocerca nueva con los ultimos DIAS_GEOCERCA_NUEVA dias y verifica
        que esas alertas se resuelven.
    """
    import tempfile
    temporal = tempfile.mkdtemp()
    globals()["CARPETA_MEMORIA"] = temporal
    globals()["RUTA_ESTADO_AVANCE"] = os.path.join(temporal, "_avance_por_labor.json")
    geocercas = obtener_geocercas(sid)
    patio = next((g for g in obtener_geocercas(sid, filtrar=False)
                  if g["nombre"].strip().lower() == GEOCERCA_PATIO.strip().lower()), None)
    print(f"DIAG patio: {patio['nombre'] if patio else 'NO ENCONTRADO'}")
    nombre_nueva = os.environ.get("PRUEBA_GEOCERCA_NUEVA", "").strip()
    nueva = next((g for g in geocercas if g["nombre"] == nombre_nueva), None)
    fin = FECHA_FIN
    if nueva is None:
        _, _, _, _, extra = generar_reporte(sid, [], {}, FECHA_INICIO, fin, geocercas, patio)
        with open("alertas_diagnostico.json", "w", encoding="utf-8") as f:
            json.dump({"fecha": fin.strftime("%Y-%m-%d"), "en_patio": extra["en_patio"],
                       "con_datos": extra["con_datos"], "alertas": extra["alertas"]}, f, ensure_ascii=False)
    else:
        sin_nueva = [g for g in geocercas if g is not nueva]
        inicio = fin - timedelta(days=DIAS_GEOCERCA_NUEVA - 1)
        estado_avance = {}
        _, _, res, _, extra = generar_reporte(sid, [nueva], estado_avance, inicio, fin, sin_nueva, patio)
    print(f"DIAG estado {fin:%Y-%m-%d} | en patio ({len(extra['en_patio'])} de {len(extra['con_datos'])} con datos): "
          f"{', '.join(sorted(extra['en_patio']))}")
    for a in sorted(extra["alertas"], key=lambda a: (a["fecha"], a["maquina"])):
        dentro = nueva is not None and alerta_resuelta(a, [nueva])
        print(f"DIAG alerta | {a['fecha']} | {a['maquina']} | {a['labor']} | {a['horas']} h | {a['pasadas']} pasadas | "
              f"~{a['ha_aprox']} ha | {a['mapa']} | {'DENTRO DE ' + nombre_nueva if dentro else ''}")
    if nueva is not None:
        avance = avance_total_por_geocerca(res, [nueva], estado_avance)
        for labor, info in avance.get(nueva["nombre"], {}).get("labores", {}).items():
            print(f"DIAG geocerca nueva | {nueva['nombre']} | {labor} | {info.get('trabajado_ha', 0):.2f} ha | "
                  f"{info.get('porcentaje', 0)}% | pasadas {info.get('pasadas_completas', '-')} | maquinas {', '.join(info['maquinas'])}")
        quedan = [a for a in extra["alertas"] if alerta_resuelta(a, [nueva])]
        todas = geocercas + ([patio] if patio else [])
        print(f"DIAG resolucion | alertas dentro de {nueva['nombre']} antes de crearla: {len(quedan)} | "
              f"despues de crearla quedan: {sum(1 for a in quedan if not alerta_resuelta(a, todas))}")


def main():
    print("Conectando con Wialon...")
    sid = wialon_login(TOKEN)
    print("Conectado.")

    if MODO_DIAGNOSTICO:
        if os.environ.get("PRUEBA_ESTADO", "").strip() or os.environ.get("PRUEBA_GEOCERCA_NUEVA", "").strip():
            prueba_estado_y_geocerca_nueva(sid)
            return
        unidad_prueba = os.environ.get("PRUEBA_PASADAS_UNIDAD", "").strip()
        if unidad_prueba:
            prueba_pasadas(sid, unidad_prueba)
            return
        configuradas = {u["id"]: u for u in UNIDADES}
        for id_wialon, nombre in obtener_unidades_wialon(sid):
            u = configuradas.get(id_wialon)
            print(f"DIAG unidad wialon | {nombre} | id {id_wialon} | "
                  f"{'labor: ' + u.get('labor', 'SIN LABOR') if u else 'NO ESTA EN config.json'}")
        return

    print("Descargando geocercas (cuarteles reales)...")
    geocercas = obtener_geocercas(sid)
    print(f"Se encontraron {len(geocercas)} geocercas de tipo poligono que califican como cuartel.")
    for geo in geocercas:
        print(f"  - {geo['nombre']}: {geo['area_ha']:.2f} ha, {len(geo['contorno'])} puntos de contorno")
    if not geocercas:
        print("ADVERTENCIA: no hay geocercas creadas en Wialon todavia (o ninguna calza con "
              "'cuarteles_incluidos' en config.json). Revisa el nombre exacto.")

    patio = next((g for g in obtener_geocercas(sid, filtrar=False)
                  if g["nombre"].strip().lower() == GEOCERCA_PATIO.strip().lower()), None)

    # Geocercas nuevas (no estaban en la corrida anterior): se calculan solas
    # con los ultimos DIAS_GEOCERCA_NUEVA dias de todas las maquinas. La
    # primera vez se registran todas como conocidas, sin recalcular.
    conocidas = cargar_geocercas_conocidas()
    nuevas = [] if conocidas is None else [g for g in geocercas if g["id_wialon"] not in conocidas]
    existentes = [g for g in geocercas if g not in nuevas]

    print(f"Procesando del {FECHA_INICIO.date()} al {FECHA_FIN.date()}...")
    estado_avance = cargar_estado_avance()
    df_resumen, df_detalle, resultado_por_unidad, diagnostico, extra = generar_reporte(
        sid, existentes, estado_avance, FECHA_INICIO, FECHA_FIN, geocercas, patio)
    if nuevas:
        desde_nuevas = FECHA_FIN - timedelta(days=DIAS_GEOCERCA_NUEVA - 1)
        print(f"Geocercas nuevas ({len(nuevas)}): {', '.join(g['nombre'] for g in nuevas)}. "
              f"Se calculan del {desde_nuevas.date()} al {FECHA_FIN.date()}.")
        df_n, det_n, res_n, diag_n, _ = generar_reporte(
            sid, nuevas, estado_avance, desde_nuevas, FECHA_FIN, geocercas, None, detectar_fuera=False)
        df_resumen = pd.concat([df_resumen, df_n], ignore_index=True)
        df_detalle = pd.concat([df_detalle, det_n], ignore_index=True)
        diagnostico.update(diag_n)
        for (_, hpg, desc), (_, hpg_n, desc_n) in zip(resultado_por_unidad, res_n):
            hpg.update(hpg_n)
            desc.extend(desc_n)
    guardar_geocercas_conocidas(geocercas)

    estado_maquinas = actualizar_estado_maquinas(extra, FECHA_INICIO, FECHA_FIN, geocercas, patio)
    print(f"\nEstado de maquinas al {estado_maquinas['fecha']}: {len(estado_maquinas['en_patio'])} en "
          f"{GEOCERCA_PATIO}, {len(estado_maquinas['sin_geocerca'])} maquinas/lugares trabajando sin geocerca "
          f"(ultimos {DIAS_ALERTAS} dias).")

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
    avance_total = avance_total_por_geocerca(resultado_por_unidad, geocercas, estado_avance)
    guardar_estado_avance(estado_avance)
    print("\nAvance por cuartel y labor (dentro de cada labor, lo repetido cuenta una vez):")
    for nombre_geo, entrada in sorted(avance_total.items()):
        for labor, info in sorted(entrada["labores"].items()):
            if labor == LABOR_CON_PASADAS:
                detalle = f"{info['pasadas_completas']} pasadas completas, en curso {info['porcentaje_en_curso']:.1f}%"
            else:
                detalle = (f"{info['trabajado_ha']:.2f} de {entrada['area_total_ha']:.2f} ha "
                           f"({info['porcentaje']:.1f}%){' -> COMPLETO' if info['completo'] else ''}")
            print(f"  - {nombre_geo} – {labor}: {detalle}")
    with open(RUTA_AVANCE_CUARTELES, "w", encoding="utf-8") as f:
        json.dump({"umbral_cierre": UMBRAL_CIERRE_PORCENTAJE, "cuarteles": avance_total},
                  f, ensure_ascii=False, indent=2)

    # GitHub no acepta archivos de mas de 100 MB: si hay demasiadas hileras,
    # el mapa general lleva solo los contornos (cada maquina tiene el suyo).
    total_hileras = sum(len(h) for _, hpg, _ in resultado_por_unidad for _, h, _ in hpg.values())
    if total_hileras > MAXIMO_HILERAS_KML_GENERAL:
        print(f"Mapa general con solo contornos ({total_hileras} hileras, maximo {MAXIMO_HILERAS_KML_GENERAL}).")
        exportar_kml(ruta_kml, [], geocercas, avance_total)
    else:
        exportar_kml(ruta_kml, resultado_por_unidad, geocercas, avance_total)
    print(f"Mapa de revision generado en: {ruta_kml}")

    # Los KML por maquina ya no se guardan: la web los arma desde la geometria.
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
            labor = LABOR_POR_MAQUINA.get(nombre_unidad, "Sin labor")
            completo = labor_completa(avance_total, nombre_geo, labor)
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
                    "labor": labor,
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
