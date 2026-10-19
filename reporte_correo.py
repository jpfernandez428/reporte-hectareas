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
VEHICULOS = rh.CONFIG.get("vehiculos", [])
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
    """Lugares en el orden en que paso: CYH, campos de las geocercas donde
    estuvo al menos MINUTOS_EN_GEOCERCA, y la comuna de cada parada de al menos
    MINUTOS_PARADA_FUERA fuera de geocercas. [{"nombre", "mapa"}]"""
    tramos = []  # [lugar, t_inicio, t_fin, k_inicio, k_fin]
    for k, p in enumerate(puntos):
        lugar = lugar_del_punto(p["punto"], indice, patio)
        if tramos and tramos[-1][0] == lugar:
            tramos[-1][2], tramos[-1][4] = p["t"], k
        else:
            tramos.append([lugar, p["t"], p["t"], k, k])
    lugares = []

    def agregar(nombre, mapa=None):
        if nombre and (not lugares or lugares[-1]["nombre"] != nombre):
            lugares.append({"nombre": nombre, "mapa": mapa})

    for lugar, t0, t1, k0, k1 in tramos:
        if lugar == "CYH":
            agregar("CYH")
        elif lugar:
            if t1 - t0 >= MINUTOS_EN_GEOCERCA * 60:
                agregar(nombre_campo(lugar))
        else:
            k = k0
            while k <= k1:
                j = k
                while j + 1 <= k1 and distancia_m(puntos[k]["punto"], puntos[j + 1]["punto"]) < 150:
                    j += 1
                if puntos[j]["t"] - puntos[k]["t"] >= MINUTOS_PARADA_FUERA * 60:
                    agregar(*nombre_lugar(puntos[k]["punto"], indice, patio, usuario))
                k = j + 1
    return lugares


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
        if r["labor"] == rh.LABOR_CON_PASADAS:
            continue
        k = (r["cuartel"], r["labor"])
        acumulado[k] = acumulado.get(k, 0) + r["area_trabajada_ha"]
        if k not in completos and acumulado[k] >= rh.UMBRAL_CIERRE_PORCENTAJE * area[r["cuartel"]] - 1e-6:
            completos[k] = r["fecha"]
    return completos




def datos_reporte(sid, usuario, ayer):
    dias = [ayer - timedelta(days=k) for k in range(DIAS_RESUMEN - 1, -1, -1)]
    fechas = [d.isoformat() for d in dias]
    with open(rh.RUTA_FLOTA, "r", encoding="utf-8") as f:
        flota = json.load(f)
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
            sin = d.get("sin_geocerca", []) or []
            fila = {"ha": ha.get((nombre, fecha), 0.0), "horas_geocercas": horas_geo,
                    "horas_sin": sum(s["horas"] for s in sin), "sin_geocerca": sin,
                    "fin_lugar": (d.get("fin") or {}).get("lugar")}
            fila["horas"] = sum(horas_geo.values()) + fila["horas_sin"]
            fila["trabajo"] = (fila["ha"] > 0 or bool(sin)
                               or any(h >= rh.HORAS_MINIMAS_ALERTA for h in horas_geo.values()))
            fila["se_movio"] = fila["trabajo"] or bool(horas_geo)
            filas[fecha] = fila
        maquinas.append({"nombre": nombre, "labor": rh.labor_de(unidad),
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
            fila["lugares"] = recorrido_vehiculo(puntos, indice, patio, usuario) if fila["se_movio"] else []
            if fecha == fechas[-1] and not fila["se_movio"]:
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
    for (cuartel, labor), fecha in completos.items():
        if fecha in fechas and nombre_campo(cuartel) in campos:
            campos[nombre_campo(cuartel)]["terminados"].add((cuartel, labor))
    for cuartel, info in avance.items():
        cierres = ((info.get("labores") or {}).get(rh.LABOR_CON_PASADAS) or {}).get("cierres") or []
        if any(f in fechas for f in cierres) and nombre_campo(cuartel) in campos:
            campos[nombre_campo(cuartel)]["terminados"].add((cuartel, rh.LABOR_CON_PASADAS))

    return {"ayer": ayer, "dias": dias, "flota": flota, "maquinas": maquinas,
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


def fecha_larga(d):
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
             "octubre", "noviembre", "diciembre"]
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]} de {d.year}"


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




