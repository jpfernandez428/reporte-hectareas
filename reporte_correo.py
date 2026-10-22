"""
reporte_correo.py

Reporte diario de la flota por correo (reglas en CLAUDE.md, "Reporte diario
por correo"). Arma un correo HTML y el mismo reporte en PDF con:
  - maquinas: lo que ya calcula el sistema, sin km: hectareas
    (historico.json), labores, geocercas y horas (flota.json, el tablero de
    la flota) y las alertas;
  - camionetas y camion (lista "vehiculos" de config.json, que NO entran al
    calculo de hectareas ni al tablero de la flota): km y lugares, sin horas.

Wialon es SOLO LECTURA: se descargan mensajes GPS y direcciones.

Modos (variable MODO_CORREO):
  vista_previa  arma el reporte en salida_correo/ sin enviar nada.
  prueba        arma el reporte y lo envia solo a CORREO_PRUEBA.
"""

import json
import math
import os
import re
import smtplib
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape

import requests

import reporte_hectareas as rh

ZONA = rh.ZONA_HORARIA
# Vehiculos con "activo": false quedan en config.json pero no salen en el correo.
VEHICULOS = [v for v in rh.CONFIG.get("vehiculos", []) if v.get("activo", True)]
CAMIONETAS = [v for v in VEHICULOS if v.get("tipo", "camioneta") != "camion"]
CAMIONES = [v for v in VEHICULOS if v.get("tipo") == "camion"]
CARPETA_SALIDA = os.path.join(rh.CARPETA_BASE, "salida_correo")
URL_PAGINA = rh.CONFIG.get("url_pagina", "https://jpfernandez428.github.io/reporte-hectareas/")
DIAS_RESUMEN = 7

# Limpieza del GPS para los km: puntos detenidos (el mismo minimo de
# movimiento de las hileras) y saltos (un punto al que se va y del que se
# vuelve, o un tramo, a una velocidad imposible para un vehiculo).
VELOCIDAD_MAXIMA_VEHICULO_KMH = rh.CONFIG.get("velocidad_maxima_vehiculo_kmh", 160)
# Lugares: una geocerca cuenta si estuvo adentro al menos MINUTOS_EN_GEOCERCA;
# fuera de geocercas, cada parada de al menos MINUTOS_PARADA_FUERA (comuna).
MINUTOS_PARADA_FUERA = rh.CONFIG.get("minutos_parada_fuera", 15)
MINUTOS_EN_GEOCERCA = rh.CONFIG.get("minutos_en_geocerca_vehiculo", 5)
KM_MINIMO_SE_MOVIO = 0.5
# Hectareas estimadas sin geocerca = horas x rendimiento real de la maquina
# (ha/h en sus cuarteles con geocerca, ultimos 30 dias); con menos de estas
# horas de referencia, el de su labor; sin referencia, el calculo del GPS.
HORAS_MINIMAS_RENDIMIENTO = rh.CONFIG.get("horas_minimas_rendimiento", 10)
DIAS_MINIMOS_RENDIMIENTO = rh.CONFIG.get("dias_minimos_rendimiento", 3)

# Envio diario (CLAUDE.md, "Reporte diario por correo").
HORA_ENVIO = rh.CONFIG.get("hora_envio_correo", "07:45")
HORA_PREPARAR = rh.CONFIG.get("hora_preparar_correo", "07:30")
HORA_AVISO_ATRASO = rh.CONFIG.get("hora_aviso_atraso_correo", "09:00")
RUTA_ESTADO_CORREO = os.path.join(rh.CARPETA_DATOS, "correo_enviado.json")
REPO = os.environ.get("GITHUB_REPOSITORY", "jpfernandez428/reporte-hectareas")
# Linea "Marcha blanca" arriba del correo mientras no se apruebe el recalculo.
MARCHA_BLANCA = rh.CONFIG.get("correo_marcha_blanca", True)

VERDE = "#2F6F3E"
VERDE_CLARO = "#EAF3EC"
GRIS_FILA = "#F6F8F7"
ROJO = "#B3261E"
ROJO_CLARO = "#FDECEA"
TEXTO = "#1F2421"
TEXTO_SUAVE = "#5F6B64"
FUENTE = "Arial, Helvetica, sans-serif"

# ---------------------------------------------------------------------------
# Wialon (solo lectura)
# ---------------------------------------------------------------------------

def login():
    r = requests.get(f"{rh.WIALON_HOST}/wialon/ajax.html",
                     params={"svc": "token/login", "params": json.dumps({"token": rh.TOKEN})}, timeout=30)
    data = r.json()
    if "eid" not in data:
        raise RuntimeError(f"Error al conectar con Wialon: {data.get('error')}")
    return data["eid"], data.get("user", {}).get("id")


def wialon(sid, svc, params, intentos=3):
    for k in range(intentos):
        try:
            r = requests.get(f"{rh.WIALON_HOST}/wialon/ajax.html",
                             params={"svc": svc, "params": json.dumps(params), "sid": sid}, timeout=120)
            data = r.json()
            if not (isinstance(data, dict) and data.get("error")):
                return data
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (k + 1))
    raise RuntimeError(f"Wialon no respondio a {svc}")


def mensajes_dia(sid, unit_id, dia):
    """Mensajes GPS de un dia en hora de Chile, con lo que trae el equipo."""
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA).timestamp()
    data = wialon(sid, "messages/load_interval", {"itemId": unit_id, "timeFrom": int(inicio),
                                                    "timeTo": int(inicio + 86400) - 1, "flags": 0,
                                                    "flagsMask": 0, "loadCount": 0xFFFFFFFF})
    return [m for m in data.get("messages", []) if m.get("pos") and m.get("t")]



def ultima_posicion(sid, unit_id, hasta_unix):
    """(lon, lat, fuente) del ultimo punto GPS hasta esa hora, para los que no
    se movieron. Si Wialon no entrega el historial hacia atras, la posicion
    actual de la unidad."""
    try:
        data = wialon(sid, "messages/load_interval", {"itemId": unit_id, "timeFrom": int(hasta_unix),
                                                      "timeTo": int(hasta_unix) - 60 * 86400, "flags": 0,
                                                      "flagsMask": 0, "loadCount": 1})
        ms = [m for m in data.get("messages", []) if m.get("pos") and m.get("t", 0) <= hasta_unix]
        if ms:
            return ms[0]["pos"]["x"], ms[0]["pos"]["y"], "historial"
    except RuntimeError:
        pass
    pos = wialon(sid, "core/search_item", {"id": unit_id, "flags": 0x1 | 0x400}).get("item", {}).get("pos") or {}
    return (pos["x"], pos["y"], "actual") if pos.get("x") is not None else None


def direccion(usuario, lon, lat, cache={}):
    """Comuna o localidad de un punto con el buscador de direcciones de Wialon."""
    clave = (round(lon, 3), round(lat, 3))
    if clave in cache:
        return cache[clave]
    texto = None
    try:
        host = rh.WIALON_HOST.replace("https://", "").replace("http://", "")
        r = requests.get(f"https://geocode-maps.wialon.com/{host}/gis_geocode", timeout=30, params={
            "coords": json.dumps([{"lon": lon, "lat": lat}]), "flags": 1255211008, "uid": usuario})
        datos = r.json()
        if isinstance(datos, list) and datos and datos[0]:
            texto = datos[0]
    except (requests.RequestException, ValueError):
        pass
    cache[clave] = texto
    return texto


REGIONES = ("region", "región", "metropolitana", "libertador", "maule", "valparaiso", "valparaíso", "biobio",
            "biobío", "nuble", "ñuble", "araucania", "araucanía", "coquimbo", "los lagos", "los rios", "los ríos")


def localidad(texto):
    """Comuna o localidad de una direccion de Wialon: sin el pais, la region
    ni la calle ("Ruta I-540, Paredones, Libertador ..., Chile" -> "Paredones").
    Si la direccion no trae comuna, None (se muestran las coordenadas)."""
    partes = [p.strip() for p in (texto or "").split(",") if p.strip() and p.strip().lower() != "chile"]
    partes = [p for p in partes if not p.lower().startswith(REGIONES)]
    if len(partes) >= 2:
        partes = partes[1:]  # la primera es la calle o la ruta
    sin_numero = [p for p in partes if not re.search(r"\d", p)]
    return sin_numero[-1] if sin_numero else None


# ---------------------------------------------------------------------------
# Calculos sobre el GPS
# ---------------------------------------------------------------------------

def distancia_m(a, b):
    return math.hypot(*rh.punto_a_metros(b, a))


def limpiar_puntos(puntos, vmax):
    """Quita el baile del GPS detenido (rh.adelgazar_puntos) y los saltos: un
    punto al que se llega y del que se vuelve a velocidad imposible."""
    puntos = rh.adelgazar_puntos(puntos)
    cambio = True
    while cambio and len(puntos) >= 3:
        cambio = False
        quedan = [puntos[0]]
        for k in range(1, len(puntos) - 1):
            a, p, b = quedan[-1], puntos[k], puntos[k + 1]
            ida = velocidad_kmh(a, p)
            vuelta = velocidad_kmh(p, b)
            if ida > vmax and vuelta > vmax and velocidad_kmh(a, b) <= vmax:
                cambio = True
                continue
            quedan.append(p)
        quedan.append(puntos[-1])
        puntos = quedan
    return puntos


def velocidad_kmh(a, b):
    dt = (b["t"] or 0) - (a["t"] or 0)
    d = distancia_m(a["punto"], b["punto"])
    if dt <= 0:
        return 0.0 if d < 50 else float("inf")
    return d / dt * 3.6


def km_recorridos(puntos, vmax):
    limpios = limpiar_puntos(puntos, vmax)
    total = 0.0
    for a, b in zip(limpios, limpios[1:]):
        if velocidad_kmh(a, b) <= vmax:
            total += distancia_m(a["punto"], b["punto"])
    # Menos de medio km en el dia es el GPS detenido, no un recorrido.
    return total / 1000 if total >= KM_MINIMO_SE_MOVIO * 1000 else 0.0


def tramos_en_movimiento(puntos):
    """[(a, b)] tramos entre puntos seguidos con la maquina en movimiento
    (mismo criterio que las horas del tablero: >= 1 km/h, hasta 10 min)."""
    salida = []
    for a, b in zip(puntos, puntos[1:]):
        dt = (b["t"] or 0) - (a["t"] or 0)
        if 0 < dt <= 600 and distancia_m(a["punto"], b["punto"]) / dt * 3.6 >= rh.VELOCIDAD_MINIMA_MOVIMIENTO_KMH:
            salida.append((a, b))
    return salida



def lugar_del_punto(punto, indice, patio):
    """"CYH", el nombre de la geocerca donde cae el punto, o None."""
    x, y = punto
    if patio:
        x1, y1, x2, y2 = patio["bbox"]
        if x1 <= x <= x2 and y1 <= y <= y2 and rh.punto_en_poligono(punto, patio["contorno"]):
            return "CYH"
    cubeta = (int(math.floor(x / rh.GRADOS_CUBETA_INDICE)), int(math.floor(y / rh.GRADOS_CUBETA_INDICE)))
    for geo in indice.get(cubeta, ()):
        x1, y1, x2, y2 = geo["bbox"]
        if x1 <= x <= x2 and y1 <= y <= y2 and rh.punto_en_poligono(punto, geo["contorno"]):
            return geo["nombre"]
    return None


def nombre_lugar(punto, indice, patio, usuario):
    """CYH, campo de la geocerca, comuna (direcciones de Wialon) o coordenadas."""
    lugar = lugar_del_punto(punto, indice, patio)
    if lugar:
        return lugar if lugar == "CYH" else nombre_campo(lugar), None
    lon, lat = punto
    mapa = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    return (localidad(direccion(usuario, lon, lat)) if usuario else None) or f"{lat:.4f}, {lon:.4f}", mapa


