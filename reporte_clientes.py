"""
reporte_clientes.py

Reporte diario a los clientes: un correo por campo con trabajo el dia anterior
(encargo del usuario del 10-nov-2026; reglas en CLAUDE.md, "Reporte diario a
clientes (nov-2026)").

  - Para: los correos de los contactos del campo (pestana "Correos clientes" de
    la app / planilla; viven SOLO en Cloudflare D1 y se piden al Worker con la
    clave secreta CLAVE_CLIENTES). CC visible: jpfernandez@cosechamecanizada.cl.
  - Contenido: cliente, fecha, labor; totales (maquinas, horas encendido, ha
    aprox.); por maquina: operador, inicio y termino del motor (sensor de
    encendido de Wialon, SOLO LECTURA), horas encendido, eficiencia y ha; por
    cuartel: superficie, ayer por maquina, ayer, acumulado de la temporada y
    avance; trabajo sin geocerca solo como total aproximado.
  - Mismo contenido en PDF adjunto. Logo de CYH arriba a la izquierda.
  - MODO PRUEBA por defecto (config.json -> correo_clientes_envio_real: false):
    todos los reportes van SOLO a correo_clientes_prueba, con "[PRUEBA]" y el
    cliente al que le habria llegado.

Nunca se escriben los correos de los clientes en el repositorio ni en los
registros de GitHub (el repositorio es publico).
"""

import base64
import json
import math
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape

import requests

import reporte_hectareas as rh
import reporte_correo as rc
import reporte_v2 as rv2

ZONA = rh.ZONA_HORARIA
CC_FIJO = rh.CONFIG.get("correo_clientes_cc", "jpfernandez@cosechamecanizada.cl")
CORREO_PRUEBA_CLIENTES = rh.CONFIG.get("correo_clientes_prueba", "jpfernandez@cosechamecanizada.cl")
ENVIO_REAL = bool(rh.CONFIG.get("correo_clientes_envio_real", False))
WORKER = re.sub(r"/confirmar/?$", "", rh.CONFIG.get("url_confirmaciones", "https://disparador-reporte.dawn-band-fd6c.workers.dev"))
RUTA_LOGO = os.path.join(rh.CARPETA_BASE, "docs", "Logo_CYH.png")
CARPETA_SALIDA = os.path.join(rh.CARPETA_BASE, "salida_correo", "clientes")

# Eficiencia: horas encendido / (termino - inicio - almuerzo). El almuerzo (1 h) se
# resta solo si la jornada es de 5 h o mas. Maximo 100 %.
HORAS_ALMUERZO = rh.CONFIG.get("horas_almuerzo_cliente", 1.0)
JORNADA_CON_ALMUERZO_H = rh.CONFIG.get("jornada_con_almuerzo_h", 5.0)
# Contador de motor dudoso: mas de esto encendido sin parar.
MAX_HORAS_SEGUIDAS = rh.CONFIG.get("max_horas_motor_seguidas", 14.0)
HUECO_MAXIMO_S = 900   # entre dos mensajes; mas que esto no cuenta como encendido
# Zona del campo del cliente (pedido del usuario 11-nov-2026): inicio, termino y horas de
# motor se miden solo mientras la maquina esta en sus cuarteles o a menos de esta distancia
# del borde (cabeceras, caminos internos, donde se estaciona); el trabajo sin geocerca
# asignado a ese campo suma una zona de este radio alrededor de sus pasadas.
MARGEN_CAMPO_M = rh.CONFIG.get("margen_zona_campo_m", 150)
RADIO_SIN_GEOCERCA_M = 300

NEGRO = "#161616"
GRIS = "#5F6368"
GRIS_FILA = "#F5F5F5"
BORDE = "#DDDDDD"
VERDE_OK = "#1F6B34"
VERDE_OK_F = "#E3F2E6"
AMARILLO_F = "#FFF4CC"
FUENTE = "Arial, Helvetica, sans-serif"


def clave(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def num(v, dec=2):
    return rc.num(v or 0, dec)


def fecha_trabajada(d):
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[d.weekday()]} {d:%d-%m-%Y}"


def hora_txt(t):
    return datetime.fromtimestamp(t, ZONA).strftime("%H:%M") if t else "–"


def horas_txt(h):
    if h is None:
        return "–"
    hh, mm = int(h), int(round((h - int(h)) * 60))
    if mm == 60:
        hh, mm = hh + 1, 0
    return f"{hh}:{mm:02d}"