def lugares_html(lugares, separador=" · "):
    return separador.join(enlace(escape(l["nombre"]), l["mapa"]) if l.get("mapa") else escape(l["nombre"])
                          for l in lugares)


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
        f'</td></tr>')

    # 2. Resumen de ayer
    hoy_m = [(m, m["dias"][fa]) for m in maquinas]
    trabajaron = [x for x in hoy_m if x[1]["trabajo"]]
    ha_ayer = sum(d["ha"] for _, d in hoy_m)
    horas_ayer = sum(d["horas"] for _, d in hoy_m)
    movidas = sum(1 for v in camionetas if v["dias"][fa]["se_movio"])
    filas_html.append(titulo("Resumen de ayer"))
    filas_html.append(indicadores([(f"{len(trabajaron)} de {len(maquinas)}", "máquinas trabajaron"),
                                   (num(ha_ayer, 2), "hectáreas"), (num(horas_ayer), "horas de las máquinas")]))
    cajas = [(f"{num(km(camionetas, fa), 0)} km", f"camionetas ({movidas} de {len(camionetas)} se movieron)")]
    for c in camiones:
        cajas.append((f"{num(c['dias'][fa]['km'], 0)} km", "camión"))
    filas_html.append(indicadores(cajas))

    # 3. Alertas
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
                           f'(~{num(s["ha"])} ha aprox.) en {coords} · {enlace("ver mapa", s["mapa"], ROJO)}')
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
    filas_html.append(titulo("Máquinas · ayer"))
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
        filas.append([escape(m["nombre"]), escape(m["labor"]), donde or "–", num(d["ha"], 2) if d["ha"] else "–",
                      num(d["horas"]) if d["horas"] else "–"])
    if any(not isinstance(f, str) for f in filas):
        filas_html.append(tabla(["Máquina", "Labor", "Dónde estuvo", "Ha", "Horas"], filas,
                                ["l", "l", "l", "r", "r"], ["Total", "", "", num(ha_ayer, 2), num(horas_ayer)],
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
    filas_html.append(titulo("Camionetas · ayer"))
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
        filas_html.append(titulo(f"Camión · ayer <span style=\"font-weight:normal;font-size:13px;color:{TEXTO_SUAVE};\">"
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
    filas_html.append(indicadores([(num(tot_ha, 2), "hectáreas"), (num(tot_h), "horas de las máquinas")]))
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
        filas.append([escape(m["nombre"]), escape(donde) or "–", str(sum(1 for x in ds if x["trabajo"])),
                      num(sum(x["ha"] for x in ds), 2), horas_txt])
    filas_html.append(tabla(["Máquina", "Dónde estuvo", "Días", "Ha", "Horas"], filas,
                            ["l", "l", "r", "r", "r"], None, estilos))

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
    msg["To"] = usuario
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    if adjunto:
        with open(adjunto, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(adjunto))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(usuario, clave)
        s.send_message(msg, to_addrs=destinatarios)


def destinatarios_de(variable):
    return [d.strip() for d in re.split(r"[,;\s]+", os.environ.get(variable, "")) if d.strip()]




def main():
    modo = os.environ.get("MODO_CORREO", "vista_previa").strip()
    hoy = datetime.now(ZONA).date()
    ayer = (date.fromisoformat(os.environ["FECHA_REPORTE"].strip()) if os.environ.get("FECHA_REPORTE", "").strip()
            else hoy - timedelta(days=1))
    print(f"Reporte diario de flota del {ayer} (modo {modo}).")
    sid, usuario = login()
    inicio = time.time()
    datos = datos_reporte(sid, usuario, ayer)
    print(f"Datos listos en {time.time() - inicio:.0f} s.")
    for v in datos["camionetas"] + datos["camiones"]:
        d = v["dias"][ayer.isoformat()]
        print(f"Vehiculo | {v['nombre']} | {d['km']:.1f} km | "
              + (" -> ".join(l["nombre"] for l in d["lugares"]) if d["se_movio"]
                 else f"no se movio, en {d['donde_quedo'][0]} (posicion: {d['fuente_posicion']})"))

    if modo == "vista_previa":
        for (lon, lat), texto in sorted(direccion.__defaults__[0].items()):
            print(f"Direccion | {lat:.3f}, {lon:.3f} | {texto} -> {localidad(texto)}")

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    html = armar_html(datos)
    ruta_html = os.path.join(CARPETA_SALIDA, f"reporte_flota_{ayer}.html")
    ruta_pdf = os.path.join(CARPETA_SALIDA, f"Reporte_flota_{ayer}.pdf")
    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(html)
    generar_pdf(ruta_html, ruta_pdf)
    print(f"Reporte generado: {ruta_html} y {ruta_pdf}")

    if modo == "prueba":
        asunto = f"Reporte diario de flota – {ayer:%d-%m-%Y} (PRUEBA)"
        enviar(asunto, html, f"Reporte diario de flota del {ayer:%d-%m-%Y}. Ver el PDF adjunto.",
               destinatarios_de("CORREO_PRUEBA"), ruta_pdf)
        print("Correo de prueba enviado.")


if __name__ == "__main__":
    sys.exit(main())