def recorrido_vehiculo(puntos, indice, patio, usuario):
    """Visitas en el orden en que paso: CYH, geocercas donde estuvo al menos
    MINUTOS_EN_GEOCERCA, y cada parada de al menos MINUTOS_PARADA_FUERA fuera
    de geocercas (con su comuna). [{"nombre", "tipo": cyh/campo/comuna,
    "detalle" (geocerca), "llegada" (unix), "minutos", "mapa"}]"""
    tramos = []  # [lugar, t_inicio, t_fin, k_inicio, k_fin]
    for k, p in enumerate(puntos):
        lugar = lugar_del_punto(p["punto"], indice, patio)
        if tramos and tramos[-1][0] == lugar:
            tramos[-1][2], tramos[-1][4] = p["t"], k
        else:
            tramos.append([lugar, p["t"], p["t"], k, k])
    visitas = []
    mapa_de = lambda punto: f"https://www.google.com/maps?q={punto[1]:.6f},{punto[0]:.6f}"
    for lugar, t0, t1, k0, k1 in tramos:
        if lugar == "CYH":
            visitas.append({"nombre": "CYH", "tipo": "cyh", "detalle": None, "llegada": t0,
                            "minutos": round((t1 - t0) / 60), "mapa": mapa_de(puntos[k0]["punto"])})
        elif lugar:
            if t1 - t0 >= MINUTOS_EN_GEOCERCA * 60:
                visitas.append({"nombre": nombre_campo(lugar), "tipo": "campo", "detalle": lugar, "llegada": t0,
                                "minutos": round((t1 - t0) / 60), "mapa": mapa_de(puntos[k0]["punto"])})
        else:
            k = k0
            while k <= k1:
                j = k
                while j + 1 <= k1 and distancia_m(puntos[k]["punto"], puntos[j + 1]["punto"]) < 150:
                    j += 1
                if puntos[j]["t"] - puntos[k]["t"] >= MINUTOS_PARADA_FUERA * 60:
                    nombre, mapa = nombre_lugar(puntos[k]["punto"], indice, patio, usuario)
                    visitas.append({"nombre": nombre, "tipo": "comuna", "detalle": None, "llegada": puntos[k]["t"],
                                    "minutos": round((puntos[j]["t"] - puntos[k]["t"]) / 60),
                                    "mapa": mapa or mapa_de(puntos[k]["punto"])})
                k = j + 1
    return visitas


def lugares_en_orden(visitas):
    """Visitas sin repetir el mismo lugar seguido (CYH -> Nancagua -> CYH)."""
    salida = []
    for v in visitas:
        if not salida or salida[-1]["nombre"] != v["nombre"]:
            salida.append(v)
    return salida


# ---------------------------------------------------------------------------
# Datos del reporte
# ---------------------------------------------------------------------------

def nombre_campo(nombre_cuartel):
    """Nombre del campo para mostrar (como nombreCampo de la pagina)."""
    palabras = []
    for p in re.split(r"[\s_]+", nombre_cuartel):
        if re.search(r"\d", p):
            break
        if p:
            palabras.append(p)
    return " ".join(palabras) or nombre_cuartel


def agrupar_geocercas(nombres):
    """["Candelaria 5", "Candelaria 7", "Aurora 3"] -> "Candelaria 5, 7 · Aurora 3"."""
    grupos = {}
    for n in nombres:
        campo = nombre_campo(n)
        resto = n[len(campo):].strip() if n.startswith(campo) else n
        grupos.setdefault(campo, []).append(resto)
    partes = []
    for campo, restos in grupos.items():
        restos = [r for r in restos if r]
        partes.append(f"{campo} {', '.join(restos)}" if restos else campo)
    return " · ".join(partes)


def fechas_completado(historico):
    """{(cuartel, labor): fecha} en que llego al 95 % (como la pagina)."""
    area = {}
    for r in historico:
        area[r["cuartel"]] = max(area.get(r["cuartel"], 0), r["area_total_ha"])
    acumulado, completos = {}, {}
    for r in sorted(historico, key=lambda r: r["fecha"]):
        if r["labor"] == rh.LABOR_CON_PASADAS or r.get("repaso"):
            continue  # cada temporada parte de cero; los repasos van aparte
        k = (r["cuartel"], r["labor"], r.get("temporada"))
        acumulado[k] = acumulado.get(k, 0) + r["area_trabajada_ha"]
        if k not in completos and acumulado[k] >= rh.UMBRAL_CIERRE_PORCENTAJE * area[r["cuartel"]] - 1e-6:
            completos[k] = r["fecha"]
    return completos




def campo_cercano(lon, lat, geocercas, maximo_m=5000):
    """(campo, distancia en m) de la geocerca mas cercana a menos de maximo_m."""
    mejor = None
    for g in geocercas:
        x1, y1, x2, y2 = g["bbox"]
        if lon < x1 - 0.06 or lon > x2 + 0.06 or lat < y1 - 0.05 or lat > y2 + 0.05:
            continue  # a mas de ~5 km
        d = min(distancia_m((lon, lat), p) for p in g["contorno"])
        if d <= maximo_m and (mejor is None or d < mejor[1]):
            mejor = (nombre_campo(g["nombre"]), d)
    return mejor


def trabajo_sin_geocerca(maquinas, fechas, geocercas, usuario):
    """Trabajo sin geocerca de los 7 dias (alertas del tablero), un lugar por
    fila: se juntan todos los dias y maquinas de la misma comuna o localidad
    (direcciones de Wialon); sin comuna, a menos de DISTANCIA_MISMO_LUGAR_M."""
    lugares = {}
    for m in maquinas:
        for f in fechas:
            for s in m["dias"][f]["sin_geocerca"]:
                q = re.search(r"q=([-\d.]+),([-\d.]+)", s.get("mapa") or "")
                if not q:
                    continue
                lat, lon = float(q.group(1)), float(q.group(2))
                nombre = localidad(direccion(usuario, lon, lat)) if usuario else None
                clave = nombre or next((k for k, g in lugares.items() if not g["nombre"] and distancia_m(
                    (g["lon"], g["lat"]), (lon, lat)) <= rh.DISTANCIA_MISMO_LUGAR_M), f"{lat:.4f},{lon:.4f}")
                g = lugares.setdefault(clave, {"nombre": nombre, "lat": lat, "lon": lon, "mapa": s["mapa"],
                                               "maquinas": [], "dias": [], "horas": 0.0, "ha": 0.0})
                if m["nombre"] not in g["maquinas"]:
                    g["maquinas"].append(m["nombre"])
                g["dias"].append({"fecha": f, "maquina": m["nombre"], "horas": s["horas"], "ha": s["ha_est"],
                                  "mapa": s["mapa"]})
                g["horas"] += s["horas"]
                g["ha"] += s["ha_est"]
    for g in lugares.values():
        mayor = max(g["dias"], key=lambda d: d["horas"])  # el punto con mas trabajo representa el lugar
        q = re.search(r"q=([-\d.]+),([-\d.]+)", mayor["mapa"])
        g["lat"], g["lon"], g["mapa"] = float(q.group(1)), float(q.group(2)), mayor["mapa"]
        g["cerca"] = campo_cercano(g["lon"], g["lat"], geocercas)
        g["dias"].sort(key=lambda d: (d["fecha"], d["maquina"]))
    return sorted(lugares.values(), key=lambda g: -g["horas"])


def rendimientos(flota, historico, avance):
    """Ha por hora de cada maquina en sus cuarteles con geocerca: dias de los
    ultimos 30 con hectareas y horas en geocercas, SIN los dias en que se
    completo un cuartel (ese dia se acredita el area total y el ha/h se
    infla; en barrido, los dias de cierre de una pasada). Propio si tiene al
    menos DIAS_MINIMOS_RENDIMIENTO dias y HORAS_MINIMAS_RENDIMIENTO horas; si no,
    el promedio de la flota en su labor (con la misma regla).
    {maquina: (ha_h, fuente, dias, horas)}"""
    dias = {d["fecha"] for m in flota.get("maquinas", []) for d in m.get("dias", [])}
    completos = {(c, l, f) for (c, l, _), f in fechas_completado(historico).items()}
    for cuartel, info in avance.items():
        for f in ((info.get("labores") or {}).get(rh.LABOR_CON_PASADAS) or {}).get("cierres") or []:
            completos.add((cuartel, rh.LABOR_CON_PASADAS, f))
    ha, con_cierre = {}, set()
    for r in historico:
        if r["fecha"] in dias:
            ha[(r["maquina"], r["fecha"])] = ha.get((r["maquina"], r["fecha"]), 0) + r["area_trabajada_ha"]
            if (r["cuartel"], r["labor"], r["fecha"]) in completos:
                con_cierre.add((r["maquina"], r["fecha"]))
    labor = {u["nombre"]: rh.labor_de(u) for u in rh.UNIDADES}
    propio, por_labor = {}, {}
    for m in flota.get("maquinas", []):
        n_dias, horas, hectareas = 0, 0.0, 0.0
        for d in m.get("dias", []):
            h = sum((d.get("horas_geocercas") or {}).values())
            a = ha.get((m["nombre"], d["fecha"]), 0)
            if h > 0 and a > 0 and (m["nombre"], d["fecha"]) not in con_cierre:
                n_dias += 1
                horas += h
                hectareas += a
        propio[m["nombre"]] = (hectareas, horas, n_dias)
        t = por_labor.setdefault(labor.get(m["nombre"]), [0.0, 0.0, 0])
        t[0] += hectareas
        t[1] += horas
        t[2] += n_dias
    salida = {}
    for nombre, (a, h, n) in propio.items():
        if n >= DIAS_MINIMOS_RENDIMIENTO and h >= HORAS_MINIMAS_RENDIMIENTO:
            salida[nombre] = (a / h, "propio", n, h)
        else:
            a_l, h_l, n_l = por_labor.get(labor.get(nombre), (0, 0, 0))
            salida[nombre] = (a_l / h_l, "flota", n_l, h_l) if h_l > 0 else (None, "gps", 0, 0)
    return salida