# ---------------------------------------------------------------------------
# Datos privados (Cloudflare) y publicos (repositorio)
# ---------------------------------------------------------------------------

def leer_clientes():
    """Clientes y contactos desde el Worker (clave secreta). Nunca se imprimen."""
    secreto = os.environ.get("CLAVE_CLIENTES", "").strip()
    if not secreto:
        raise RuntimeError("Falta el secreto CLAVE_CLIENTES")
    r = requests.get(WORKER + "/clientes", headers={"Authorization": "Bearer " + secreto}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"El Worker no entrego los clientes (respuesta {r.status_code})")
    return r.json().get("clientes", [])


def operacion_actual():
    """Operador de cada maquina segun la pagina Operacion (D1 al momento; si no, lo publicado)."""
    try:
        r = requests.get(WORKER + "/estado", timeout=20)
        d = r.json()
        if d.get("d1") and d.get("maquinas"):
            return d["maquinas"]
    except Exception as e:
        print(f"Operacion: sin Cloudflare ({type(e).__name__}); se usa operacion.json.")
    with open(os.path.join(rh.CARPETA_DATOS, "operacion.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("maquinas", {})


def leer_json(nombre, defecto):
    ruta = os.path.join(rh.CARPETA_DATOS, nombre)
    if not os.path.exists(ruta):
        return defecto
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def campos_wialon_de(nombre):
    """Claves de los campos de Wialon que corresponden a un nombre de Operacion /
    cliente: el mismo nombre y sus equivalencias (config.json -> equivalencias_campos)."""
    salida = {clave(nombre)}
    for k, v in rh.CONFIG.get("equivalencias_campos", {}).items():
        if clave(k) == clave(nombre):
            salida |= {clave(x) for x in v}
    return salida


# ---------------------------------------------------------------------------
# Motor (sensor de encendido de Wialon, solo lectura)
# ---------------------------------------------------------------------------

def sensor_encendido(sid, unit_id):
    item = rc.wialon(sid, "core/search_item", {"id": unit_id, "flags": 0x1 | 0x1000}).get("item", {})
    sensores = list((item.get("sens") or {}).values())
    s = next((x for x in sensores if x.get("t") in ("engine operation", "ignition")), None)
    return s.get("p") if s else None


def _m_por_grado(lat):
    return 111320.0, 111320.0 * math.cos(math.radians(lat))


def _dentro(x, y, pol):
    c = False
    for i in range(len(pol)):
        x1, y1 = pol[i]; x2, y2 = pol[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _dist_borde_m(lon, lat, pol):
    my, mx = _m_por_grado(lat)
    mejor = float("inf")
    for i in range(len(pol)):
        ax, ay = (pol[i - 1][0] - lon) * mx, (pol[i - 1][1] - lat) * my
        bx, by = (pol[i][0] - lon) * mx, (pol[i][1] - lat) * my
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L)) if L else 0.0
        mejor = min(mejor, math.hypot(ax + t * dx, ay + t * dy))
    return mejor


class ZonaCampo:
    """Cuarteles del campo (geocercas.json) + MARGEN_CAMPO_M, y circulos alrededor de
    las pasadas del trabajo sin geocerca asignado al campo ese dia."""

    def __init__(self, contornos, puntos_sin):
        self.pols = []
        for pol in contornos:
            if len(pol) < 3:
                continue
            lat = sum(p[1] for p in pol) / len(pol)
            my, mx = _m_por_grado(lat)
            dlon, dlat = MARGEN_CAMPO_M / mx, MARGEN_CAMPO_M / my
            caja = (min(p[0] for p in pol) - dlon, max(p[0] for p in pol) + dlon,
                    min(p[1] for p in pol) - dlat, max(p[1] for p in pol) + dlat)
            self.pols.append((caja, pol))
        self.puntos = puntos_sin

    def vacia(self):
        return not self.pols and not self.puntos

    def contiene(self, lon, lat):
        for (x0, x1, y0, y1), pol in self.pols:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and (_dentro(lon, lat, pol) or _dist_borde_m(lon, lat, pol) <= MARGEN_CAMPO_M):
                return True
        my, mx = _m_por_grado(lat)
        return any(math.hypot((lon - x) * mx, (lat - y) * my) <= RADIO_SIN_GEOCERCA_M for x, y in self.puntos)


def _contar_motor(vals):
    """vals: [(t, encendido, cuenta)] -> {inicio, termino, horas, seguidas_max}; solo
    suman los tramos que parten en un mensaje con cuenta=True."""
    segundos, seguidas, seguidas_max = 0.0, 0.0, 0.0
    inicio = termino = None
    for i, (t, v, cuenta) in enumerate(vals):
        if v and cuenta:
            inicio = inicio or t
            termino = t
            if i + 1 < len(vals):
                dt = vals[i + 1][0] - t
                if 0 < dt <= HUECO_MAXIMO_S:
                    segundos += dt
                    seguidas += dt
                    termino = vals[i + 1][0]   # el apagado es el mensaje siguiente
                    seguidas_max = max(seguidas_max, seguidas)
                    continue
        seguidas = 0.0
    if inicio is None:
        return None
    return {"inicio": inicio, "termino": termino, "horas": segundos / 3600, "seguidas_max": seguidas_max / 3600}


_MSGS = {}


def motor_del_dia(sid, unit_id, dia, zona=None):
    """{inicio, termino (unix), horas, seguidas_max} con el motor encendido ese dia
    (hora de Chile); con zona, solo mientras la maquina esta dentro de ella. None si
    la maquina no tiene sensor o no hay datos."""
    if unit_id not in _MSGS:
        p = sensor_encendido(sid, unit_id)
        msgs = rc.mensajes_dia(sid, unit_id, dia) if p else []
        _MSGS[unit_id] = [(m["t"], rc.valor_parametro(m, p), m["pos"]["x"], m["pos"]["y"]) for m in msgs] if p else None
    datos = _MSGS[unit_id]
    if not datos:
        return None
    vals = [(t, v, True if zona is None else zona.contiene(x, y)) for t, v, x, y in datos if v is not None]
    return _contar_motor(vals) if vals else None


def eficiencia(m):
    if not m or not m["inicio"] or not m["termino"] or not m["horas"]:
        return None
    jornada = (m["termino"] - m["inicio"]) / 3600
    if jornada >= JORNADA_CON_ALMUERZO_H:
        jornada -= HORAS_ALMUERZO
    return min(1.0, m["horas"] / jornada) if jornada > 0 else None


# ---------------------------------------------------------------------------
# Armado de los reportes del dia
# ---------------------------------------------------------------------------

def reportes_del_dia(dia, sid=None, solo_campo=None):
    """Lista de reportes (uno por campo con trabajo) y alertas para el correo interno."""
    fecha = dia.isoformat()
    historico = leer_json("historico.json", [])
    sin_geo = [t for t in leer_json("sin_geocerca.json", {}).get("trabajos", [])
               if t.get("fecha") == fecha and t.get("estado") != "resuelto" and t.get("campo") and (t.get("ha") or 0) > 0]
    flota = {m["nombre"]: m for m in leer_json("flota.json", {}).get("maquinas", [])}
    avance = leer_json("avance_cuarteles.json", {}).get("cuarteles", {})
    clientes = leer_clientes()
    oper = operacion_actual()
    por_clave = {}
    for c in clientes:
        for k in campos_wialon_de(c["campo"]):
            por_clave.setdefault(k, c)

    def destino(nombre_campo):
        """(nombre del reporte, cliente o None) para un campo de Wialon o de Operacion."""
        for k in campos_wialon_de(nombre_campo):
            if k in por_clave:
                return por_clave[k]["campo"], por_clave[k]
        return nombre_campo, None

    reportes = {}

    def rep(nombre_campo):
        nombre, cli = destino(nombre_campo)
        r = reportes.setdefault(clave(nombre), {"campo": nombre, "cliente": cli, "maquinas": {}, "cuarteles": {},
                                                 "sin_geocerca": 0.0, "labores": set()})
        return r

    for x in historico:
        if x["fecha"] != fecha or not (x.get("area_trabajada_ha") or 0) > 0:
            continue
        r = rep(rh.campo_de_cuartel(x["cuartel"]))
        labor = rv2.labor_visible(x["labor"], fecha)
        r["labores"].add(labor)
        m = r["maquinas"].setdefault(x["maquina"], {"ha": 0.0, "ha_sin": 0.0})
        m["ha"] += x["area_trabajada_ha"]
        c = r["cuarteles"].setdefault((x["cuartel"], labor), {"cuartel": x["cuartel"], "labor": labor, "labor_hist": x["labor"],
                                                                "area": x.get("area_total_ha") or 0, "ayer": {}})
        c["ayer"][x["maquina"]] = c["ayer"].get(x["maquina"], 0) + x["area_trabajada_ha"]
    for t in sin_geo:
        r = rep(t["campo"])
        r["labores"].add(rv2.labor_visible(t.get("labor") or "", fecha))
        m = r["maquinas"].setdefault(t["maquina"], {"ha": 0.0, "ha_sin": 0.0})
        m["ha_sin"] += t["ha"]
        m["horas_sin_gps"] = m.get("horas_sin_gps", 0) + (t.get("horas") or 0)
        r["sin_geocerca"] += t["ha"]

    if solo_campo:
        reportes = {k: v for k, v in reportes.items() if k in campos_wialon_de(solo_campo) or clave(v["campo"]) == clave(solo_campo)}

    # Acumulado de la temporada por cuartel y labor (todas las maquinas, sin repetir:
    # el historial acredita solo lo que supera el maximo ya alcanzado; con el 95 %
    # se acredita el area total).
    for r in reportes.values():
        for (cuartel, labor), c in r["cuarteles"].items():
            if labor == rh.LABOR_CON_PASADAS:
                a = (avance.get(cuartel, {}).get("labores", {}).get(labor) or {})
                c["acumulado"], c["pct"] = a.get("trabajado_ha", 0), (a.get("porcentaje", 0) or 0) / 100
            else:
                desde = rv2.temporada_inicio(c["labor_hist"], dia).isoformat()
                c["acumulado"] = sum(x["area_trabajada_ha"] for x in historico if x["cuartel"] == cuartel and
                                     rv2.labor_visible(x["labor"], x["fecha"]) == labor and desde <= x["fecha"] <= fecha)
                c["pct"] = c["acumulado"] / c["area"] if c["area"] else 0
            c["terminado"] = c["pct"] >= rh.UMBRAL_CIERRE_PORCENTAJE
            if c["terminado"] and labor != rh.LABOR_CON_PASADAS:
                c["acumulado"], c["pct"] = c["area"], 1.0

    # Motor, operador y alertas por maquina.
    unidades = {u["nombre"]: u for u in rh.UNIDADES}
    alertas = []
    cache_motor = {}
    contornos = leer_json("geocercas.json", {})
    for r in reportes.values():
        claves = campos_wialon_de(r["campo"]) | {clave(rh.campo_de_cuartel(c)) for c, _ in r["cuarteles"]}
        pols = [g.get("contorno") or [] for n, g in contornos.items()
                if clave(rh.campo_de_cuartel(n)) in claves or n in {c for c, _ in r["cuarteles"]}]
        r["zona_por_maquina"] = {}
        for nombre in r["maquinas"]:
            pts = []
            for t in sin_geo:
                if t["maquina"] == nombre and clave(destino(t["campo"])[0]) == clave(r["campo"]):
                    mu = t.get("muestras") or []
                    pts += [(float(x), float(y)) for x, y in mu] or [(float(t["lon"]), float(t["lat"]))]
            r["zona_por_maquina"][nombre] = ZonaCampo(pols, pts)
    for r in reportes.values():
        for nombre, m in r["maquinas"].items():
            u = unidades.get(nombre)
            zona = r["zona_por_maquina"][nombre]
            try:
                if nombre not in cache_motor:
                    cache_motor[nombre] = motor_del_dia(sid, u["id"], dia) if (sid and u) else None
                mot_dia = cache_motor[nombre]
                # Inicio, termino y horas solo dentro del campo del cliente; sin zona (campo
                # sin cuarteles ni pasadas), el dia completo.
                mot = (motor_del_dia(sid, u["id"], dia, zona) if (sid and u and not zona.vacia()) else mot_dia)
            except Exception as e:
                print(f"Motor | {nombre} | no se pudo leer ({type(e).__name__})")
                mot_dia = mot = cache_motor[nombre] = None
            m["motor_dia"] = mot_dia
            dia_flota = next((d for d in (flota.get(nombre, {}).get("dias") or []) if d.get("fecha") == fecha), {})
            gps_h = sum((dia_flota.get("horas_geocercas") or {}).values()) + m.get("horas_sin_gps", 0)
            razones = []
            # Contador dudoso: se revisa con el dia completo de la maquina.
            if (m["ha"] + m["ha_sin"]) > 0 and (not mot_dia or not mot_dia["horas"]):
                razones.append("hizo hectáreas pero Wialon marca 0 horas de motor")
            if mot_dia and mot_dia["horas"] and gps_h > mot_dia["horas"] + 0.05:
                razones.append(f"horas en movimiento por GPS ({horas_txt(gps_h)}) mayores que las de motor ({horas_txt(mot_dia['horas'])})")
            if mot_dia and mot_dia["seguidas_max"] > MAX_HORAS_SEGUIDAS:
                razones.append(f"motor encendido {horas_txt(mot_dia['seguidas_max'])} seguidas (más de {MAX_HORAS_SEGUIDAS:.0f} h)")
            m.update({"motor": mot, "gps_h": gps_h, "dudoso": razones, "eficiencia": None if razones else eficiencia(mot),
                      "operador": ((oper.get(nombre) or {}).get("operador") or "").strip(),
                      "campo_operacion": ((oper.get(nombre) or {}).get("campo") or "").strip()})
            for z in razones:
                alertas.append({"tipo": "motor", "maquina": nombre, "campo": r["campo"], "texto": z})
            if not m["operador"]:
                alertas.append({"tipo": "operador", "maquina": nombre, "campo": r["campo"],
                                "texto": "trabajó sin operador anotado en Operación (el reporte salió con el operador en blanco)"})
            co = m["campo_operacion"]
            if co and not rc_es_taller(co) and not (campos_wialon_de(co) & (campos_wialon_de(r["campo"]))):
                alertas.append({"tipo": "campo", "maquina": nombre, "campo": r["campo"],
                                "texto": f"trabajó en {r['campo']} pero Operación dice {co}"})
    for r in reportes.values():
        r["correos"] = [c for c in ([r["cliente"].get("correo1"), r["cliente"].get("correo2")] if r["cliente"] else []) if c]
        if not r["correos"]:
            alertas.append({"tipo": "sin_correo", "maquina": "", "campo": r["campo"],
                            "texto": "tuvo trabajo y no tiene correo del cliente: no se le mandó reporte"})
    return sorted(reportes.values(), key=lambda r: r["campo"].lower()), alertas


def orden_natural(t):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", t)]


def rc_es_taller(c):
    return clave(c) in ("taller", "cyh", "tallercyh")


# ---------------------------------------------------------------------------
# HTML (estilos en linea: Gmail, Outlook y celular) y PDF
# ---------------------------------------------------------------------------

def celda(texto, alinear="left", negrita=False, color=NEGRO, fondo="", borde=True, tam=12, ancho=""):
    return (f'<td{f" width={chr(34)}{ancho}{chr(34)}" if ancho else ""} style="padding:6px 5px;font-family:{FUENTE};font-size:{tam}px;{"white-space:nowrap;" if alinear != "left" else ""}'
            f'color:{color};text-align:{alinear};{"font-weight:bold;" if negrita else ""}{f"background:{fondo};" if fondo else ""}'
            f'{f"border-bottom:1px solid {BORDE};" if borde else ""}vertical-align:top;">{texto}</td>')


def tabla(encabezados, filas, alinear, total=None):
    th = "".join(f'<th style="padding:6px 5px;font-family:{FUENTE};font-size:11px;color:#ffffff;background:{NEGRO};'
                 f'text-align:{a};font-weight:bold;">{h}</th>' for h, a in zip(encabezados, alinear))
    cuerpo = ""
    for i, f in enumerate(filas):
        fondo = f.get("fondo") or (GRIS_FILA if i % 2 else "#ffffff")
        cuerpo += "<tr>" + "".join(celda(v, a, fondo=fondo) for v, a in zip(f["celdas"], alinear)) + "</tr>"
    if total:
        cuerpo += "<tr>" + "".join(celda(v, a, negrita=True, fondo="#EAEAEA") for v, a in zip(total, alinear)) + "</tr>"
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'border:1px solid {BORDE};">{"<tr>" + th + "</tr>"}{cuerpo}</table>')


