"""
reporte_v2.py

Version nueva del correo diario y de la pagina (pedido del usuario 22-oct-2026,
ver CLAUDE.md "Correo y pagina v2"), cruzando con la planilla "Maquinas en
Operacion" del Drive (planilla.py, solo lectura):
  0. Alerta grande: maquina que la planilla pone en un campo y cuyo GPS lleva
     mas de 15 dias sin senal.
  1. Resumen de ayer + maquinas que trabajaron (con operador), camionetas, camion.
  2. Maquinas en operacion (fuera de CYH): planilla vs GPS.
  3. Alertas.
  4. Trabajo de las maquinas por campo (temporada).
  5. Ultimos 7 dias.
Mientras el usuario no lo apruebe, solo se envia como prueba (modo prueba_v2).
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from html import escape

import planilla as pl
import reporte_correo as rc
import reporte_hectareas as rh
import sin_geocerca as sg

ZONA = rh.ZONA_HORARIA
_CANONICO = {}


def CAMPO(nombre_cuartel):
    """Campo del cuartel (campos unidos), con un solo nombre aunque las
    geocercas lo escriban distinto ("Santa Isabel" / "santa Isabel")."""
    campo = sg.campo_de(nombre_cuartel)
    k = pl.normalizar(campo)
    if k not in _CANONICO or (campo[:1].isupper() and not _CANONICO[k][:1].isupper()):
        _CANONICO[k] = campo  # se prefiere la version con mayuscula
    return _CANONICO[k]
# Maquinas que no son de CYH (por revisar): no suman a nuestro trabajo ni a los totales.
NO_CYH = set(rh.CONFIG.get("maquinas_no_cyh", ["Barredora 5497"]))
DIAS_ALERTA_SIN_SENAL = 15
DIAS_GPS_APAGADO = 30
DIAS_RECIENTES = 3
DIAS_TRABAJO_CORREO = 30  # "Trabajo por campo" en el correo: campos con trabajo en estos dias  # el GPS "calza" si esta o trabajo en el campo en estos dias
PAGINA = rh.CONFIG.get("pagina_reporte_v2", "reporte2.html")
# Datos de reporte2.html (aparte de reporte_diario.json, que reescribe el correo diario).
RUTA_V2 = os.path.join(rh.CARPETA_DATOS, "reporte_v2.json")


def temporada_inicio(labor, dia):
    """Inicio de la temporada en curso de la labor (reglas del 21-oct-2026)."""
    if labor in ("Picado", "Poda"):
        return date(dia.year if dia.month >= 4 else dia.year - 1, 4, 1)
    if labor == rh.LABOR_CON_PASADAS:
        return date(dia.year, 1, 1)
    if labor == "Raleo":
        return date(dia.year, 9, 1)
    return date(dia.year, 1, 1)


def labor_visible(labor, fecha):
    """Shacker SBS de sep a nov hace raleo (en main el historial dice cosecha)."""
    if labor == "Cosecha con recibidor" and 9 <= int(fecha[5:7]) <= 11:
        return "Raleo"
    return labor


def fecha_conexion(texto):
    try:
        return datetime.strptime(texto, "%d-%m-%Y %H:%M").replace(tzinfo=ZONA)
    except (TypeError, ValueError):
        return None


class Contexto:
    def __init__(self, ayer, planilla=None):
        self.ayer = ayer
        self.fa = ayer.isoformat()
        with open(rh.RUTA_FLOTA, "r", encoding="utf-8") as f:
            self.flota = json.load(f)
        self.historico = rh.cargar_historico()
        self.sin_geo = []
        if os.path.exists(sg.RUTA):
            with open(sg.RUTA, "r", encoding="utf-8") as f:
                self.sin_geo = json.load(f).get("trabajos", [])
        with open(rh.RUTA_GEOCERCAS_WEB, "r", encoding="utf-8") as f:
            self.campos = sorted({CAMPO(n) for n in json.load(f)})
        self.unidades = {u["nombre"]: u for u in rh.UNIDADES}
        self.planilla = planilla if planilla is not None else pl.cargar(
            list(self.unidades), rh.CONFIG.get("equivalencias_campos", {}))
        self.confirmadas = rh.CONFIG.get("maquinas_confirmadas", {})
        self.comunas = {}  # maquina -> comuna ya conocida (al rearmar sin Wialon)
        self.por_maquina = {m["nombre"]: m for m in self.flota.get("maquinas", [])}

    def campos_wialon(self, nombre_planilla):
        """Campos de Wialon de un nombre de la planilla ([] = sin geocerca)."""
        n = pl.normalizar(nombre_planilla)
        if n in self.planilla.get("equivalencias", {}):
            return self.planilla["equivalencias"][n]
        return [c for c in self.campos if pl.mismo_nombre(c, nombre_planilla)]

    def gps(self, maquina):
        """Lugar actual (CYH / campo / "sin geocerca"), dias sin senal y campos recientes."""
        m = self.por_maquina.get(maquina, {})
        ultima = fecha_conexion(m.get("ultima_conexion"))
        dias = (datetime.now(ZONA) - ultima).days if ultima else None
        ub = m.get("ubicacion")
        lugar = "CYH" if ub == "CYH" else ("fuera de geocercas" if ub in (None, "Fuera de geocercas") else CAMPO(ub))
        desde = (self.ayer - timedelta(days=DIAS_RECIENTES - 1)).isoformat()
        recientes, sin_geo = set(), False
        for d in m.get("dias", []):
            if d["fecha"] >= desde:
                recientes |= {CAMPO(g) for g, h in (d.get("horas_geocercas") or {}).items() if h >= 0.1}
                sin_geo = sin_geo or bool(d.get("sin_geocerca"))
        return {"lugar": lugar, "dias_sin_senal": dias, "recientes": recientes, "sin_geocerca": sin_geo,
                "mapa": m.get("mapa"), "ultima_conexion": m.get("ultima_conexion")}


def hace(segundos):
    h = segundos / 3600
    if h < 1:
        return f"{max(1, round(segundos / 60))} min"
    return f"{round(h)} h" if round(h) < 48 else f"{round(h / 24)} días"


def texto_gps(ctx, maquina, usuario=None):
    """Lo que dice el GPS, siempre (regla del 23-oct-2026): "detenido sin
    geocerca en <comuna>, desde hace 5 h" / "en movimiento en Candelaria" /
    "detenido en CYH, desde hace 3 días" / "sin señal desde el …"."""
    m = ctx.por_maquina.get(maquina, {})
    g = ctx.gps(maquina)
    ahora = datetime.now(ZONA).timestamp()
    if g["dias_sin_senal"] is not None and g["dias_sin_senal"] >= 1:
        return f"sin señal desde el {m.get('ultima_conexion')}"
    q = re.search(r"q=([-\d.]+),([-\d.]+)", m.get("mapa") or "")
    if g["lugar"] == "fuera de geocercas":
        comuna = ctx.comunas.get(maquina)
        if q and usuario:
            comuna = rc.localidad(rc.direccion(usuario, float(q.group(2)), float(q.group(1))))
        lugar = f"sin geocerca en {comuna}" if comuna else "sin geocerca"
    else:
        lugar = f"en {g['lugar']}"
    movimientos = [d["ultimo_movimiento"] for d in m.get("dias", []) if d.get("ultimo_movimiento")]
    ultimo = max(movimientos) if movimientos else None
    if ultimo and ahora - ultimo < 20 * 60:
        return f"en movimiento {lugar}"
    return f"detenido {lugar}" + (f", desde hace {hace(ahora - ultimo)}" if ultimo else "")


# ---------------------------------------------------------------------------
# Trabajo por campo (temporada)
# ---------------------------------------------------------------------------

def trabajo_por_campo(ctx):
    """[{maquina, labor, campo, ha, ha_sin, dias, promedio, ayer_ha, ayer_sin, detalle}]
    Trabajo sin geocerca: al campo asignado/confirmado (o probable unico) o, si
    no, al campo de la planilla (con sus equivalencias)."""
    filas = {}
    horas_dia = {}  # (maquina, fecha, campo) -> horas en geocercas de ese campo
    for m in ctx.flota.get("maquinas", []):
        for d in m.get("dias", []):
            for g, h in (d.get("horas_geocercas") or {}).items():
                k = (m["nombre"], d["fecha"], CAMPO(g))
                horas_dia[k] = horas_dia.get(k, 0) + h

    def fila(maquina, campo, labor):
        k = (maquina, campo, labor)
        if k not in filas:
            filas[k] = {"maquina": maquina, "campo": campo, "labor": labor, "ha": 0.0, "ha_sin": 0.0,
                        "ayer_ha": 0.0, "ayer_sin": 0.0, "por_dia": {}}
        return filas[k]

    for r in ctx.historico:
        if r["maquina"] in NO_CYH or r["area_trabajada_ha"] <= 0 or r["fecha"] > ctx.fa:
            continue
        labor = labor_visible(r["labor"], r["fecha"])
        if r["fecha"] < temporada_inicio(labor, ctx.ayer).isoformat():
            continue
        f = fila(r["maquina"], CAMPO(r["cuartel"]), labor)
        f["ha"] += r["area_trabajada_ha"]
        dia = f["por_dia"].setdefault(r["fecha"], {"cuarteles": {}, "sin": 0.0})
        dia["cuarteles"][r["cuartel"]] = dia["cuarteles"].get(r["cuartel"], 0) + r["area_trabajada_ha"]
        if r["fecha"] == ctx.fa:
            f["ayer_ha"] += r["area_trabajada_ha"]
    for t in ctx.sin_geo:
        if t["maquina"] in NO_CYH or t["fecha"] > ctx.fa or t.get("estado") == "ninguno":
            continue
        u = ctx.unidades.get(t["maquina"])
        labor = labor_visible(rh.labor_de(u) if u else t.get("labor", ""), t["fecha"])
        if t["fecha"] < temporada_inicio(labor, ctx.ayer).isoformat():
            continue
        campo = t.get("campo")
        if not campo:
            p = ctx.planilla["maquinas"].get(t["maquina"])
            if p and not p["en_cyh"]:
                wc = ctx.campos_wialon(p["campo"])
                campo = wc[0] if len(wc) == 1 else p["campo"].strip()
        if not campo:
            continue
        f = fila(t["maquina"], campo, labor)
        f["ha_sin"] += t["ha"]
        f["por_dia"].setdefault(t["fecha"], {"cuarteles": {}, "sin": 0.0})["sin"] += t["ha"]
        if t["fecha"] == ctx.fa:
            f["ayer_sin"] += t["ha"]
    salida = []
    for f in filas.values():
        dias = sorted(f.pop("por_dia").items())
        f["dias"] = len(dias)
        f["promedio"] = (f["ha"] + f["ha_sin"]) / f["dias"] if f["dias"] else 0.0
        f["detalle"] = [{"fecha": d, "horas": round(horas_dia.get((f["maquina"], d, f["campo"]), 0), 1) or None,
                         "cuarteles": [{"cuartel": c, "ha": round(h, 2)} for c, h in sorted(v["cuarteles"].items())],
                         "sin": round(v["sin"], 1)} for d, v in reversed(dias)]
        salida.append(f)
    return sorted(salida, key=lambda f: (rh.orden_flota(f["maquina"]), -f["ha"] - f["ha_sin"]))


# ---------------------------------------------------------------------------
# Maquinas en operacion: planilla vs GPS
# ---------------------------------------------------------------------------

def ultimo_sin_geo(ctx, maquina):
    """Ultimo trabajo sin geocerca de la maquina en los 7 dias hasta ayer (o None)."""
    desde = (ctx.ayer - timedelta(days=7)).isoformat()
    ts = [t for t in ctx.sin_geo if t["maquina"] == maquina and t["fecha"] >= desde]
    return max(ts, key=lambda t: t["fecha"]) if ts else None


def operacion(ctx, trabajo, usuario=None):
    plan = ctx.planilla
    fuente = "operación" if plan.get("fuente") == "operacion" else "planilla"
    filas, no_en_planilla, apagadas, alerta_grande, avisos = [], [], [], [], []
    promedio = {(f["maquina"], f["campo"]): f for f in trabajo}
    for nombre in sorted(ctx.unidades, key=rh.orden_flota):
        g = ctx.gps(nombre)
        p = plan["maquinas"].get(nombre)
        u = ctx.unidades[nombre]
        base = {"maquina": nombre, "labor": rh.labor_de(u), "grupo": rh.NOMBRES_GRUPOS_FLOTA[rh.orden_flota(nombre)[0]],
                "operador": (p or {}).get("operador", ""), "campo_planilla": (p or {}).get("campo", "").strip(),
                "gps": g["lugar"], "dias_sin_senal": g["dias_sin_senal"], "mapa": g["mapa"],
                "no_cyh": nombre in NO_CYH, "gps_texto": texto_gps(ctx, nombre, usuario),
                "lat_gps": None, "lon_gps": None}
        q = re.search(r"q=([-\d.]+),([-\d.]+)", g["mapa"] or "")
        if q:
            base["lat_gps"], base["lon_gps"] = float(q.group(1)), float(q.group(2))
        # Lugar de trabajo sin geocerca: el ultimo de los 7 dias o, si no hay, la posicion GPS.
        t = ultimo_sin_geo(ctx, nombre)
        base["lat"], base["lon"] = (t["lat"], t["lon"]) if t else (base["lat_gps"], base["lon_gps"])
        sin_senal = g["dias_sin_senal"]
        # GPS apagado hace mas de 30 dias fuera de CYH (en CYH el GPS se apaga al guardarla).
        if sin_senal is not None and sin_senal > DIAS_GPS_APAGADO and g["lugar"] != "CYH":
            apagadas.append({**base, "texto": f"GPS apagado hace {sin_senal} días"})
            if p and not p["en_cyh"]:
                alerta_grande.append(base)
            continue
        en_planilla_campo = bool(p) and not p["en_cyh"]
        fuera_cyh = g["lugar"] != "CYH"
        if not p and fuera_cyh:
            no_en_planilla.append({**base, "texto": f"GPS {g['lugar'] if g['lugar'] == 'fuera de geocercas' else 'en ' + g['lugar']}"})
            continue
        if not (en_planilla_campo or (p and fuera_cyh)):
            continue  # en CYH segun la planilla y el GPS
        conf = ctx.confirmadas.get(nombre)
        # La planilla ya se actualizo como pedia el aviso: confirmado, sin aviso.
        cumplida = bool(conf and conf.get("aviso") and pl.mismo_nombre(conf["aviso"], base["campo_planilla"] or "Taller"))
        if conf and conf.get("planilla") != base["campo_planilla"] and not cumplida:
            conf = None  # la planilla cambio: la confirmacion ya no aplica
        wc = ctx.campos_wialon(p["campo"]) if en_planilla_campo else []
        fila = {**base, "campos_wialon": wc}
        if sin_senal is not None and sin_senal > DIAS_ALERTA_SIN_SENAL:
            fila.update(estado="sin_senal", texto=f"sin señal hace {sin_senal} días")
            if en_planilla_campo:
                alerta_grande.append(base)
        elif conf:
            fila.update(estado="ok", texto=f"confirmado: {conf['texto']}")
            if conf.get("aviso") and not cumplida:
                avisos.append(f"Actualizar {fuente}: {nombre} → {conf['aviso']}")
        elif en_planilla_campo and (g["lugar"] in wc or g["recientes"] & set(wc)):
            fila.update(estado="ok", texto="GPS calza")
        elif en_planilla_campo and (g["lugar"] == "fuera de geocercas" or (g["sin_geocerca"] and g["lugar"] != "CYH")):
            regla = sg.regla_confirmada((base["lon"], base["lat"])) if base["lat"] is not None else None
            if regla:
                # Lugar confirmado en la pagina (lugares_confirmados).
                fila.update(estado="ok", texto=f"confirmado: {rh.nombre_lista_campo(regla['campo']) or regla['campo']} (sin geocerca)" if regla["campo"]
                            else "confirmado: no es de ningún campo")
            else:
                fila.update(estado="sin_geocerca", texto=f"sin geocerca · Posiblemente {p['campo'].strip()}")
        elif en_planilla_campo:
            fila.update(estado="confirmar", texto=f"Confirmar · GPS en {g['lugar']}")
        else:
            donde = g["lugar"] if g["lugar"] == "fuera de geocercas" else "en " + g["lugar"]
            fila.update(estado="confirmar", texto=f"Confirmar · {fuente} Taller, GPS {donde}")
        clave = (nombre, (wc[0] if len(wc) == 1 else base["campo_planilla"]))
        t = promedio.get(clave)
        fila["promedio"] = round(t["promedio"], 2) if t else None
        fila["ayer_ha"] = round((t["ayer_ha"] + t["ayer_sin"]), 2) if t else 0.0
        fila["ayer_trabajo"] = any(r["maquina"] == nombre and r["fecha"] == ctx.fa and r["area_trabajada_ha"] > 0
                                   for r in ctx.historico) or any(
            d["fecha"] == ctx.fa and (d.get("horas_geocercas") or d.get("sin_geocerca"))
            for d in ctx.por_maquina.get(nombre, {}).get("dias", []))
        # Trabajo fuera de CYH sin operador anotado en la planilla: queda en la maquina.
        fila["sin_operador"] = bool(fila["ayer_trabajo"] and g["lugar"] != "CYH" and not (p.get("operador") or "").strip())
        filas.append(fila)
    return {"filas": filas, "no_en_planilla": no_en_planilla, "gps_apagado": apagadas,
            "alerta_grande": alerta_grande, "avisos": avisos,
            "sin_cruce": [f["maquina_planilla"] for f in plan.get("sin_cruce", []) if not f["en_cyh"]],
            "aviso_planilla": plan.get("aviso")}


# ---------------------------------------------------------------------------
# Correo (HTML con estilos en linea, como el actual)
# ---------------------------------------------------------------------------

def boton(ancla):
    url = f"{rc.URL_PAGINA}{PAGINA}#{ancla}"
    return (f'<tr><td align="right" style="padding:6px 0 2px 0;"><a href="{url}" style="display:inline-block;'
            f'padding:6px 12px;border:1px solid {rc.VERDE};border-radius:5px;font-family:{rc.FUENTE};font-size:12px;'
            f'font-weight:bold;color:{rc.VERDE};text-decoration:none;">Más información en la página &rsaquo;</a></td></tr>')


def marca(estado, texto):
    colores = {"ok": ("#1f6b34", "#e3f2e6", "✓ "), "sin_geocerca": ("#8a6a00", "#fff4cc", ""),
               "confirmar": ("#b3261e", "#fdecea", ""), "sin_senal": ("#5d6660", "#eceeed", "")}
    c, f, pre = colores.get(estado, colores["sin_senal"])
    return (f'<span style="display:inline-block;padding:1px 6px;border-radius:9px;background:{f};color:{c};'
            f'font-size:11px;font-weight:bold;">{pre}{escape(texto)}</span>')


def donde_ayer(d, campo_planilla):
    partes = [escape(rc.agrupar_geocercas(sorted(d["horas_geocercas"], key=lambda g: -d["horas_geocercas"][g])))] \
        if d["horas_geocercas"] else []
    if d["sin_geocerca"]:
        extra = f" · posiblemente {escape(campo_planilla)}" if campo_planilla else ""
        partes.append(f'<span style="color:{rc.ROJO};font-weight:bold;">sin geocerca{extra}</span>')
    return "<br>".join(partes) or "–"


def armar_html_v2(datos, ctx, trabajo, oper):
    ayer, dias, fa = datos["ayer"], datos["dias"], ctx.fa
    maquinas, camionetas, camiones = datos["maquinas"], datos["camionetas"], datos["camiones"]
    km = lambda lista, f: sum(v["dias"][f]["km"] for v in lista)
    nuestras = [m for m in maquinas if m["nombre"] not in NO_CYH]
    hoy_m = [(m, m["dias"][fa]) for m in maquinas]
    hoy_n = [(m, d) for m, d in hoy_m if m["nombre"] not in NO_CYH]
    ha_ayer = sum(d["ha"] for _, d in hoy_n)
    ha_sin_ayer = sum(d["ha_sin"] for _, d in hoy_n)
    horas_ayer = sum(d["horas"] for _, d in hoy_n)
    movidas = sum(1 for v in camionetas if v["dias"][fa]["se_movio"])
    plan = {m: f for m, f in ctx.planilla["maquinas"].items()}
    filas = []

    encabezado = (
        f'<tr><td style="padding:16px;background:{rc.VERDE};font-family:{rc.FUENTE};color:#ffffff;">'
        f'<div style="font-size:19px;font-weight:bold;">Reporte diario de flota – C&amp;H Maquinaria</div>'
        f'<div style="font-size:14px;padding-top:4px;">{rc.fecha_larga(ayer).capitalize()}</div></td></tr>'
        + (f'<tr><td style="padding:6px 16px;background:#FFF6DB;font-family:{rc.FUENTE};font-size:12px;color:#7A5B00;">'
           'Marcha blanca: algunos números se están ajustando.</td></tr>' if rc.MARCHA_BLANCA else ""))

    # 0. Alerta grande
    if oper["alerta_grande"]:
        lista = "<br>".join(f'<b>{escape(a["maquina"])}</b> – planilla: {escape(a["campo_planilla"])} · '
                            f'GPS sin señal hace {a["dias_sin_senal"]} días' for a in oper["alerta_grande"])
        filas.append(f'<tr><td style="padding:12px;margin-top:10px;background:{rc.ROJO};font-family:{rc.FUENTE};'
                     f'color:#fff;font-size:14px;line-height:1.5;"><div style="font-size:16px;font-weight:bold;">'
                     f'⚠ Máquinas en campo sin señal GPS (más de {DIAS_ALERTA_SIN_SENAL} días)</div>{lista}</td></tr>')
    if oper.get("aviso_planilla"):
        filas.append(rc.linea(f'<span style="color:{rc.ROJO};">⚠ {escape(oper["aviso_planilla"])}. El correo sale igual, '
                              'sin el cruce con la planilla.</span>', tam=12))

    # 1. Resumen de ayer
    filas.append(rc.titulo(f"Resumen de ayer ({rc.fecha_larga(ayer, anio=False)} {ayer:%d-%m-%Y})"))
    filas.append(rc.indicadores([
        (f"{sum(1 for _, d in hoy_n if d['trabajo'])} de {len(nuestras)}", "máquinas trabajaron"),
        (rc.num(horas_ayer), "horas de las máquinas")]))
    filas.append(rc.linea(f'<b style="font-size:16px;color:{rc.VERDE};">{rc.num(ha_ayer, 2)} ha</b> en geocercas'
                          + (f' + <b style="color:{rc.ROJO};">~{rc.num(ha_sin_ayer)} ha</b> estimadas sin geocerca'
                             if ha_sin_ayer else "")))
    km_camion = " · ".join(f'<b>{rc.num(c["dias"][fa]["km"], 0)} km</b> camión' for c in camiones)
    filas.append(rc.linea(f'<b>{rc.num(km(camionetas, fa), 0)} km</b> camionetas ({movidas} de {len(camionetas)} '
                          f'se movieron)' + (f" · {km_camion}" if km_camion else "")))

    # 1a. Maquinas que trabajaron ayer
    filas.append(rc.subtitulo("Máquinas que trabajaron ayer"))
    lista, estilos = [], {}
    for m, d in hoy_m:
        if not d["se_movio"]:
            continue
        p = plan.get(m["nombre"], {})
        no_cyh = m["nombre"] in NO_CYH
        nombre = escape(m["nombre"]) + (f'<br><span style="color:{rc.ROJO};font-size:11px;">No es de CYH (por revisar)'
                                        '</span>' if no_cyh else "")
        if d["sin_geocerca"] or no_cyh:
            estilos[len(lista)] = rc.ROJO_CLARO
        lista.append([nombre, escape(m["labor"]), escape(p.get("operador") or "–"),
                      donde_ayer(d, p.get("campo") if p and not p.get("en_cyh") else ""),
                      rc.num(d["horas"]) if d["horas"] else "–", rc.ha_texto(d["ha"], d["ha_sin"])])
    if lista:
        filas.append(rc.tabla(["Máquina", "Labor", "Operador", "Dónde", "Horas", "Ha"], lista,
                              ["l", "l", "l", "l", "r", "r"],
                              ["Total", "", "", "", rc.num(horas_ayer), rc.ha_texto(ha_ayer, ha_sin_ayer, total=True)],
                              estilos, ocultar_celular={1}))
    else:
        filas.append(rc.parrafo("Ninguna máquina trabajó ayer."))
    filas.append(boton("maquinas-ayer"))

    # 1b. Camionetas
    filas.append(rc.subtitulo(f"Camionetas · ayer ({ayer:%d-%m})"))
    movieron = [v for v in camionetas if v["dias"][fa]["se_movio"]]
    quietas = [v for v in camionetas if not v["dias"][fa]["se_movio"]]
    lista = [[escape(v["nombre"]), f'<b style="font-size:14px;color:{rc.VERDE};">{rc.num(v["dias"][fa]["km"])}</b>',
              f'{rc.hora(v["dias"][fa]["salida"])}–{rc.hora(v["dias"][fa]["llegada"])}',
              rc.lugares_html(rc.lugares_en_orden(v["dias"][fa]["visitas"]), enlaces=False) or "camino"] for v in movieron]
    if lista:
        filas.append(rc.tabla(["Camioneta", "Km", "Salida–llegada", "Dónde estuvo"], lista, ["l", "r", "l", "l"],
                              ["Total", f'<b>{rc.num(km(camionetas, fa))}</b>', "", ""]))
    if quietas:
        filas.append(rc.parrafo("No se movieron: " + ", ".join(
            f'{escape(v["nombre"])} (en {escape((v["dias"][fa].get("donde_quedo") or ("?",))[0])})' for v in quietas) + "."))
    filas.append(rc.parrafo("En negrita, los campos (geocercas); en texto normal, las comunas donde se detuvo.", tam=11))
    filas.append(boton("camionetas"))

    # 1c. Camion
    for c in camiones:
        d = c["dias"][fa]
        filas.append(rc.subtitulo(f"Camión · ayer ({ayer:%d-%m})"))
        filas.append(rc.linea(f'<b>{rc.num(d["km"])} km</b> · {rc.hora(d["salida"])}–{rc.hora(d["llegada"])} · '
                              f'{rc.lugares_html(rc.lugares_en_orden(d["visitas"]), " → ", enlaces=False)}'
                              if d["se_movio"] else
                              f'0 km · No se movió · en {escape((d.get("donde_quedo") or ("?",))[0])}'))
        filas.append(boton("camion"))

    # 2. Maquinas en operacion
    filas.append(rc.titulo("Máquinas en operación (fuera de CYH)"))
    lista, estilos = [], {}
    for f in oper["filas"]:
        if f["estado"] == "confirmar":
            estilos[len(lista)] = rc.ROJO_CLARO
        campo = (escape(f["campo_planilla"]) if f["campo_planilla"] and pl.normalizar(f["campo_planilla"]) != "taller"
                 else "Taller")
        ayer_txt = f'<b style="color:{rc.VERDE};">{rc.num(f["ayer_ha"], 2)}</b>' if f["ayer_ha"] else "–"
        gps = f'<br><span style="color:{rc.TEXTO_SUAVE};font-size:11px;">GPS: {escape(f["gps_texto"])}</span>'
        lista.append([escape(f["maquina"]), escape(f["operador"] or "–"), f"{campo}<br>{marca(f['estado'], f['texto'])}{gps}",
                      rc.num(f["promedio"], 2) if f["promedio"] else "–", ayer_txt])
    if lista:
        filas.append(rc.tabla(["Máquina", "Operador", "Campo (planilla)", "Promedio ha/día", "Ayer ha"], lista,
                              ["l", "l", "l", "r", "r"], None, estilos))
    for a in oper["avisos"]:
        filas.append(rc.linea(f'<b style="color:{rc.ROJO};">{escape(a)}</b>', tam=12))
    if oper["no_en_planilla"]:
        filas.append(rc.linea(f'<b style="color:{rc.ROJO};">Fuera de CYH y no está en la planilla:</b> ' + ", ".join(
            f'{escape(x["maquina"])} ({escape(x["texto"])})' + (" – No es de CYH (por revisar)" if x["no_cyh"] else "")
            for x in oper["no_en_planilla"]), tam=12))
    if oper["gps_apagado"]:
        filas.append(rc.linea('<b>GPS apagado hace más de 30 días:</b> ' + ", ".join(
            f'{escape(x["maquina"])} ({x["dias_sin_senal"]} d)' for x in oper["gps_apagado"]), tam=12))
    filas.append(boton("operacion"))

    # 3. Alertas
    filas.append(rc.titulo("Alertas"))
    sin_senal = datos["flota"].get("alertas_sin_senal", [])
    texto = ", ".join(f'{escape(a["maquina"])} (desde {escape((a["ultima_conexion"] or "")[:5])})' for a in sin_senal)
    filas.append(rc.linea(f'<b style="color:{rc.ROJO if sin_senal else rc.TEXTO};">GPS sin señal:</b> {texto or "ninguna"}'))
    sin_geo = []
    for m, d in hoy_n:
        if d["sin_geocerca"]:
            p = plan.get(m["nombre"])
            prob = f", probable {escape(p['campo'].strip())}" if p and not p["en_cyh"] else ""
            sin_geo.append(f'{escape(m["nombre"])} (~{rc.num(d["ha_sin"])} ha{prob})')
    filas.append(rc.linea(f'<b style="color:{rc.ROJO if sin_geo else rc.TEXTO};">Trabajo sin geocerca:</b> '
                          f'{", ".join(sin_geo) or "ninguno"}'))
    filas.append(boton("alertas"))

    # 4. Trabajo de las maquinas por campo (temporada)
    filas.append(rc.titulo("Trabajo de las máquinas por campo · temporada"))
    lista, grupo = [], None
    desde_30 = (ayer - timedelta(days=DIAS_TRABAJO_CORREO - 1)).isoformat()
    for f in trabajo:
        if not any(d["fecha"] >= desde_30 for d in f["detalle"]):
            continue  # en el correo, solo campos con trabajo en los ultimos 30 dias (la pagina muestra todo)
        g = rh.NOMBRES_GRUPOS_FLOTA[rh.orden_flota(f["maquina"])[0]]
        if g != grupo:
            grupo = g
            lista.append(g)
        area = rc.num(f["ha"] + f["ha_sin"], 1)
        area = ("~" + area) if f["ha_sin"] else area
        ayer_ha = f["ayer_ha"] + f["ayer_sin"]
        lista.append([f'<b>{escape(f["maquina"])}</b><br><span style="color:{rc.TEXTO_SUAVE};font-size:11px;">'
                      f'{escape(f["labor"])}</span>', escape(f["campo"]), area, str(f["dias"]), rc.num(f["promedio"], 2),
                      f'<b style="color:{rc.VERDE};">{("~" if f["ayer_sin"] else "") + rc.num(ayer_ha, 2)}</b>'
                      if ayer_ha else "–"])
    filas.append(rc.tabla(["Máquina", "Campo", "Ha temporada", "Días", "Ha/día", "Ayer"], lista,
                          ["l", "l", "r", "r", "r", "r"]))
    filas.append(rc.parrafo(f"Solo los campos con trabajo en los últimos {DIAS_TRABAJO_CORREO} días (con el total de "
                            "la temporada); la página muestra todos. "
                            "Con ~: incluye trabajo sin geocerca estimado (horas × rendimiento real), asignado al campo "
                            "confirmado o al de la planilla. Temporada: poda y picado desde el 1 de abril; raleo desde "
                            "el 1 de septiembre; las demás desde el 1 de enero.", tam=11))
    filas.append(boton("trabajo-campo"))

    # 5. Ultimos 7 dias
    filas.append(rc.titulo(f"Últimos 7 días ({dias[0]:%d-%m} al {ayer:%d-%m})"))
    ha_dia = {d.isoformat(): sum(m["dias"][d.isoformat()]["ha"] for m in nuestras) for d in dias}
    maximo = max(ha_dia.values()) if ha_dia else 0
    lista = [[rc.fecha_corta(d), str(sum(1 for m in nuestras if m["dias"][d.isoformat()]["trabajo"])),
              rc.barrita(ha_dia[d.isoformat()], maximo), rc.num(sum(m["dias"][d.isoformat()]["horas"] for m in nuestras)),
              rc.num(km(camionetas, d.isoformat()), 0), rc.num(km(camiones, d.isoformat()), 0)] for d in dias]
    filas.append(rc.tabla(["Día", "Máq.", "Hectáreas", "Horas", "Km cam.", "Km camión"], lista,
                          ["l", "r", "r", "r", "r", "r"],
                          ["Total", "", rc.num(sum(ha_dia.values()), 2),
                           rc.num(sum(d["horas"] for m in nuestras for d in m["dias"].values())),
                           rc.num(sum(km(camionetas, d.isoformat()) for d in dias), 0),
                           rc.num(sum(km(camiones, d.isoformat()) for d in dias), 0)]))
    filas.append(boton("semana"))
    filas.append(rc.parrafo("Detalle completo en el PDF adjunto.", tam=11))

    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light"><title>Reporte diario de flota</title>'
            "<style>@media screen and (max-width:520px){.ocm{display:none!important;} .caja{width:47%!important;min-width:0!important;}}</style></head>"
            '<body style="margin:0;padding:0;background:#F1F4F2;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F4F2;">'
            '<tr><td align="center" style="padding:8px 0;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:680px;background:#ffffff;border-collapse:collapse;">'
            f'{encabezado}<tr><td style="padding:0 10px 16px 10px;"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(filas)}</table></td></tr>'
            '</table></td></tr></table></body></html>')


# ---------------------------------------------------------------------------
# Datos de la pagina (se agregan a docs/datos/reporte_diario.json, clave "v2")
# ---------------------------------------------------------------------------

def huella_planilla(plan):
    """Huella (sha256) de lo que se usa de la planilla: si no cambia, no se
    rearma la pagina. No guarda la planilla, solo la huella."""
    import hashlib
    filas = sorted((f["maquina_planilla"], f["operador"], f["campo"], f["destino"])
                   for f in list(plan.get("maquinas", {}).values()) + plan.get("sin_cruce", []))
    return hashlib.sha256(json.dumps(filas, ensure_ascii=False).encode()).hexdigest()


def datos_pagina_v2(datos, ctx, trabajo, oper):
    fa = ctx.fa
    plan = ctx.planilla["maquinas"]
    maquinas_ayer = []
    for m in (datos or {}).get("maquinas", []):
        d = m["dias"][fa]
        if not d["se_movio"]:
            continue
        p = plan.get(m["nombre"], {})
        maquinas_ayer.append({
            "maquina": m["nombre"], "labor": m["labor"], "grupo": m["grupo"], "operador": p.get("operador", ""),
            "geocercas": rc.agrupar_geocercas(sorted(d["horas_geocercas"], key=lambda g: -d["horas_geocercas"][g])),
            "sin_geocerca": bool(d["sin_geocerca"]),
            "posible": p.get("campo", "").strip() if p and not p.get("en_cyh") else "",
            "horas": round(d["horas"], 1), "ha": round(d["ha"], 2), "ha_sin": round(d["ha_sin"], 1),
            "no_cyh": m["nombre"] in NO_CYH})
    filas = []
    for f in oper["filas"]:
        filas.append({k: f.get(k) for k in ("maquina", "labor", "grupo", "operador", "campo_planilla", "estado", "texto",
                                              "promedio", "ayer_ha", "ayer_trabajo", "gps", "dias_sin_senal", "mapa",
                                              "campos_wialon", "gps_texto", "lat", "lon", "sin_operador")})
    import operadores
    # GPS de TODAS las maquinas activas (columna GPS de la pagina Operacion).
    gps_maquinas = {}
    for f in oper["filas"]:
        gps_maquinas[f["maquina"]] = {"estado": f["estado"], "texto": f["texto"], "gps": f.get("gps_texto"), "mapa": f.get("mapa")}
    for x in oper["no_en_planilla"]:
        gps_maquinas[x["maquina"]] = {"estado": "confirmar", "texto": "Confirmar · GPS fuera de CYH y sin campo en la operación",
                                      "gps": x.get("gps_texto"), "mapa": x.get("mapa")}
    for x in oper["gps_apagado"]:
        gps_maquinas[x["maquina"]] = {"estado": "sin_senal", "texto": f"sin señal hace {x['dias_sin_senal']} días",
                                      "gps": x.get("gps_texto"), "mapa": x.get("mapa")}
    for m in ctx.unidades:
        if m not in gps_maquinas:
            g = ctx.gps(m)
            sin = g["dias_sin_senal"] is not None and g["dias_sin_senal"] > DIAS_GPS_APAGADO
            gps_maquinas[m] = {"estado": "sin_senal" if sin else "ok",
                               "texto": f"sin señal hace {g['dias_sin_senal']} días" if sin else "en CYH",
                               "gps": texto_gps(ctx, m), "mapa": g["mapa"]}
    return {
        "pagina": PAGINA,
        "gps_maquinas": gps_maquinas,
        # Maquinas activas en el orden fijo de la flota (filas de la pagina Operacion).
        "unidades": [{"maquina": m, "labor": rh.labor_de(ctx.unidades[m]),
                      "grupo": rh.NOMBRES_GRUPOS_FLOTA[rh.orden_flota(m)[0]]} for m in sorted(ctx.unidades, key=rh.orden_flota)],
        "operacion_actualizada": ctx.planilla.get("actualizado"),
        # "Desde" automatico (llegada al campo actual segun el GPS) de cada maquina en un campo.
        "desde_auto": {m: d for m, f in ctx.planilla.get("maquinas", {}).items() if not f.get("en_cyh")
                       for d in [operadores.desde_auto(ctx, m, f["campo"])] if d},
        "fuente": ctx.planilla.get("fuente", "planilla"),
        "fecha": ctx.fa,
        "operadores": operadores.construir(ctx, oper),
        "url_confirmar": rh.CONFIG.get("url_confirmaciones"),
        "aviso_planilla": oper.get("aviso_planilla"),
        "planilla_huella": huella_planilla(ctx.planilla) if ctx.planilla.get("ok") else None,
        "planilla_leida": datetime.now(ZONA).strftime("%d-%m-%Y %H:%M") if ctx.planilla.get("ok") else None,
        "alerta_grande": [{k: a.get(k) for k in ("maquina", "campo_planilla", "dias_sin_senal", "mapa")}
                          for a in oper["alerta_grande"]],
        "maquinas_ayer": maquinas_ayer,
        "operacion": filas,
        "no_en_planilla": [{k: x.get(k) for k in ("maquina", "labor", "texto", "mapa", "no_cyh", "gps_texto")} for x in oper["no_en_planilla"]],
        "gps_apagado": [{k: x.get(k) for k in ("maquina", "labor", "dias_sin_senal", "mapa", "gps_texto")} for x in oper["gps_apagado"]],
        "avisos_planilla": oper["avisos"],
        "trabajo_campo": [{**f, "ha": round(f["ha"], 2), "ha_sin": round(f["ha_sin"], 1), "promedio": round(f["promedio"], 2),
                           "ayer_ha": round(f["ayer_ha"], 2), "ayer_sin": round(f["ayer_sin"], 1),
                           "grupo": rh.NOMBRES_GRUPOS_FLOTA[rh.orden_flota(f["maquina"])[0]]} for f in trabajo],
    }


def preparar(sid, usuario, ayer, publicar, planilla=None):
    """Correo v2 (cuerpo), PDF (detalle completo, el de siempre) y datos de la pagina."""
    corto, ruta_pdf, datos = rc.preparar_reporte(sid, usuario, ayer, publicar=False)
    ctx = Contexto(ayer, planilla)
    trabajo = trabajo_por_campo(ctx)
    oper = operacion(ctx, trabajo, usuario)
    html = armar_html_v2(datos, ctx, trabajo, oper)
    pagina = rc.datos_pagina(datos)
    pagina["v2"] = datos_pagina_v2(datos, ctx, trabajo, oper)
    destino = RUTA_V2 if publicar else os.path.join(rc.CARPETA_SALIDA, "reporte_v2.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(pagina, f, ensure_ascii=False)
    with open(os.path.join(rc.CARPETA_SALIDA, f"correo_v2_{ayer}.html"), "w", encoding="utf-8") as f:
        f.write(html)
    if publicar:
        rc.guardar_en_repo([RUTA_V2], f"Reporte diario {ayer} (v2)")
    return html, ruta_pdf, oper


def maquinas_ayer_de_pagina(pagina, ctx):
    """"Maquinas que trabajaron ayer" desde los datos ya publicados del correo
    (reporte_diario.json), sin Wialon."""
    plan = ctx.planilla.get("maquinas", {})
    salida = []
    for m in pagina.get("maquinas", []):
        d = next((x for x in m.get("dias", []) if x["fecha"] == ctx.fa), None)
        if not d or not (d.get("ha") or d.get("horas") or d.get("sin")):
            continue
        p = plan.get(m["nombre"], {})
        lugares = sorted(d.get("lugares", []), key=lambda l: -l.get("horas", 0))
        salida.append({
            "maquina": m["nombre"], "labor": m["labor"], "grupo": m["grupo"], "operador": p.get("operador", ""),
            "geocercas": rc.agrupar_geocercas([l["geocerca"] for l in lugares]),
            "sin_geocerca": bool(d.get("sin")),
            "posible": p.get("campo", "").strip() if p and not p.get("en_cyh") else "",
            "horas": round(d.get("horas", 0) + d.get("horas_sin", 0), 1), "ha": round(d.get("ha", 0), 2),
            "ha_sin": round(d.get("ha_sin", 0), 1), "no_cyh": m["nombre"] in NO_CYH})
    return salida


def leer_json(ruta):
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def rearmar_pagina(solo_si_cambio=False, base_nueva=False, usuario=None):
    """Arma docs/datos/reporte_v2.json (datos de reporte2.html: lo del correo
    + bloque "v2") con lo ya publicado (flota.json, historial,
    sin_geocerca.json, config.json y la planilla del Drive), SIN bajar GPS de
    Wialon (usuario: solo para las comunas, lectura). Desde el 26-oct-2026 en
    un archivo aparte: el correo diario reescribe reporte_diario.json sin "v2".
      - base_nueva: parte del reporte_diario.json de hoy (paso de la manana,
        despues del correo de las 07:45); si no, de reporte_v2.json.
      - solo_si_cambio: solo si cambio la planilla o el historial de operadores.
    Si la planilla no se puede leer, no toca nada."""
    doc = leer_json(RUTA_V2)
    if base_nueva or not doc:
        base = leer_json(rc.RUTA_DATOS_PAGINA)
        if not base:
            return False
    else:
        base = doc
    base = {k: v for k, v in base.items() if k != "v2"}
    previo = (doc or {}).get("v2") or (leer_json(rc.RUTA_DATOS_PAGINA) or {}).get("v2") or {}
    ctx = Contexto(date.fromisoformat(base["fecha"]))
    if not ctx.planilla.get("ok"):
        print(f"No se rearma reporte2: {ctx.planilla.get('aviso')}")
        return False
    import operadores
    nuevos_operadores = operadores.registrar(ctx.planilla)  # historial de operadores de hoy
    if solo_si_cambio and previo.get("planilla_huella") == huella_planilla(ctx.planilla) and not nuevos_operadores:
        print("La planilla no cambio: no se rearma.")
        return False
    for x in previo.get("operacion", []) + previo.get("no_en_planilla", []) + previo.get("gps_apagado", []):
        c = re.search(r"sin geocerca en (.+?)(?:,|$)", x.get("gps_texto") or "")
        if c:
            ctx.comunas[x["maquina"]] = c.group(1)
    trabajo = trabajo_por_campo(ctx)
    oper = operacion(ctx, trabajo, usuario)
    nuevo = datos_pagina_v2(None, ctx, trabajo, oper)
    nuevo["maquinas_ayer"] = (previo["maquinas_ayer"] if previo.get("fecha") == ctx.fa and previo.get("maquinas_ayer")
                              else maquinas_ayer_de_pagina(base, ctx))
    nuevo["actualizado"] = datetime.now(ZONA).strftime("%d-%m-%Y %H:%M")
    with open(RUTA_V2, "w", encoding="utf-8") as f:
        json.dump({**base, "v2": nuevo}, f, ensure_ascii=False)
    print(f"reporte2 armado ({base['fecha']}): {len(oper['filas'])} maquinas en operacion, "
          f"{len(nuevo['maquinas_ayer'])} trabajaron ayer.")
    return True