def datos_reporte(sid, usuario, ayer):
    dias = [ayer - timedelta(days=k) for k in range(DIAS_RESUMEN - 1, -1, -1)]
    fechas = [d.isoformat() for d in dias]
    with open(rh.RUTA_FLOTA, "r", encoding="utf-8") as f:
        flota = json.load(f)
    if not any(m.get("ultima_conexion") for m in flota.get("maquinas", [])):
        raise RuntimeError("El tablero de la flota (flota.json) no trae la ultima conexion de ninguna maquina")
    historico = rh.cargar_historico()
    with open(rh.RUTA_AVANCE_CUARTELES, "r", encoding="utf-8") as f:
        avance = json.load(f).get("cuarteles", {})

    geocercas = rh.obtener_geocercas(sid)
    patio = next((g for g in rh.obtener_geocercas(sid, filtrar=False)
                  if g["nombre"].strip().lower() == rh.GEOCERCA_PATIO.strip().lower()), None)
    indice = rh.indice_geocercas(geocercas)

    ha = {}
    for r in historico:
        if r["fecha"] in fechas:
            ha[(r["maquina"], r["fecha"])] = ha.get((r["maquina"], r["fecha"]), 0) + r["area_trabajada_ha"]

    # Maquinas: hectareas del historial; horas, geocercas y alertas del tablero.
    rend = rendimientos(flota, historico, avance)
    maquinas = []
    por_nombre_flota = {m["nombre"]: m for m in flota.get("maquinas", [])}
    for unidad in sorted(rh.UNIDADES, key=lambda u: rh.orden_flota(u["nombre"])):
        nombre = unidad["nombre"]
        mf = por_nombre_flota.get(nombre, {})
        dias_flota = {d["fecha"]: d for d in mf.get("dias", [])}
        filas = {}
        for fecha in fechas:
            d = dias_flota.get(fecha, {})
            horas_geo = d.get("horas_geocercas", {}) or {}
            sin = [dict(x) for x in d.get("sin_geocerca", []) or []]
            ha_h = rend.get(nombre, (None,))[0]
            for x in sin:
                x["ha_est"] = x["horas"] * ha_h if ha_h else x["ha"]
            fila = {"ha": ha.get((nombre, fecha), 0.0), "horas_geocercas": horas_geo,
                    "ha_sin": sum(x["ha_est"] for x in sin),
                    "horas_sin": sum(s["horas"] for s in sin), "sin_geocerca": sin,
                    "fin_lugar": (d.get("fin") or {}).get("lugar")}
            fila["horas"] = sum(horas_geo.values()) + fila["horas_sin"]
            fila["trabajo"] = (fila["ha"] > 0 or bool(sin)
                               or any(h >= rh.HORAS_MINIMAS_ALERTA for h in horas_geo.values()))
            fila["se_movio"] = fila["trabajo"] or bool(horas_geo)
            filas[fecha] = fila
        maquinas.append({"nombre": nombre, "labor": rh.labor_de(unidad), "rendimiento": rend.get(nombre),
                         "grupo": rh.NOMBRES_GRUPOS_FLOTA[rh.orden_flota(nombre)[0]],
                         "ubicacion": mf.get("ubicacion"), "ultima_conexion": mf.get("ultima_conexion"),
                         "dias": filas})

    # Camionetas y camion: km y lugares (sin horas).
    vehiculos = []
    for v in VEHICULOS:
        filas = {}
        for dia in dias:
            fecha = dia.isoformat()
            mensajes = mensajes_dia(sid, v["id"], dia)
            puntos = [{"punto": (m["pos"]["x"], m["pos"]["y"]), "t": m["t"]} for m in mensajes]
            movimiento = tramos_en_movimiento(puntos)
            fila = {"km": km_recorridos(puntos, VELOCIDAD_MAXIMA_VEHICULO_KMH) if len(puntos) > 1 else 0.0,
                    "salida": movimiento[0][0]["t"] if movimiento else None,
                    "llegada": movimiento[-1][1]["t"] if movimiento else None}
            fila["se_movio"] = fila["km"] >= KM_MINIMO_SE_MOVIO
            fila["visitas"] = recorrido_vehiculo(puntos, indice, patio, usuario) if fila["se_movio"] else []
            fila["lugares"] = lugares_en_orden(fila["visitas"])
            if not fila["se_movio"]:
                fin_dia = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA).timestamp() + 86400
                if puntos:
                    pos, fuente = puntos[-1]["punto"], "dia"
                else:
                    ultima = ultima_posicion(sid, v["id"], fin_dia)
                    pos, fuente = (ultima[:2], ultima[2]) if ultima else (None, None)
                fila["donde_quedo"] = nombre_lugar(pos, indice, patio, usuario) if pos else ("ubicación desconocida", None)
                fila["fuente_posicion"] = fuente
            filas[fecha] = fila
        vehiculos.append({"nombre": v["nombre"], "tipo": v.get("tipo", "camioneta"), "dias": filas})

    # Avance por campo en los 7 dias.
    completos = fechas_completado(historico)
    campos = {}
    for r in historico:
        if r["fecha"] in fechas and r["area_trabajada_ha"] > 0:
            c = campos.setdefault(nombre_campo(r["cuartel"]), {"labores": set(), "ha": 0.0, "terminados": set()})
            c["labores"].add(r["labor"])
            c["ha"] += r["area_trabajada_ha"]
    for (cuartel, labor, _), fecha in completos.items():
        if fecha in fechas and nombre_campo(cuartel) in campos:
            campos[nombre_campo(cuartel)]["terminados"].add((cuartel, labor))
    for cuartel, info in avance.items():
        cierres = ((info.get("labores") or {}).get(rh.LABOR_CON_PASADAS) or {}).get("cierres") or []
        if any(f in fechas for f in cierres) and nombre_campo(cuartel) in campos:
            campos[nombre_campo(cuartel)]["terminados"].add((cuartel, rh.LABOR_CON_PASADAS))

    sin_geocerca = trabajo_sin_geocerca(maquinas, fechas, geocercas, usuario)
    alarmas = []
    if os.path.exists(rh.RUTA_ALARMAS):
        with open(rh.RUTA_ALARMAS, "r", encoding="utf-8") as f:
            alarmas = [a for a in json.load(f) if a["fecha"] in fechas]

    return {"ayer": ayer, "dias": dias, "flota": flota, "maquinas": maquinas, "sin_geocerca": sin_geocerca,
            "alarmas_labor": alarmas,
            "camionetas": [v for v in vehiculos if v["tipo"] != "camion"],
            "camiones": [v for v in vehiculos if v["tipo"] == "camion"], "campos": campos}


# ---------------------------------------------------------------------------
# HTML del correo (estilos en linea: Gmail y Outlook, celular y escritorio)
# ---------------------------------------------------------------------------

def num(v, dec=1):
    texto = f"{v:,.{dec}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def hora(t):
    return datetime.fromtimestamp(t, ZONA).strftime("%H:%M") if t else "–"


def fecha_larga(d, anio=True):
    """"lunes 19 de octubre de 2026"; con anio=False solo el dia de la semana."""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
             "octubre", "noviembre", "diciembre"]
    if not anio:
        return dias[d.weekday()]
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]} de {d.year}"


def ha_texto(ha, ha_sin, total=False):
    """"4,54", "(~3,8)", "4,54 (~1,0)" o, en el total, "14,97 (+~12,6)"."""
    if not ha and not ha_sin:
        return "–"
    partes = [num(ha, 2)] if ha or total else []
    if ha_sin:
        partes.append(f'<span style="color:{ROJO};">({"+" if total else ""}~{num(ha_sin)})</span>')
    return " ".join(partes)


def fecha_corta(d):
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    return f"{dias[d.weekday()]} {d:%d-%m}"


def enlace(texto, url, color=VERDE):
    return f'<a href="{escape(url)}" style="color:{color};text-decoration:underline;">{texto}</a>'


def titulo(texto):
    return (f'<tr><td style="padding:22px 0 8px 0;font-family:{FUENTE};font-size:17px;font-weight:bold;'
            f'color:{VERDE};border-bottom:2px solid {VERDE};">{texto}</td></tr>')


def subtitulo(texto):
    return (f'<tr><td style="padding:14px 0 6px 0;font-family:{FUENTE};font-size:14px;font-weight:bold;'
            f'color:{TEXTO};">{texto}</td></tr>')


def parrafo(texto, color=TEXTO_SUAVE, tam=13):
    return f'<tr><td style="padding:6px 0;font-family:{FUENTE};font-size:{tam}px;color:{color};line-height:1.45;">{texto}</td></tr>'


def tabla(columnas, filas, alinear, total=None, estilos_fila=None, ocultar_celular=()):
    """Tabla con encabezado verde, filas alternadas y fila de totales.
    alinear: "l" o "r" por columna. estilos_fila[i]: fondo especial de la fila.
    ocultar_celular: columnas que no se muestran en pantallas angostas."""
    oc = lambda k: ' class="ocm"' if k in ocultar_celular else ""
    th = "".join(f'<th{oc(k)} align="{"left" if a == "l" else "right"}" style="padding:7px 4px;background:{VERDE};'
                 f'color:#ffffff;font-family:{FUENTE};font-size:12px;font-weight:bold;">{c}</th>'
                 for k, (c, a) in enumerate(zip(columnas, alinear)))
    cuerpo = []
    for i, fila in enumerate(filas):
        if isinstance(fila, str):  # fila de grupo
            cuerpo.append(f'<tr><td colspan="{len(columnas)}" style="padding:8px 6px 4px 6px;background:{VERDE_CLARO};'
                          f'font-family:{FUENTE};font-size:12px;font-weight:bold;color:{VERDE};">{fila}</td></tr>')
            continue
        fondo = (estilos_fila or {}).get(i) or (GRIS_FILA if i % 2 else "#ffffff")
        celdas = "".join(f'<td{oc(k)} align="{"left" if a == "l" else "right"}" valign="top" style="padding:6px 4px;'
                         f'font-family:{FUENTE};font-size:12px;color:{TEXTO};border-bottom:1px solid #E3E8E5;">{v}</td>'
                         for k, (v, a) in enumerate(zip(fila, alinear)))
        cuerpo.append(f'<tr style="background:{fondo};">{celdas}</tr>')
    if total:
        celdas = "".join(f'<td{oc(k)} align="{"left" if a == "l" else "right"}" style="padding:7px 4px;font-family:{FUENTE};'
                         f'font-size:12px;font-weight:bold;color:{TEXTO};border-top:2px solid {VERDE};'
                         f'background:{VERDE_CLARO};">{v}</td>' for k, (v, a) in enumerate(zip(total, alinear)))
        cuerpo.append(f"<tr>{celdas}</tr>")
    return ('<tr><td style="padding:4px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;"><tr>{th}</tr>{"".join(cuerpo)}</table></td></tr>')


def indicadores(items):
    """Cajas con un numero grande y su etiqueta; en celular pasan a la fila
    siguiente solas (inline-block). Outlook de escritorio las apila."""
    cajas = "".join(
        f'<div class="caja" style="display:inline-block;vertical-align:top;width:{100 // len(items) - 2}%;min-width:150px;'
        f'margin:0 4px 6px 0;"><div style="padding:10px 8px;background:{VERDE_CLARO};border-left:4px solid {VERDE};'
        f'font-family:{FUENTE};"><div style="font-size:20px;font-weight:bold;color:{VERDE};">{v}</div>'
        f'<div style="font-size:11px;color:{TEXTO_SUAVE};padding-top:2px;">{e}</div></div></div>'
        for v, e in items)
    return f'<tr><td style="padding:4px 0;font-size:0;">{cajas}</td></tr>'


def barrita(valor, maximo):
    ancho = max(1, round(40 * valor / maximo)) if maximo and valor > 0 else 0
    barra = (f'<table role="presentation" cellpadding="0" cellspacing="0" align="right" style="border-collapse:collapse;">'
             f'<tr><td style="font-family:{FUENTE};font-size:12px;padding-right:6px;white-space:nowrap;">{num(valor, 2)}</td>'
             f'<td width="40" style="width:40px;"><table role="presentation" cellpadding="0" cellspacing="0" '
             f'style="border-collapse:collapse;"><tr>'
             + (f'<td width="{ancho}" height="8" style="width:{ancho}px;height:8px;background:{VERDE};font-size:1px;'
                f'line-height:1px;">&nbsp;</td>' if ancho else "")
             + (f'<td width="{40 - ancho}" height="8" style="width:{40 - ancho}px;height:8px;background:#E3E8E5;'
                f'font-size:1px;line-height:1px;">&nbsp;</td>' if ancho < 40 else "")
             + '</tr></table></td></tr></table>')
    return barra




def lugares_html(lugares, separador=" · ", enlaces=True):
    """Campos (geocercas) en negrita y comunas en texto normal (con mapa)."""
    partes = []
    for l in lugares:
        if l.get("tipo") == "campo":
            partes.append(f"<b>{escape(l['nombre'])}</b>")
        elif l.get("tipo") == "comuna" and enlaces and l.get("mapa"):
            partes.append(enlace(escape(l["nombre"]), l["mapa"], TEXTO))
        else:
            partes.append(escape(l["nombre"]))
    return separador.join(partes)


def sin_repetir(lugares):
    vistos, salida = set(), []
    for l in lugares:
        if l["nombre"] not in vistos:
            vistos.add(l["nombre"])
            salida.append(l)
    return salida


def mas_visitados(vehiculo, cuantos=3):
    """Lugares en mas dias de la semana (sin CYH, que es la base): "Candelaria (4 d)"."""
    dias_por_lugar = {}
    for d in vehiculo["dias"].values():
        for nombre in {l["nombre"] for l in d["lugares"]} - {"CYH"}:
            dias_por_lugar[nombre] = dias_por_lugar.get(nombre, 0) + 1
    top = sorted(dias_por_lugar.items(), key=lambda x: (-x[1], x[0]))[:cuantos]
    return ", ".join(f"{escape(n)} ({k} d)" for n, k in top) or "–"