def armar_html(r, dia, logo_src, prueba=None):
    cli = r["cliente"] or {}
    labores = " · ".join(sorted(r["labores"])) or "–"
    maquinas = sorted(r["maquinas"].items(), key=lambda x: rh.orden_flota(x[0]))
    ha_total = sum(m["ha"] + m["ha_sin"] for _, m in maquinas)
    horas_total, aprox = 0.0, False
    filas_m = []
    for nombre, m in maquinas:
        mot = m["motor"]
        if m["dudoso"]:
            h, aprox = m["gps_h"], True
            filas_m.append({"celdas": [escape(nombre), escape(m["operador"]) or "–", "–", "–",
                                       f'{horas_txt(h)} <span style="color:{GRIS};font-size:11px;">aprox. (GPS)</span>', "–",
                                       num(m["ha"] + m["ha_sin"])]})
        else:
            h = mot["horas"] if mot else 0
            ef = m["eficiencia"]
            filas_m.append({"celdas": [escape(nombre), escape(m["operador"]) or "–", hora_txt(mot and mot["inicio"]),
                                       hora_txt(mot and mot["termino"]), horas_txt(h),
                                       f"{rc.num(ef * 100, 0)} %" if ef is not None else "–", num(m["ha"] + m["ha_sin"])]})
        horas_total += h or 0
    filas_c = []
    sum_area = sum_ayer = sum_acum = 0.0
    for (cuartel, labor), c in sorted(r["cuarteles"].items(), key=lambda x: orden_natural(x[0][0]) + [x[0][1]]):
        ayer = sum(c["ayer"].values())
        por_maq = "<br>".join(f"{escape(k)}: {num(v)}" for k, v in sorted(c["ayer"].items(), key=lambda x: -x[1]))
        estado = (f'<br><span style="color:{VERDE_OK};font-weight:bold;font-size:11px;">✔ Terminado</span>' if c["terminado"] else "")
        nombre_c = escape(cuartel) + (f'<br><span style="color:{GRIS};font-size:11px;">{escape(labor)}</span>' if len(r["labores"]) > 1 else "")
        filas_c.append({"celdas": [nombre_c, num(c["area"]), por_maq, num(ayer), num(c["acumulado"]),
                                   f'{rc.num(c["pct"] * 100, 0)} %{estado}'],
                        "fondo": VERDE_OK_F if c["terminado"] else ""})
        sum_area += c["area"]; sum_ayer += ayer; sum_acum += c["acumulado"]
    if r["sin_geocerca"] > 0:
        filas_c.append({"celdas": ['Sin cuartel definido<br><span style="font-size:11px;color:#5F6368;">aprox., sin cuartel definido</span>',
                                   "–", "–", f"~{num(r['sin_geocerca'])}", "–", "–"], "fondo": AMARILLO_F})
    total_c = ["Total", num(sum_area), "", num(sum_ayer + r["sin_geocerca"]), num(sum_acum), ""]
    caja = lambda titulo, valor: (f'<td width="33%" style="padding:8px 4px;background:{GRIS_FILA};border:1px solid {BORDE};'
                                  f'font-family:{FUENTE};text-align:center;"><div style="font-size:12px;color:{GRIS};">{titulo}</div>'
                                  f'<div style="font-size:20px;font-weight:bold;color:{NEGRO};margin-top:2px;">{valor}</div></td>')
    banda = ""
    if prueba:
        banda = (f'<tr><td style="padding:10px 12px;background:#FFF4CC;border:1px solid #E8C547;font-family:{FUENTE};'
                 f'font-size:13px;color:#5F4B00;"><b>PRUEBA</b> · {prueba}</td></tr><tr><td height="12"></td></tr>')
    nota = (f'<p style="margin:0 0 6px 0;">Las hectáreas son aproximadas, calculadas por GPS dentro de cada cuartel.'
            f'{" El trabajo sin cuartel definido es un aproximado." if r["sin_geocerca"] > 0 else ""}</p>'
            f'<p style="margin:0 0 6px 0;"><b>Inicio</b> y <b>término</b>: primer encendido y último apagado del motor '
            f'dentro del campo (sus cuarteles y alrededores). <b>Horas encendido</b>: tiempo con el motor encendido dentro del campo; '
            f'no cuenta el traslado ni lo hecho en otros lugares. <b>Eficiencia</b>: horas encendido ÷ (término − inicio − 1 h de almuerzo; '
            f'el almuerzo se descuenta en jornadas de 5 h o más), con un máximo de 100 %.</p>'
            + (f'<p style="margin:0 0 6px 0;">"aprox. (GPS)": horas en movimiento según el GPS, porque el contador del motor de esa máquina no fue confiable ese día.</p>' if aprox else "")
            + f'<p style="margin:0;">Avance: acumulado de la temporada en esa labor, sumando todas las máquinas sin repetir hileras.</p>')
    cliente_txt = escape(cli.get("cliente") or r["campo"])
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reporte diario C&amp;H</title></head>
<body style="margin:0;padding:0;background:#F2F2F2;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F2F2F2;"><tr><td align="center" style="padding:10px 4px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:720px;background:#ffffff;border:1px solid {BORDE};">
<tr><td style="padding:14px 10px 8px 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
{banda}
<tr><td style="padding:0 0 12px 0;"><img src="{logo_src}" alt="C&amp;H Cosecha Mecanizada" width="150" style="display:block;width:150px;height:auto;border:0;"></td></tr>
<tr><td style="font-family:{FUENTE};font-size:20px;font-weight:bold;color:{NEGRO};padding:4px 0 2px 0;">Reporte diario de trabajo</td></tr>
<tr><td style="font-family:{FUENTE};font-size:14px;color:{NEGRO};line-height:1.6;padding:0 0 12px 0;">
<b>Cliente:</b> {cliente_txt} · <b>Campo:</b> {escape(r["campo"])}<br>
<b>Fecha trabajada:</b> {fecha_trabajada(dia)} · <b>Labor:</b> {escape(labores)}</td></tr>
<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
{caja("Máquinas", len(maquinas))}{caja("Horas encendido", horas_txt(horas_total) + (' <span style="font-size:12px;font-weight:normal;">aprox.</span>' if aprox else ""))}{caja("Ha aprox.", num(ha_total))}
</tr></table></td></tr>
<tr><td style="font-family:{FUENTE};font-size:16px;font-weight:bold;color:{NEGRO};padding:18px 0 8px 0;">Máquinas</td></tr>
<tr><td>{tabla(["Máquina", "Operador", "Inicio", "Término", "Horas<br>encend.", "Efic.", "Ha<br>aprox."], filas_m,
              ["left", "left", "center", "center", "right", "right", "right"])}</td></tr>