def armar_html(datos):
    ayer, dias = datos["ayer"], datos["dias"]
    fa = ayer.isoformat()
    flota = datos["flota"]
    maquinas, camionetas, camiones = datos["maquinas"], datos["camionetas"], datos["camiones"]
    km = lambda lista, f: sum(v["dias"][f]["km"] for v in lista)
    filas_html = []

    # 1. Encabezado
    encabezado = (
        f'<tr><td style="padding:18px 16px;background:{VERDE};font-family:{FUENTE};color:#ffffff;">'
        f'<div style="font-size:20px;font-weight:bold;">Reporte diario de flota – C&amp;H Maquinaria</div>'
        f'<div style="font-size:14px;padding-top:6px;">Día reportado: <b>{fecha_larga(ayer)}</b></div>'
        f'<div style="font-size:13px;padding-top:2px;opacity:0.9;">Últimos 7 días: {dias[0]:%d-%m-%Y} al {ayer:%d-%m-%Y}</div>'
        f'</td></tr>'
        + (f'<tr><td style="padding:6px 16px;background:#FFF6DB;font-family:{FUENTE};font-size:12px;color:#7A5B00;">'
           'Marcha blanca: algunos números se están ajustando.</td></tr>' if MARCHA_BLANCA else ""))

    # 2. Resumen de ayer
    hoy_m = [(m, m["dias"][fa]) for m in maquinas]
    trabajaron = [x for x in hoy_m if x[1]["trabajo"]]
    ha_ayer = sum(d["ha"] for _, d in hoy_m)
    ha_sin_ayer = sum(d["ha_sin"] for _, d in hoy_m)
    horas_ayer = sum(d["horas"] for _, d in hoy_m)
    movidas = sum(1 for v in camionetas if v["dias"][fa]["se_movio"])
    filas_html.append(titulo(f"Resumen de ayer ({fecha_larga(ayer, anio=False)} {ayer:%d-%m-%Y})"))
    filas_html.append(indicadores([(f"{len(trabajaron)} de {len(maquinas)}", "máquinas trabajaron"),
                                   (num(ha_ayer, 2), f"ha en geocercas + ~{num(ha_sin_ayer)} ha estimadas sin geocerca"),
                                   (num(horas_ayer), "horas de las máquinas")]))
    cajas = [(f"{num(km(camionetas, fa), 0)} km", f"camionetas ({movidas} de {len(camionetas)} se movieron)")]
    for c in camiones:
        cajas.append((f"{num(c['dias'][fa]['km'], 0)} km", "camión"))
    filas_html.append(indicadores(cajas))

    # 3. Alertas (primero el aviso del token, si esta por vencer)
    alertas = []
    for a in flota.get("alertas_sin_senal", []):
        alertas.append(f'<b>GPS sin señal</b>: {escape(a["maquina"])} – última señal {escape(a["ultima_conexion"] or "")} '
                       f'({a["horas"]} h), {escape(a["ubicacion"] or "ubicación desconocida")}'
                       + (f' · {enlace("ver mapa", a["mapa"], ROJO)}' if a.get("mapa") else ""))
    for m, d in hoy_m:
        for s in d["sin_geocerca"]:
            q = re.search(r"q=([-\d.]+),([-\d.]+)", s.get("mapa") or "")
            coords = f"{float(q.group(1)):.5f}, {float(q.group(2)):.5f}" if q else ""
            alertas.append(f'<b>Trabajo sin geocerca</b>: {escape(m["nombre"])} – {num(s["horas"])} h '
                           f'(~{num(s["ha_est"])} ha estimadas) en {coords} · {enlace("ver mapa", s["mapa"], ROJO)}')
    for a in datos.get("alarmas_labor", []):
        if a["fecha"] == fa:
            alertas.append(f'<b>Alarma de labor ({escape(a["tipo"])})</b>: {escape(a["maquina"])} – {escape(a["labor"])} en '
                           f'{escape(a["cuartel"])}, {num(a["ha"], 2)} ha'
                           + (" (no suma hasta definir la labor)" if a.get("no_suma") else ""))
    filas_html.append(titulo("Alertas"))
    if alertas:
        filas_html.append('<tr><td style="padding:4px 0;"><table role="presentation" width="100%" cellpadding="0" '
                          'cellspacing="0" style="border-collapse:collapse;">' + "".join(
                              f'<tr><td style="padding:8px 10px;background:{ROJO_CLARO};border-left:4px solid {ROJO};'
                              f'font-family:{FUENTE};font-size:13px;color:{TEXTO};line-height:1.4;">{a}</td></tr>'
                              f'<tr><td style="height:4px;font-size:1px;line-height:1px;">&nbsp;</td></tr>'
                              for a in alertas) + "</table></td></tr>")
    else:
        filas_html.append(parrafo("Sin alertas: todas las máquinas con señal y ningún trabajo sin geocerca ayer."))

    # 4. Maquinas ayer (sin km)
    filas_html.append(titulo(f"Máquinas · ayer ({ayer:%d-%m})"))
    filas, estilos, grupo = [], {}, None
    for m, d in hoy_m:
        if not d["se_movio"]:
            continue
        if m["grupo"] != grupo:
            grupo = m["grupo"]
            filas.append(grupo)
        donde = escape(agrupar_geocercas(sorted(d["horas_geocercas"], key=lambda g: -d["horas_geocercas"][g])))
        if d["sin_geocerca"]:
            enlaces = ", ".join(enlace("mapa", s["mapa"], ROJO) for s in d["sin_geocerca"])
            donde = (donde + "<br>" if donde else "") + f'<span style="color:{ROJO};font-weight:bold;">Sin geocerca ' \
                                                       f'{num(d["horas_sin"])} h</span> ({enlaces})'
            estilos[len(filas)] = ROJO_CLARO
        filas.append([escape(m["nombre"]), escape(m["labor"]), donde or "–", ha_texto(d["ha"], d["ha_sin"]),
                      num(d["horas"]) if d["horas"] else "–"])
    if any(not isinstance(f, str) for f in filas):
        filas_html.append(tabla(["Máquina", "Labor", "Dónde estuvo", "Ha", "Horas"], filas,
                                ["l", "l", "l", "r", "r"], ["Total", "", "", ha_texto(ha_ayer, ha_sin_ayer, total=True), num(horas_ayer)],
                                estilos, ocultar_celular={1}))
    else:
        filas_html.append(parrafo("Ninguna máquina trabajó ayer."))
    sin_trabajo = [m for m, d in hoy_m if not d["se_movio"]]
    hace_30 = datetime.now(ZONA) - timedelta(days=rh.DIAS_FLOTA)

    def sin_senal_30(m):
        try:
            return datetime.strptime(m["ultima_conexion"], "%d-%m-%Y %H:%M").replace(tzinfo=ZONA) < hace_30
        except (TypeError, ValueError):
            return m["ultima_conexion"] is None
    n_30 = sum(1 for m in sin_trabajo if sin_senal_30(m))
    n_cyh = sum(1 for m in sin_trabajo if not sin_senal_30(m)
                and (m["dias"][fa]["fin_lugar"] == "CYH" or m["ubicacion"] == "CYH"))
    n_fuera = len(sin_trabajo) - n_30 - n_cyh
    filas_html.append(parrafo(f"No trabajaron ayer: <b>{len(sin_trabajo)}</b> máquinas — {n_cyh} en CYH, "
                              f"{n_fuera} detenidas fuera de CYH y {n_30} sin señal hace más de 30 días "
                              f"({enlace('ver lista en la página', URL_PAGINA + '#flota')})."))

    def no_se_movio(d):
        nombre, mapa = d.get("donde_quedo") or ("ubicación desconocida", None)
        lugar = enlace(escape(nombre), mapa) if mapa else escape(nombre)
        return f'<span style="color:{TEXTO_SUAVE};">No se movió · en {lugar}</span>'

    # 5. Camionetas ayer
    filas_html.append(titulo(f"Camionetas · ayer ({ayer:%d-%m})"))
    filas = []
    for v in camionetas:
        d = v["dias"][fa]
        filas.append([escape(v["nombre"]), f'<b style="font-size:14px;color:{VERDE};">{num(d["km"])}</b>',
                      f'{hora(d["salida"])} – {hora(d["llegada"])}' if d["se_movio"] else "–",
                      (lugares_html(sin_repetir(d["lugares"])) or "camino") if d["se_movio"] else no_se_movio(d)])
    filas_html.append(tabla(["Camioneta", "Km", "Salida – llegada", "Dónde estuvo"], filas, ["l", "r", "l", "l"],
                            ["Total", f'<b style="font-size:14px;">{num(km(camionetas, fa))}</b>', "", ""]))

    # Camion ayer
    for c in camiones:
        d = c["dias"][fa]
        filas_html.append(titulo(f"Camión · ayer ({ayer:%d-%m}) <span style=\"font-weight:normal;font-size:13px;color:{TEXTO_SUAVE};\">"
                                 f"({escape(c['nombre'])})</span>"))
        filas_html.append(tabla(["Km", "Salida – llegada", "Recorrido"],
                                [[f'<b style="font-size:14px;color:{VERDE};">{num(d["km"])}</b>',
                                  f'{hora(d["salida"])} – {hora(d["llegada"])}' if d["se_movio"] else "–",
                                  (lugares_html(d["lugares"], " → ") or "camino") if d["se_movio"] else no_se_movio(d)]],
                                ["r", "l", "l"]))
    filas_html.append(parrafo(f"Lugares: CYH, campos donde estuvo al menos {MINUTOS_EN_GEOCERCA} min y la comuna de "
                              f"cada parada de {MINUTOS_PARADA_FUERA} min o más fuera de geocercas.", tam=11))

    # 6. Ultimos 7 dias
    filas_html.append(titulo("Resumen últimos 7 días"))
    tot_ha = sum(d["ha"] for m in maquinas for d in m["dias"].values())
    tot_h = sum(d["horas"] for m in maquinas for d in m["dias"].values())
    tot_cam = sum(km(camionetas, f.isoformat()) for f in dias)
    tot_camion = sum(km(camiones, f.isoformat()) for f in dias)
    tot_sin = sum(d["ha_sin"] for m in maquinas for d in m["dias"].values())
    filas_html.append(indicadores([(num(tot_ha, 2), f"ha en geocercas + ~{num(tot_sin)} ha estimadas sin geocerca"),
                                   (num(tot_h), "horas de las máquinas")]))
    filas_html.append(indicadores([(f"{num(tot_cam, 0)} km", "camionetas"), (f"{num(tot_camion, 0)} km", "camión")]))

    filas_html.append(subtitulo("Día por día"))
    ha_dia = {d.isoformat(): sum(m["dias"][d.isoformat()]["ha"] for m in maquinas) for d in dias}
    maximo = max(ha_dia.values()) if ha_dia else 0
    filas = []
    for d in dias:
        f = d.isoformat()
        filas.append([fecha_corta(d), str(sum(1 for m in maquinas if m["dias"][f]["trabajo"])),
                      barrita(ha_dia[f], maximo), num(sum(m["dias"][f]["horas"] for m in maquinas)),
                      num(km(camionetas, f), 0), num(km(camiones, f), 0)])
    distintas = sum(1 for m in maquinas if any(x["trabajo"] for x in m["dias"].values()))
    filas_html.append(tabla(["Día", "Máquinas", "Hectáreas", "Horas", "Km camionetas", "Km camión"], filas,
                            ["l", "r", "r", "r", "r", "r"],
                            ["Total", f"{distintas} distintas", num(tot_ha, 2), num(tot_h), num(tot_cam, 0),
                             num(tot_camion, 0)]))

    filas_html.append(subtitulo("Por máquina"))
    filas, estilos, grupo = [], {}, None
    for m in maquinas:
        ds = m["dias"].values()
        if not any(x["se_movio"] for x in ds):
            continue
        if m["grupo"] != grupo:
            grupo = m["grupo"]
            filas.append(grupo)
        geos = {}
        for x in ds:
            for g, h in x["horas_geocercas"].items():
                geos[g] = geos.get(g, 0) + h
        donde = agrupar_geocercas(sorted(geos, key=lambda g: -geos[g]))
        horas_sin = sum(x["horas_sin"] for x in ds)
        horas_txt = num(sum(x["horas"] for x in ds))
        if horas_sin:
            horas_txt += f'<br><span style="color:{ROJO};font-size:11px;">{num(horas_sin)} h sin geocerca</span>'
            estilos[len(filas)] = ROJO_CLARO
        filas.append([escape(m["nombre"]), escape(donde) or "–", str(sum(1 for x in ds if x["trabajo"] or x["horas"] > 0)),
                      num(sum(x["ha"] for x in ds), 2), horas_txt])
    filas_html.append(tabla(["Máquina", "Dónde estuvo", "Días", "Ha", "Horas"], filas,
                            ["l", "l", "r", "r", "r"], None, estilos))

    filas_html.append(subtitulo("Trabajo sin geocerca · últimos 7 días"))
    if datos["sin_geocerca"]:
        filas = []
        for g in datos["sin_geocerca"]:
            lugar = escape(g["nombre"] or f'{g["lat"]:.5f}, {g["lon"]:.5f}')
            if g["cerca"]:
                lugar += (f'<br><span style="color:{TEXTO_SUAVE};font-size:11px;">cerca de {escape(g["cerca"][0])} '
                          f'({num(g["cerca"][1] / 1000)} km)</span>')
            dias_g = sorted({d["fecha"] for d in g["dias"]})
            rango = (f'{date.fromisoformat(dias_g[0]):%d-%m}' + (f' a {date.fromisoformat(dias_g[-1]):%d-%m}'
                                                                 if len(dias_g) > 1 else ""))
            filas.append([lugar, escape(", ".join(g["maquinas"])),
                          f'{len(dias_g)}<br><span style="color:{TEXTO_SUAVE};font-size:11px;">{rango}</span>',
                          num(g["horas"]), num(g["ha"]), enlace("mapa", g["mapa"], ROJO)])
        filas_html.append(tabla(["Lugar", "Máquinas", "Días", "Horas", "Ha estim.", "Mapa"], filas,
                                ["l", "l", "r", "r", "r", "l"],
                                ["Total", "", "", num(sum(g["horas"] for g in datos["sin_geocerca"])),
                                 num(sum(g["ha"] for g in datos["sin_geocerca"])), ""]))
        filas_html.append(parrafo("Trabajo real en campos sin geocerca en Wialon: crear la geocerca hace que "
                                  "esas hectáreas se recuperen y el lugar salga de esta lista.", tam=11))
    else:
        filas_html.append(parrafo("Sin trabajo fuera de geocercas en los últimos 7 días."))

    def tabla_vehiculos(lista, total, encabezado):
        filas = [[escape(v["nombre"]), str(sum(1 for x in v["dias"].values() if x["se_movio"])),
                  num(sum(x["km"] for x in v["dias"].values())), mas_visitados(v)] for v in lista]
        pie = ["Total", "", num(sum(x["km"] for v in lista for x in v["dias"].values())), ""] if total else None
        return tabla([encabezado, "Días con movimiento", "Km", "Lugares más visitados"], filas,
                     ["l", "r", "r", "l"], pie)
    filas_html.append(subtitulo("Camionetas"))
    filas_html.append(tabla_vehiculos(camionetas, True, "Camioneta"))
    if camiones:
        filas_html.append(subtitulo("Camión"))
        filas_html.append(tabla_vehiculos(camiones, False, "Camión"))

    filas_html.append(subtitulo("Avance por campo"))
    filas = []
    for campo, c in sorted(datos["campos"].items(), key=lambda x: -x[1]["ha"]):
        n = len(c["terminados"])
        por_labor = {}
        for _, labor in c["terminados"]:
            por_labor[labor] = por_labor.get(labor, 0) + 1
        detalle = f' <span style="color:{TEXTO_SUAVE};">({", ".join(f"{l} {k}" for l, k in sorted(por_labor.items()))})</span>' if n else ""
        filas.append([escape(campo), escape(", ".join(sorted(c["labores"]))), num(c["ha"], 2), f"{n}{detalle}"])
    if filas:
        filas_html.append(tabla(["Campo", "Labores", "Ha 7 días", "Cuarteles terminados"], filas, ["l", "l", "r", "l"],
                                ["Total", "", num(sum(c["ha"] for c in datos["campos"].values()), 2),
                                 str(sum(len(c["terminados"]) for c in datos["campos"].values()))]))
    else:
        filas_html.append(parrafo("Sin hectáreas registradas en los últimos 7 días."))

    # 7. Boton a la pagina
    filas_html.append(
        f'<tr><td align="center" style="padding:24px 0 8px 0;"><table role="presentation" cellpadding="0" cellspacing="0">'
        f'<tr><td style="background:{VERDE};border-radius:6px;"><a href="{URL_PAGINA}" style="display:inline-block;'
        f'padding:12px 22px;font-family:{FUENTE};font-size:15px;font-weight:bold;color:#ffffff;text-decoration:none;">'
        f'Ver la página completa</a></td></tr></table></td></tr>')
    filas_html.append(parrafo(
        "Máquinas: hectáreas, labores, geocercas y horas son las mismas que calcula el sistema (horas en movimiento "
        "dentro de geocercas más el trabajo sin geocerca). Camionetas y camión: km del recorrido GPS del día en hora "
        f"de Chile, sin los puntos detenidos ni los saltos del GPS. Generado el {datetime.now(ZONA):%d-%m-%Y %H:%M}.",
        tam=11))

    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light"><title>Reporte diario de flota</title>'
            "<style>@page{size:A4;margin:12mm;} @media print{.pagina{max-width:none!important;}} "
            "@media screen and (max-width:520px){.ocm{display:none!important;} .caja{width:47%!important;min-width:0!important;}}</style></head>"
            f'<body style="margin:0;padding:0;background:#F1F4F2;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F4F2;">'
            '<tr><td align="center" style="padding:8px 0;">'
            '<table role="presentation" class="pagina" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:720px;background:#ffffff;border-collapse:collapse;">'
            f'{encabezado}<tr><td style="padding:0 10px 16px 10px;"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(filas_html)}</table></td></tr>'
            '</table></td></tr></table></body></html>')


def alarmas_labor_txt(datos, fecha):
    """Fuera de temporada, repasos y "Revisar labor" de ese dia, en una linea."""
    lista = [a for a in datos.get("alarmas_labor", []) if a["fecha"] == fecha]
    if not lista:
        return "ninguna"
    partes = [f'{escape(a["maquina"])}: {escape(a["tipo"].lower())} ({escape(a["labor"])}, {escape(a["cuartel"])}, '
              f'{"~" if a.get("no_suma") else ""}{num(a["ha"], 2)} ha{" sin sumar" if a.get("no_suma") else ""})'
              for a in lista[:4]]
    return "; ".join(partes) + (f" y {len(lista) - 4} más" if len(lista) > 4 else "")


def boton_detalle(ancla):
    url = f"{URL_PAGINA}reporte.html#{ancla}"
    return (f'<tr><td align="right" style="padding:6px 0 2px 0;"><a href="{url}" style="display:inline-block;'
            f'padding:6px 12px;border:1px solid {VERDE};border-radius:5px;font-family:{FUENTE};font-size:12px;'
            f'font-weight:bold;color:{VERDE};text-decoration:none;">Ver detalle &rsaquo;</a></td></tr>')


def linea(texto, tam=13):
    return (f'<tr><td style="padding:5px 0;font-family:{FUENTE};font-size:{tam}px;color:{TEXTO};'
            f'line-height:1.45;">{texto}</td></tr>')