<tr><td style="font-family:{FUENTE};font-size:16px;font-weight:bold;color:{NEGRO};padding:18px 0 8px 0;">Detalle por cuartel</td></tr>
<tr><td>{tabla(["Cuartel", "Sup.<br>(ha)", "Trabajado ayer<br>por máquina", "Ayer<br>(ha)", "Total<br>acum. (ha)", "Avance"], filas_c,
              ["left", "right", "left", "right", "right", "right"], total_c)}</td></tr>
<tr><td style="font-family:{FUENTE};font-size:12px;color:{GRIS};line-height:1.5;padding:16px 0 4px 0;">{nota}</td></tr>
<tr><td style="font-family:{FUENTE};font-size:12px;color:{GRIS};padding:10px 0 4px 0;border-top:1px solid {BORDE};">
C&amp;H Cosecha Mecanizada · <a href="https://www.cosechamecanizada.cl" style="color:{GRIS};">www.cosechamecanizada.cl</a></td></tr>
</table></td></tr></table></td></tr></table></body></html>"""


def texto_plano(r, dia):
    cli = r["cliente"] or {}
    ha = sum(m["ha"] + m["ha_sin"] for m in r["maquinas"].values())
    return (f"Reporte diario de trabajo C&H\nCliente: {cli.get('cliente') or r['campo']} · Campo: {r['campo']}\n"
            f"Fecha trabajada: {fecha_trabajada(dia)}\nMáquinas: {len(r['maquinas'])} · Ha aprox.: {num(ha)}\n"
            "El detalle está en la versión HTML de este correo y en el PDF adjunto.")


def logo_data_uri():
    with open(RUTA_LOGO, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def generar_pdf(r, dia):
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    base = f"reporte_{clave(r['campo'])}_{dia:%Y-%m-%d}"
    ruta_html = os.path.join(CARPETA_SALIDA, base + ".html")
    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(armar_html(r, dia, logo_data_uri()))
    ruta_pdf = os.path.join(CARPETA_SALIDA, f"Reporte C&H {r['campo']} {dia:%d-%m-%Y}.pdf")
    rc.generar_pdf(ruta_html, ruta_pdf)
    return ruta_pdf


def enviar_correo(asunto, html, texto, para, cc, pdf):
    """Para y CC visibles; el logo va dentro del correo (cid), no como enlace."""
    usuario, clave_g = os.environ["CORREO_USUARIO"].strip(), os.environ["CORREO_CLAVE"].replace(" ", "").strip()
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = f"Reporte C&H Cosecha Mecanizada <{usuario}>"
    msg["To"] = ", ".join(para)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    with open(RUTA_LOGO, "rb") as f:
        msg.get_payload()[1].add_related(f.read(), maintype="image", subtype="png", cid="<logo_cyh>", filename="Logo_CYH.png")
    with open(pdf, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf))
    import smtplib
    destinos = list(dict.fromkeys(para + cc))
    for intento in range(3):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
                s.login(usuario, clave_g)
                rechazados = s.send_message(msg, to_addrs=destinos)
            print(f"Envio: aceptado para {len(destinos) - len(rechazados)} de {len(destinos)} direcciones.")
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError) as e:
            print(f"Envio: intento {intento + 1} fallo ({type(e).__name__}); se reintenta.")
            time.sleep(10)
    raise RuntimeError("No se pudo enviar por Gmail")


def enviar_reportes(dia, solo_campo=None, real=None):
    """Arma y envia un correo por campo con trabajo. real=None usa config.json."""
    real = ENVIO_REAL if real is None else real
    sid, _ = rc.login()
    reportes, alertas = reportes_del_dia(dia, sid, solo_campo)
    print(f"Reporte a clientes del {dia} ({'ENVIO REAL' if real else 'PRUEBA: todo a ' + 'correo_clientes_prueba'}): "
          f"{len(reportes)} campo(s) con trabajo.")
    enviados = 0
    for r in reportes:
        ha = sum(m["ha"] + m["ha_sin"] for m in r["maquinas"].values())
        print(f"Campo | {r['campo']} | cliente: {'sí' if r['cliente'] else 'no'} | contactos con correo: {len(r['correos'])} | "
              f"maquinas: {len(r['maquinas'])} | ha: {ha:.2f} | cuarteles: {len(r['cuarteles'])} | sin geocerca: {r['sin_geocerca']:.2f}")
        for nombre, m in r["maquinas"].items():
            mot = m["motor"]
            print(f"  Maquina | {nombre} | operador: {'sí' if m['operador'] else 'no'} | motor: "
                  + (f"{hora_txt(mot['inicio'])}-{hora_txt(mot['termino'])}, {horas_txt(mot['horas'])} h" if mot else "sin datos")
                  + f" | GPS {horas_txt(m['gps_h'])} h | eficiencia: {'–' if m['eficiencia'] is None else round(m['eficiencia'] * 100)}"
                  + " | dia completo: " + (f"{hora_txt(m['motor_dia']['inicio'])}-{hora_txt(m['motor_dia']['termino'])}, {horas_txt(m['motor_dia']['horas'])} h" if m.get('motor_dia') else "sin datos")
                  + (f" | DUDOSO: {'; '.join(m['dudoso'])}" if m["dudoso"] else ""))
        for (cu, lab), c in r["cuarteles"].items():
            print(f"  Cuartel | {cu} | {lab} | {c['area']:.2f} ha | ayer {sum(c['ayer'].values()):.2f} | "
                  f"acumulado {c['acumulado']:.2f} ({c['pct'] * 100:.0f} %){' TERMINADO' if c['terminado'] else ''}")
        if not r["correos"] and real:
            continue   # sin correo: no se manda (va en las alertas)
        cli = r["cliente"] or {}
        asunto = f"Reporte diario C&H – {r['campo']} – {fecha_trabajada(dia)}"
        if real:
            para, cc, prueba = r["correos"], [CC_FIJO], None
        else:
            para, cc = [CORREO_PRUEBA_CLIENTES], []
            quien = (f"le habría llegado a {escape(cli.get('cliente') or r['campo'])}: Para "
                     + ", ".join(escape(c) for c in r["correos"]) + f", con copia a {escape(CC_FIJO)}"
                     if r["correos"] else "este campo <b>no tiene correo del cliente</b>: en el envío real no se le mandaría")
            prueba = quien
            asunto = f"[PRUEBA] {asunto} (para: {cli.get('cliente') or 'SIN CORREO'})"
        pdf = generar_pdf(r, dia)
        html = armar_html(r, dia, "cid:logo_cyh", prueba)
        enviar_correo(asunto, html, texto_plano(r, dia), para, cc, pdf)
        enviados += 1
    print(f"Correos enviados: {enviados}. Alertas: {len(alertas)}.")
    return reportes, alertas