def armar_html_corto(datos):
    """Cuerpo del correo: corto y resumido; cada seccion con "Ver detalle"
    (la pagina reporte.html) y el detalle completo en el PDF adjunto."""
    ayer, dias = datos["ayer"], datos["dias"]
    fa = ayer.isoformat()
    flota = datos["flota"]
    maquinas, camionetas, camiones = datos["maquinas"], datos["camionetas"], datos["camiones"]
    km = lambda lista, f: sum(v["dias"][f]["km"] for v in lista)
    hoy_m = [(m, m["dias"][fa]) for m in maquinas]
    ha_ayer = sum(d["ha"] for _, d in hoy_m)
    ha_sin_ayer = sum(d["ha_sin"] for _, d in hoy_m)
    horas_ayer = sum(d["horas"] for _, d in hoy_m)
    movidas = sum(1 for v in camionetas if v["dias"][fa]["se_movio"])
    filas = []

    encabezado = (
        f'<tr><td style="padding:16px;background:{VERDE};font-family:{FUENTE};color:#ffffff;">'
        f'<div style="font-size:19px;font-weight:bold;">Reporte diario de flota – C&amp;H Maquinaria</div>'
        f'<div style="font-size:14px;padding-top:4px;">{fecha_larga(ayer).capitalize()}</div></td></tr>'
        + (f'<tr><td style="padding:6px 16px;background:#FFF6DB;font-family:{FUENTE};font-size:12px;color:#7A5B00;">'
           'Marcha blanca: algunos números se están ajustando.</td></tr>' if MARCHA_BLANCA else ""))

    # Resumen de ayer
    filas.append(titulo(f"Resumen de ayer ({fecha_larga(ayer, anio=False)} {ayer:%d-%m-%Y})"))
    filas.append(indicadores([
        (f"{sum(1 for _, d in hoy_m if d['trabajo'])} de {len(maquinas)}", "máquinas trabajaron"),
        (num(horas_ayer), "horas de las máquinas")]))
    filas.append(linea(f'<b style="font-size:16px;color:{VERDE};">{num(ha_ayer, 2)} ha</b> en geocercas'
                       + (f' + <b style="color:{ROJO};">~{num(ha_sin_ayer)} ha</b> estimadas sin geocerca'
                          if ha_sin_ayer else "")))
    km_camion = " · ".join(f'<b>{num(c["dias"][fa]["km"], 0)} km</b> camión' for c in camiones)
    filas.append(linea(f'<b>{num(km(camionetas, fa), 0)} km</b> camionetas ({movidas} de {len(camionetas)} se movieron)'
                       + (f" · {km_camion}" if km_camion else "")))
    filas.append(boton_detalle("resumen"))

    # Alertas en 2 lineas
    filas.append(titulo("Alertas"))
    sin_senal = flota.get("alertas_sin_senal", [])
    texto = ", ".join(f'{escape(a["maquina"])} (desde {escape((a["ultima_conexion"] or "")[:5])})' for a in sin_senal)
    filas.append(linea(f'<b style="color:{ROJO if sin_senal else TEXTO};">GPS sin señal:</b> {texto or "ninguna"}'))
    sin_geo = [(m, d) for m, d in hoy_m if d["sin_geocerca"]]
    texto = ", ".join(f'{escape(m["nombre"])} (~{num(d["ha_sin"])} ha)' for m, d in sin_geo)
    filas.append(linea(f'<b style="color:{ROJO if sin_geo else TEXTO};">Trabajo sin geocerca:</b> {texto or "ninguno"}'))
    filas.append(linea(f'<b style="color:{ROJO if alarmas_labor_txt(datos, fa) != "ninguna" else TEXTO};">'
                       f'Alarmas de labor:</b> {alarmas_labor_txt(datos, fa)}'))
    filas.append(boton_detalle("sin-geocerca"))

    # Maquinas ayer
    filas.append(titulo(f"Máquinas · ayer ({ayer:%d-%m})"))
    lista, estilos = [], {}
    for m, d in hoy_m:
        if not d["se_movio"]:
            continue
        lugar = agrupar_geocercas(sorted(d["horas_geocercas"], key=lambda g: -d["horas_geocercas"][g]))
        if d["sin_geocerca"]:
            lugar = (lugar + " · " if lugar else "") + "sin geocerca"
            estilos[len(lista)] = ROJO_CLARO
        lista.append([f'<b>{escape(m["nombre"])}</b><br><span style="color:{TEXTO_SUAVE};font-size:11px;">'
                      f'{escape(m["labor"])} · {escape(lugar or "–")}</span>',
                      ha_texto(d["ha"], d["ha_sin"]), num(d["horas"]) if d["horas"] else "–"])
    if lista:
        filas.append(tabla(["Máquina · labor · lugar", "Ha", "Horas"], lista, ["l", "r", "r"],
                           ["Total", ha_texto(ha_ayer, ha_sin_ayer, total=True), num(horas_ayer)], estilos))
    else:
        filas.append(parrafo("Ninguna máquina trabajó ayer."))
    filas.append(boton_detalle("maquinas"))

    # Camionetas ayer
    filas.append(titulo(f"Camionetas · ayer ({ayer:%d-%m})"))
    lista = []
    for v in camionetas:
        d = v["dias"][fa]
        if d["se_movio"]:
            donde = lugares_html(d["lugares"], enlaces=False) or "camino"
        else:
            donde = f'<span style="color:{TEXTO_SUAVE};">No se movió · en {escape((d.get("donde_quedo") or ("?",))[0])}</span>'
        lista.append([escape(v["nombre"]), donde, f'<b>{num(d["km"])}</b>'])
    filas.append(tabla(["Camioneta", "Dónde estuvo", "Km"], lista, ["l", "l", "r"],
                       ["Total", "", f'<b>{num(km(camionetas, fa))}</b>']))
    filas.append(parrafo("En negrita, los campos (geocercas); en texto normal, las comunas donde se detuvo.", tam=11))
    filas.append(boton_detalle("camionetas"))

    # Camion ayer
    for c in camiones:
        d = c["dias"][fa]
        filas.append(titulo(f"Camión · ayer ({ayer:%d-%m})"))
        if d["se_movio"]:
            filas.append(linea(f'<b>{num(d["km"])} km</b> · {hora(d["salida"])}–{hora(d["llegada"])} · '
                               f'{lugares_html(d["lugares"], " → ", enlaces=False)}'))
        else:
            filas.append(linea(f'0 km · No se movió · en {escape((d.get("donde_quedo") or ("?",))[0])}'))
        filas.append(boton_detalle("camion"))

    # Ultimos 7 dias
    filas.append(titulo(f"Últimos 7 días ({dias[0]:%d-%m} al {ayer:%d-%m})"))
    tot_ha = sum(d["ha"] for m in maquinas for d in m["dias"].values())
    tot_sin = sum(d["ha_sin"] for m in maquinas for d in m["dias"].values())
    tot_h = sum(d["horas"] for m in maquinas for d in m["dias"].values())
    filas.append(linea(f'<b style="font-size:15px;color:{VERDE};">{num(tot_ha, 2)} ha</b> en geocercas'
                       + (f' + <b style="color:{ROJO};">~{num(tot_sin)} ha</b> estimadas sin geocerca' if tot_sin else "")
                       + f' · <b>{num(tot_h)} h</b> de máquinas'))
    filas.append(linea(f'<b>{num(sum(km(camionetas, d.isoformat()) for d in dias), 0)} km</b> camionetas · '
                       f'<b>{num(sum(km(camiones, d.isoformat()) for d in dias), 0)} km</b> camión'))
    ha_dia = {d.isoformat(): sum(m["dias"][d.isoformat()]["ha"] for m in maquinas) for d in dias}
    maximo = max(ha_dia.values()) if ha_dia else 0
    lista = [[fecha_corta(d), str(sum(1 for m in maquinas if m["dias"][d.isoformat()]["trabajo"])),
              barrita(ha_dia[d.isoformat()], maximo), num(sum(m["dias"][d.isoformat()]["horas"] for m in maquinas)),
              num(km(camionetas, d.isoformat()), 0), num(km(camiones, d.isoformat()), 0)] for d in dias]
    filas.append(tabla(["Día", "Máq.", "Hectáreas", "Horas", "Km cam.", "Km camión"], lista,
                       ["l", "r", "r", "r", "r", "r"],
                       ["Total", "", num(tot_ha, 2), num(tot_h),
                        num(sum(km(camionetas, d.isoformat()) for d in dias), 0),
                        num(sum(km(camiones, d.isoformat()) for d in dias), 0)]))
    filas.append(boton_detalle("semana"))

    # Trabajo sin geocerca (7 dias)
    filas.append(titulo("Trabajo sin geocerca · últimos 7 días"))
    sg = datos["sin_geocerca"]
    if sg:
        top = ", ".join(f'{escape(g["nombre"] or "sin nombre")} (~{num(g["ha"])} ha)' for g in sg[:4])
        filas.append(linea(f'<b>{len(sg)} lugar{"es" if len(sg) != 1 else ""}</b> · {num(sum(g["horas"] for g in sg))} h · '
                           f'<b style="color:{ROJO};">~{num(sum(g["ha"] for g in sg))} ha estimadas</b>. '
                           f'Los que más pesan: {top}.'))
    else:
        filas.append(linea("Sin trabajo fuera de geocercas en los últimos 7 días."))
    filas.append(boton_detalle("sin-geocerca"))

    filas.append(parrafo("El detalle completo va en el PDF adjunto. Hectáreas sin geocerca: estimadas con el "
                         "rendimiento real de cada máquina (ha por hora en sus cuarteles con geocerca).", tam=11))
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light"><title>Reporte diario de flota</title>'
            "<style>@media screen and (max-width:520px){.caja{width:47%!important;min-width:0!important;}}</style></head>"
            '<body style="margin:0;padding:0;background:#F1F4F2;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F4F2;">'
            '<tr><td align="center" style="padding:8px 0;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:640px;background:#ffffff;border-collapse:collapse;">'
            f'{encabezado}<tr><td style="padding:0 10px 16px 10px;"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(filas)}</table></td></tr>'
            '</table></td></tr></table></body></html>')


RUTA_DATOS_PAGINA = os.path.join(rh.CARPETA_DATOS, "reporte_diario.json")


def no_trabajaron(maquinas, fa):
    """(sin trabajo, en CYH, detenidas fuera, sin senal > 30 dias)."""
    sin_trabajo = [m for m in maquinas if not m["dias"][fa]["se_movio"]]
    hace_30 = datetime.now(ZONA) - timedelta(days=rh.DIAS_FLOTA)

    def sin_senal_30(m):
        try:
            return datetime.strptime(m["ultima_conexion"], "%d-%m-%Y %H:%M").replace(tzinfo=ZONA) < hace_30
        except (TypeError, ValueError):
            return m["ultima_conexion"] is None
    n_30 = sum(1 for m in sin_trabajo if sin_senal_30(m))
    n_cyh = sum(1 for m in sin_trabajo if not sin_senal_30(m)
                and (m["dias"][fa]["fin_lugar"] == "CYH" or m["ubicacion"] == "CYH"))
    return len(sin_trabajo), n_cyh, len(sin_trabajo) - n_30 - n_cyh, n_30


def datos_pagina(datos):
    """docs/datos/reporte_diario.json: lo que muestra la pagina reporte.html
    (resumido, con el detalle que se despliega al tocar)."""
    ayer, dias = datos["ayer"], datos["dias"]
    fechas = [d.isoformat() for d in dias]
    fa = ayer.isoformat()
    r1 = lambda v: round(v, 1)
    hhmm = lambda t: datetime.fromtimestamp(t, ZONA).strftime("%H:%M") if t else None

    def vehiculo(v):
        salida = []
        for f in fechas:
            d = v["dias"][f]
            salida.append({
                "fecha": f, "km": r1(d["km"]), "se_movio": d["se_movio"],
                "salida": hhmm(d["salida"]), "llegada": hhmm(d["llegada"]),
                "lugares": [{"nombre": l["nombre"], "tipo": l["tipo"]} for l in d["lugares"]],
                "visitas": [{"nombre": x["nombre"], "tipo": x["tipo"], "detalle": x["detalle"],
                             "llegada": hhmm(x["llegada"]), "minutos": x["minutos"], "mapa": x["mapa"]}
                            for x in d["visitas"]],
                "donde_quedo": (d.get("donde_quedo") or [None])[0]})
        return {"nombre": v["nombre"], "km": r1(sum(x["km"] for x in salida)),
                "dias_movimiento": sum(1 for x in salida if x["se_movio"]), "dias": salida}

    maquinas = []
    for m in datos["maquinas"]:
        ds = [dict(fecha=f, **m["dias"][f]) for f in fechas if m["dias"][f]["se_movio"]]
        if not ds:
            continue
        maquinas.append({
            "nombre": m["nombre"], "labor": m["labor"], "grupo": m["grupo"],
            "rendimiento": round(m["rendimiento"][0], 2) if m.get("rendimiento") and m["rendimiento"][0] else None,
            "ha": round(sum(d["ha"] for d in ds), 2), "ha_sin": r1(sum(d["ha_sin"] for d in ds)),
            "horas": r1(sum(d["horas"] for d in ds)), "dias_trabajo": sum(1 for d in ds if d["trabajo"] or d["horas"] > 0),
            "dias": [{"fecha": d["fecha"], "ha": round(d["ha"], 2), "ha_sin": r1(d["ha_sin"]), "horas": r1(d["horas"]),
                      "horas_sin": r1(d["horas_sin"]),
                      "lugares": [{"geocerca": g, "horas": r1(h)} for g, h in
                                  sorted(d["horas_geocercas"].items(), key=lambda x: -x[1])],
                      "sin": [{"horas": r1(x["horas"]), "ha": r1(x["ha_est"]), "mapa": x["mapa"]}
                              for x in d["sin_geocerca"]]} for d in ds]})
    semana = []
    for f in fechas:
        semana.append({"fecha": f,
                       "maquinas": sum(1 for m in datos["maquinas"] if m["dias"][f]["trabajo"]),
                       "ha": round(sum(m["dias"][f]["ha"] for m in datos["maquinas"]), 2),
                       "ha_sin": r1(sum(m["dias"][f]["ha_sin"] for m in datos["maquinas"])),
                       "horas": r1(sum(m["dias"][f]["horas"] for m in datos["maquinas"])),
                       "km_camionetas": r1(sum(v["dias"][f]["km"] for v in datos["camionetas"])),
                       "km_camion": r1(sum(v["dias"][f]["km"] for v in datos["camiones"]))})
    hoy = next(x for x in semana if x["fecha"] == fa)
    n, n_cyh, n_fuera, n_30 = no_trabajaron(datos["maquinas"], fa)
    return {
        "fecha": fa, "fecha_texto": f"{fecha_larga(ayer, anio=False)} {ayer:%d-%m-%Y}", "dias": fechas,
        "generado": datetime.now(ZONA).strftime("%d-%m-%Y %H:%M"),
        "resumen": {**hoy, "total_maquinas": len(datos["maquinas"]),
                    "camionetas_movidas": sum(1 for v in datos["camionetas"] if v["dias"][fa]["se_movio"]),
                    "total_camionetas": len(datos["camionetas"]),
                    "no_trabajaron": n, "en_cyh": n_cyh, "detenidas_fuera": n_fuera, "sin_senal_30": n_30},
        "alertas": {"sin_senal": datos["flota"].get("alertas_sin_senal", []),
                    "sin_geocerca": [{"maquina": m["nombre"], "horas": r1(x["horas"]), "ha": r1(x["ha_est"]),
                                      "mapa": x["mapa"]}
                                     for m in datos["maquinas"] for x in m["dias"][fa]["sin_geocerca"]]},
        "maquinas": maquinas,
        "alarmas_labor": datos.get("alarmas_labor", []),
        "camionetas": [vehiculo(v) for v in datos["camionetas"]],
        "camion": [vehiculo(v) for v in datos["camiones"]],
        "semana": semana,
        "sin_geocerca": [{"lugar": g["nombre"] or f'{g["lat"]:.4f}, {g["lon"]:.4f}',
                          "cerca": [g["cerca"][0], r1(g["cerca"][1] / 1000)] if g["cerca"] else None,
                          "desde": min(d["fecha"] for d in g["dias"]), "hasta": max(d["fecha"] for d in g["dias"]),
                          "n_dias": len({d["fecha"] for d in g["dias"]}), "maquinas": g["maquinas"],
                          "horas": r1(g["horas"]), "ha": r1(g["ha"]), "mapa": g["mapa"],
                          "dias": [{**d, "horas": r1(d["horas"]), "ha": r1(d["ha"])} for d in g["dias"]]}
                         for g in datos["sin_geocerca"]],
        "campos": [{"campo": c, "labores": sorted(v["labores"]), "ha": round(v["ha"], 2),
                    "terminados": len(v["terminados"])}
                   for c, v in sorted(datos["campos"].items(), key=lambda x: -x[1]["ha"])],
    }


def guardar_en_repo(rutas, mensaje):
    """Sube archivos al repositorio (con reintentos si otra corrida subio algo)."""
    for intento in range(5):
        subprocess.run(["git", "add", *rutas], check=True)
        if subprocess.run(["git", "diff", "--staged", "--quiet"]).returncode == 0:
            return
        subprocess.run(["git", "commit", "-q", "-m", mensaje], check=True)
        subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], check=False)
        if subprocess.run(["git", "push", "-q"]).returncode == 0:
            return
        time.sleep(10)
    raise RuntimeError(f"No se pudo subir {rutas}")


def preparar_reporte(sid, usuario, ayer, publicar):
    """Arma el correo (corto), el PDF (detalle completo) y, si publicar, los
    datos de la pagina reporte.html. Devuelve (html_corto, ruta_pdf, datos)."""
    datos = datos_reporte(sid, usuario, ayer)
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    ruta_html = os.path.join(CARPETA_SALIDA, f"reporte_flota_{ayer}.html")
    ruta_pdf = os.path.join(CARPETA_SALIDA, f"Reporte_flota_{ayer}.pdf")
    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(armar_html(datos))
    generar_pdf(ruta_html, ruta_pdf)
    corto = armar_html_corto(datos)
    with open(os.path.join(CARPETA_SALIDA, f"correo_{ayer}.html"), "w", encoding="utf-8") as f:
        f.write(corto)
    with open(RUTA_DATOS_PAGINA if publicar else os.path.join(CARPETA_SALIDA, "reporte_diario.json"),
              "w", encoding="utf-8") as f:
        json.dump(datos_pagina(datos), f, ensure_ascii=False)
    if publicar:
        guardar_en_repo([RUTA_DATOS_PAGINA], f"Reporte diario {ayer}")
    return corto, ruta_pdf, datos


# ---------------------------------------------------------------------------
# PDF y envio
# ---------------------------------------------------------------------------

def generar_pdf(ruta_html, ruta_pdf):
    """Imprime el mismo HTML a PDF con Chrome sin ventana."""
    for chrome in ("google-chrome", "chromium", "chromium-browser",
                   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        try:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                            f"--print-to-pdf={ruta_pdf}", "file://" + os.path.abspath(ruta_html)],
                           check=True, capture_output=True, timeout=180)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("No se encontro Chrome para generar el PDF")


def enviar(asunto, html, texto, destinatarios, adjunto=None):
    """Envia por Gmail (contrasena de aplicacion). Usuario y clave vienen de
    los secretos de GitHub, nunca del repositorio."""
    usuario, clave = os.environ["CORREO_USUARIO"].strip(), os.environ["CORREO_CLAVE"].replace(" ", "").strip()
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = f"Reporte flota C&H <{usuario}>"
    # Con un solo destinatario va a la vista; con varios, en copia oculta (nadie ve la lista).
    msg["To"] = destinatarios[0] if len(destinatarios) == 1 else usuario
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    if adjunto:
        with open(adjunto, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(adjunto))
    ultimo_error = None
    for intento in range(3):
        try:
            if intento % 2 == 0:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
                    s.login(usuario, clave)
                    rechazados = s.send_message(msg, to_addrs=destinatarios)
            else:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
                    s.starttls()
                    s.login(usuario, clave)
                    rechazados = s.send_message(msg, to_addrs=destinatarios)
            # Sin mostrar direcciones (el registro de GitHub es publico).
            print(f"Envio: aceptado por Gmail para {len(destinatarios) - len(rechazados)} de {len(destinatarios)} "
                  f"direcciones; rechazadas al enviar: {len(rechazados)}")
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as e:
            ultimo_error = e
            print(f"Envio: intento {intento + 1} fallo ({type(e).__name__}: {e}); se reintenta.")
            time.sleep(10)
    raise ultimo_error


def html_corto(titulo_txt, cuerpo):
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"></head><body style="margin:0;padding:16px;'
            f'background:#F1F4F2;font-family:{FUENTE};"><table role="presentation" width="100%" style="max-width:640px;'
            f'background:#fff;border-collapse:collapse;"><tr><td style="padding:16px;background:{VERDE};color:#fff;'
            f'font-size:18px;font-weight:bold;">{titulo_txt}</td></tr><tr><td style="padding:16px;font-size:14px;'
            f'color:{TEXTO};line-height:1.5;">{cuerpo}</td></tr></table></body></html>')


def github(ruta):
    r = requests.get(f"https://api.github.com/repos/{REPO}{ruta}", timeout=60, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r


def corrida_de_la_noche(hoy):
    """La corrida de la noche lanzada hoy (hora de Chile): la ultima "Corrida de
    la noche" de diario.yml creada desde las 00:00. None si todavia no parte."""
    desde = datetime(hoy.year, hoy.month, hoy.day, tzinfo=ZONA)
    for run in github("/actions/workflows/diario.yml/runs?per_page=30").json()["workflow_runs"]:
        creada = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if creada >= desde and run.get("display_title") == "Corrida de la noche":
            return run
    return None


def motivo_falla(run):
    """Paso que fallo y ultimas lineas de error del registro."""
    pasos, lineas = [], []
    for job in github(f"/actions/runs/{run['id']}/jobs").json()["jobs"]:
        pasos += [st["name"] for st in job.get("steps", []) if st.get("conclusion") == "failure"]
        try:
            registro = github(f"/actions/jobs/{job['id']}/logs").text.splitlines()
            lineas += [l[29:] for l in registro if "Error" in l or "error" in l][-3:]
        except requests.RequestException:
            pass
    return (", ".join(pasos) or "desconocido"), lineas[-3:]


def leer_estado(hoy):
    try:
        with open(RUTA_ESTADO_CORREO, "r", encoding="utf-8") as f:
            estado = json.load(f)
    except (OSError, ValueError):
        estado = {}
    return estado if estado.get("fecha") == hoy.isoformat() else {"fecha": hoy.isoformat()}


def guardar_estado(estado):
    """Marca del dia (que ya se envio) en el repositorio: evita duplicados
    entre el Worker de Cloudflare, los horarios de respaldo de GitHub y el
    aviso al terminar la corrida. Solo fecha y horas, sin direcciones."""
    with open(RUTA_ESTADO_CORREO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False)
    guardar_en_repo([RUTA_ESTADO_CORREO], f"Correo diario {estado['fecha']}")


# Espera maxima dentro de un trabajo de GitHub (limite 6 h): 5 h 15 min.
ESPERA_MAXIMA_S = 5 * 3600 + 15 * 60


def relanzar_correo():
    """Lanza de nuevo correo.yml (modo diario) para seguir esperando las 07:45."""
    r = requests.post(f"https://api.github.com/repos/{REPO}/actions/workflows/correo.yml/dispatches", timeout=60,
                      headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                               "Accept": "application/vnd.github+json"},
                      json={"ref": "main", "inputs": {"modo": "diario"}})
    r.raise_for_status()
    print("Correo relanzado para seguir esperando.")


def esperar_hasta(hhmm):
    hoy = datetime.now(ZONA)
    h, m = map(int, hhmm.split(":"))
    objetivo = hoy.replace(hour=h, minute=m, second=0, microsecond=0)
    if hoy < objetivo:
        print(f"Esperando hasta las {hhmm} de Chile ({(objetivo - hoy).total_seconds() / 60:.0f} min).")
        time.sleep((objetivo - hoy).total_seconds())


def envio_diario():
    """Decide que mandar hoy (lo lanzan el Worker de Cloudflare a las 07:30 y
    09:00, los horarios de respaldo de GitHub y el fin de la corrida de la
    noche; todos usan la misma marca del dia):
      - la corrida de la noche termino bien -> reporte a las 07:45 (o apenas
        este, si termina despues);
      - fallo -> correo corto con el motivo;
      - sigue sin terminar a las 09:00 -> aviso de atraso (una vez) y despues
        el reporte cuando termine."""
    destinatarios = destinatarios_de("CORREO_DESTINATARIOS")
    if not destinatarios:
        print("Envio diario inactivo: falta el secreto CORREO_DESTINATARIOS (se activa cuando el usuario lo cargue).")
        return
    # Los avisos (falla, atraso) van solo al usuario, no a todos (regla del 21-oct-2026).
    solo_usuario = destinatarios_de("CORREO_PRUEBA") or destinatarios
    ahora = datetime.now(ZONA)
    hoy, ayer = ahora.date(), ahora.date() - timedelta(days=1)
    estado = leer_estado(hoy)
    if estado.get("reporte"):
        print(f"El reporte de hoy ya se envio a las {estado['reporte']}.")
        return
    if ahora.strftime("%H:%M") < HORA_PREPARAR:
        # El correo no se rinde (regla del usuario 22-oct-2026): espera aqui
        # hasta las 07:30, arma el reporte y sale a las 07:45. Un trabajo de
        # GitHub dura como maximo 6 h: si falta mas, espera ~5 h y se relanza.
        h, m = map(int, HORA_PREPARAR.split(":"))
        objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        falta = (objetivo - ahora).total_seconds()
        if falta > ESPERA_MAXIMA_S:
            print(f"Faltan {falta / 3600:.1f} h para las {HORA_PREPARAR}: espera {ESPERA_MAXIMA_S / 3600:.1f} h y se relanza.")
            time.sleep(ESPERA_MAXIMA_S)
            relanzar_correo()
            return
        print(f"Esperando hasta las {HORA_PREPARAR} de Chile ({falta / 60:.0f} min).")
        time.sleep(max(0, falta))
        estado = leer_estado(hoy)
        if estado.get("reporte"):
            print(f"El reporte de hoy ya se envio a las {estado['reporte']}.")
            return
        ahora = datetime.now(ZONA)
        subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], check=False)  # lo ultimo de la noche
    try:
        with open(rh.RUTA_ULTIMA_CORRIDA, "r", encoding="utf-8") as f:
            lista = json.load(f).get("dia_procesado") == ayer.isoformat()
    except (OSError, ValueError):
        lista = False

    if lista:
        try:
            sid, usuario = login()
            html, ruta_pdf, _ = preparar_reporte(sid, usuario, ayer, publicar=True)
        except Exception as e:  # el reporte no se pudo armar: aviso corto
            if not estado.get("falla"):
                enviar(f"Reporte diario de flota – {ayer:%d-%m-%Y}: no se generó",
                       html_corto("El reporte diario de flota no se generó",
                                  f"La corrida de la noche terminó bien, pero el reporte falló al armarse: "
                                  f"<b>{escape(type(e).__name__)}: {escape(str(e))}</b>. Se puede volver a lanzar a "
                                  "mano en GitHub (Actions → Reporte diario de flota por correo)."),
                       f"El reporte diario de flota no se generó: {e}", solo_usuario)
                estado["falla"] = datetime.now(ZONA).strftime("%H:%M")
                guardar_estado(estado)
            raise
        esperar_hasta(HORA_ENVIO)
        enviar(f"Reporte diario de flota – {ayer:%d-%m-%Y}", html,
               f"Reporte diario de flota del {ayer:%d-%m-%Y}. Ver el PDF adjunto.", destinatarios, ruta_pdf)
        estado["reporte"] = datetime.now(ZONA).strftime("%H:%M")
        guardar_estado(estado)
        print(f"Reporte enviado a {len(destinatarios)} destinatarios a las {estado['reporte']}.")
        return

    run = corrida_de_la_noche(hoy)
    if run and run["status"] == "completed" and run["conclusion"] != "success" and not estado.get("falla"):
        paso, lineas = motivo_falla(run)
        detalle = "<br>".join(escape(l) for l in lineas) or "sin detalle en el registro"
        enviar(f"Reporte diario de flota – {ayer:%d-%m-%Y}: no se generó",
               html_corto("El reporte diario de flota no se generó",
                          f"La corrida de la noche falló (paso: <b>{escape(paso)}</b>).<br><br>"
                          f'<span style="font-family:monospace;font-size:12px;">{detalle}</span><br><br>'
                          f'{enlace("Ver la corrida en GitHub", run["html_url"])}. Cuando se vuelva a correr y '
                          "termine bien, el reporte sale solo."),
               f"El reporte diario de flota no se genero: fallo la corrida de la noche ({paso}).", solo_usuario)
        estado["falla"] = datetime.now(ZONA).strftime("%H:%M")
        guardar_estado(estado)
        print(f"Aviso de falla enviado (paso: {paso}).")
    elif ahora.strftime("%H:%M") >= HORA_AVISO_ATRASO and not estado.get("atraso") and not estado.get("falla"):
        situacion = ("todavía está corriendo" if run else "todavía no parte (GitHub la largó tarde)")
        enviar(f"Reporte diario de flota – {ayer:%d-%m-%Y}: viene atrasado",
               html_corto("El reporte diario de flota viene atrasado",
                          f"La corrida de la noche {situacion}. El reporte sale solo apenas termine."),
               f"El reporte diario de flota viene atrasado: la corrida de la noche {situacion}.", solo_usuario)
        estado["atraso"] = datetime.now(ZONA).strftime("%H:%M")
        guardar_estado(estado)
        print("Aviso de atraso enviado.")
    else:
        print("La corrida de la noche no ha terminado: el reporte sale cuando termine.")


def enviar_ahora_a_todos():
    """Envio manual del reporte de ayer a CORREO_DESTINATARIOS (pedido del
    usuario 21-oct-2026). Deja la marca del dia para que el envio automatico
    no lo repita. Despues revisa rebotes en la casilla que envia."""
    destinatarios = destinatarios_de("CORREO_DESTINATARIOS")
    if not destinatarios:
        raise RuntimeError("Falta el secreto CORREO_DESTINATARIOS")
    hoy = datetime.now(ZONA).date()
    ayer = hoy - timedelta(days=1)
    estado = leer_estado(hoy)
    if estado.get("reporte"):
        print(f"El reporte de hoy ya se envio a las {estado['reporte']}: no se repite.")
        return
    sid, usuario = login()
    html, ruta_pdf, _ = preparar_reporte(sid, usuario, ayer, publicar=True)
    inicio = time.time()
    enviar(f"Reporte diario de flota – {ayer:%d-%m-%Y}", html,
           f"Reporte diario de flota del {ayer:%d-%m-%Y}. Detalle completo en el PDF adjunto.", destinatarios, ruta_pdf)
    estado["reporte"] = datetime.now(ZONA).strftime("%H:%M")
    guardar_estado(estado)
    time.sleep(120)
    revisar_rebotes(inicio)


def revisar_rebotes(desde_unix):
    """Solo lectura: cuenta los avisos de rebote (Mail Delivery Subsystem) que
    llegaron a la casilla que envia despues del envio. No muestra direcciones."""
    import email
    import imaplib
    usuario, clave = os.environ["CORREO_USUARIO"].strip(), os.environ["CORREO_CLAVE"].replace(" ", "").strip()
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com") as m:
            m.login(usuario, clave)
            m.select("INBOX", readonly=True)
            _, ids = m.search(None, f'(FROM "mailer-daemon" SINCE "{datetime.now(ZONA):%d-%b-%Y}")')
            rebotes = 0
            for i in ids[0].split():
                _, datos = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
                fecha = email.utils.parsedate_to_datetime(email.message_from_bytes(datos[0][1])["Date"])
                if fecha.timestamp() >= desde_unix - 60:
                    rebotes += 1
            print(f"Rebotes recibidos en los 2 minutos siguientes: {rebotes}")
    except Exception as e:
        print(f"No se pudieron revisar los rebotes ({type(e).__name__}): revisar la casilla a mano.")


def destinatarios_de(variable):
    return [d.strip() for d in re.split(r"[,;\s]+", os.environ.get(variable, "")) if d.strip()]




def medir_atraso(dias=14):
    """Solo lectura: cuanto GPS llega atrasado respecto del fin del dia en hora
    de Chile (00:00 del dia siguiente), para elegir la hora de la corrida de
    la noche. Usa la hora de llegada al servidor ("rt") de cada mensaje."""
    sid, _ = login()
    hoy = datetime.now(ZONA).date()
    cortes = [0, 15, 30, 60, 90, 120, 180, 240, 300, 360, 480]  # minutos despues de las 00:00
    tarde = {c: 0 for c in cortes}
    total = sin_rt = 0
    por_unidad = {}
    peores = []
    unidades = [(u["id"], u["nombre"], "maquina") for u in rh.UNIDADES] + \
               [(v["id"], v["nombre"], "vehiculo") for v in rh.CONFIG.get("vehiculos", [])]
    for uid, nombre, tipo in unidades:
        for k in range(dias, 0, -1):
            dia = hoy - timedelta(days=k)
            fin_dia = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA).timestamp() + 86400
            for m in mensajes_dia(sid, uid, dia):
                total += 1
                if not m.get("rt"):
                    sin_rt += 1
                    continue
                atraso_min = (m["rt"] - fin_dia) / 60
                for c in cortes:
                    if atraso_min > c:
                        tarde[c] += 1
                if atraso_min > 0:
                    clave = (nombre, tipo)
                    por_unidad[clave] = por_unidad.get(clave, 0) + 1
                    peores.append((atraso_min, nombre, dia.isoformat()))
    print(f"ATRASO | {total} mensajes de {len(unidades)} unidades en {dias} dias ({sin_rt} sin hora de llegada)")
    for c in cortes:
        print(f"ATRASO | llegaron mas de {c:>3} min despues de las 00:00 de Chile del dia siguiente: {tarde[c]} "
              f"({tarde[c] / max(total, 1) * 100:.3f} %)")
    for (nombre, tipo), n in sorted(por_unidad.items(), key=lambda x: -x[1])[:15]:
        print(f"ATRASO | unidad {nombre} ({tipo}): {n} mensajes llegados despues de medianoche")
    for a, nombre, dia in sorted(peores, reverse=True)[:10]:
        print(f"ATRASO | peor: {nombre} dia {dia}: llego {a / 60:.1f} h despues de medianoche")


def valor_parametro(mensaje, parametro):
    """Valor de un parametro simple ("io_239", "in1", ...) en un mensaje; None
    si el sensor usa una formula que no se puede leer directo."""
    m = re.fullmatch(r"in(\d+)", parametro or "")
    if m:
        return (mensaje.get("i") or 0) >> (int(m.group(1)) - 1) & 1
    if not re.fullmatch(r"[A-Za-z_][\w]*", parametro or ""):
        return None
    return (mensaje.get("p") or {}).get(parametro)


def horas_motor(mensajes, parametro):
    """Horas con el motor encendido segun el sensor (intervalos de hasta 15
    min entre mensajes). None si el parametro no viene en los mensajes."""
    segundos, leidos = 0.0, 0
    for a, b in zip(mensajes, mensajes[1:]):
        v = valor_parametro(a, parametro)
        if v is None:
            continue
        leidos += 1
        dt = b["t"] - a["t"]
        if v and 0 < dt <= 900:
            segundos += dt
    return segundos / 3600 if leidos else None


def revisar_sensores(dias=7):
    """Solo lectura: por maquina, sensor de encendido, horometro (contador de
    horas de motor de Wialon), ultimo dato y horas de motor de los 7 dias.
    Deja salida_correo/sensores.json."""
    sid, _ = login()
    hoy = datetime.now(ZONA).date()
    salida = []
    for u in sorted(rh.UNIDADES, key=lambda u: rh.orden_flota(u["nombre"])):
        item = wialon(sid, "core/search_item", {"id": u["id"], "flags": 0x1 | 0x400 | 0x1000 | 0x2000}).get("item", {})
        sensores = list((item.get("sens") or {}).values())
        encendido = next((x for x in sensores if x.get("t") in ("engine operation", "ignition")), None)
        horometro_sensor = next((x for x in sensores if x.get("t") in ("engine hours", "absolute engine hours")), None)
        horas7 = None
        if encendido:
            total = 0.0
            leido = False
            for k in range(dias, 0, -1):
                h = horas_motor(mensajes_dia(sid, u["id"], hoy - timedelta(days=k)), encendido.get("p"))
                if h is not None:
                    total += h
                    leido = True
            horas7 = round(total, 1) if leido else None
        ultimo = (item.get("lmsg") or {}).get("t")
        salida.append({"maquina": u["nombre"], "labor": rh.labor_de(u),
                       "sensor_encendido": encendido.get("n") if encendido else None,
                       "parametro_encendido": encendido.get("p") if encendido else None,
                       "sensor_horometro": horometro_sensor.get("n") if horometro_sensor else None,
                       "horometro_h": round(item["cneh"], 1) if item.get("cneh") is not None else None,
                       "ultimo_dato": datetime.fromtimestamp(ultimo, ZONA).strftime("%Y-%m-%d %H:%M") if ultimo else None,
                       "horas_motor_7_dias": horas7,
                       "tipos_sensores": sorted({x.get("t") for x in sensores})})
        print(f"SENSORES | {u['nombre']} | encendido: {salida[-1]['sensor_encendido']} ({salida[-1]['parametro_encendido']}) | "
              f"horometro: {salida[-1]['horometro_h']} | 7 dias: {horas7} | tipos: {salida[-1]['tipos_sensores']}")
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    with open(os.path.join(CARPETA_SALIDA, "sensores.json"), "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)


def main():
    modo = os.environ.get("MODO_CORREO", "vista_previa").strip()
    if modo == "sensores":
        return revisar_sensores()
    if modo == "atraso":
        return medir_atraso()
    if modo == "diario":
        return envio_diario()
    if modo == "todos":
        return enviar_ahora_a_todos()
    hoy = datetime.now(ZONA).date()
    ayer = (date.fromisoformat(os.environ["FECHA_REPORTE"].strip()) if os.environ.get("FECHA_REPORTE", "").strip()
            else hoy - timedelta(days=1))
    print(f"Reporte diario de flota del {ayer} (modo {modo}).")
    sid, usuario = login()
    inicio = time.time()
    # En la prueba se publican los datos de la pagina, para que "Ver detalle" funcione.
    html, ruta_pdf, datos = preparar_reporte(sid, usuario, ayer, publicar=(modo == "prueba"))
    print(f"Reporte generado en {time.time() - inicio:.0f} s: correo corto, {ruta_pdf} y datos de la pagina.")
    for v in datos["camionetas"] + datos["camiones"]:
        d = v["dias"][ayer.isoformat()]
        print(f"Vehiculo | {v['nombre']} | {d['km']:.1f} km | "
              + (" -> ".join(l["nombre"] for l in d["lugares"]) if d["se_movio"]
                 else f"no se movio, en {d['donde_quedo'][0]} (posicion: {d['fuente_posicion']})"))
    for m in datos["maquinas"]:
        if any(x["sin_geocerca"] for x in m["dias"].values()):
            r = m["rendimiento"]
            print(f"Rendimiento | {m['nombre']} | {r[0] and round(r[0], 2)} ha/h ({r[1]}) | "
                  f"sin geocerca 7 dias: {sum(x['horas_sin'] for x in m['dias'].values()):.1f} h, "
                  f"~{sum(x['ha_sin'] for x in m['dias'].values()):.1f} ha (GPS: "
                  f"{sum(y['ha'] for x in m['dias'].values() for y in x['sin_geocerca']):.1f} ha)")

    if modo == "prueba":
        if not destinatarios_de("CORREO_PRUEBA"):
            raise RuntimeError("Falta el secreto CORREO_PRUEBA")
        asunto = f"Reporte diario de flota – {ayer:%d-%m-%Y} (PRUEBA)"
        enviar(asunto, html, f"Reporte diario de flota del {ayer:%d-%m-%Y}. Detalle completo en el PDF adjunto.",
               destinatarios_de("CORREO_PRUEBA"), ruta_pdf)
        print("Correo de prueba enviado.")


if __name__ == "__main__":
    sys.exit(main())
