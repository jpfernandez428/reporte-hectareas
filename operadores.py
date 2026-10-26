"""
operadores.py

Pestana "Operadores" de reporte2.html (pedido del usuario 22-oct-2026; los
nombres de operadores se pueden guardar en el repositorio, autorizado por el
usuario el 22-10-2026).

  - Historial (docs/datos/operadores.json): en cada lectura de la planilla
    "Maquinas en Operacion" se guarda que operador estaba en cada maquina ese
    dia (exacto). Sin foto del dia, los dias desde "Desde" (llegada al campo:
    la fecha puesta en la pagina Operacion o la automatica del GPS) son del
    operador actual: "aproximado". Los dias sin lectura entre dos
    lecturas con el mismo operador en la maquina tambien quedan aproximados.
  - Equivalencias de nombres (config.json -> equivalencias_operadores:
    {nombre: [otros nombres]}), editables en la pagina. Nombres parecidos a
    uno conocido generan un aviso para confirmar si es el mismo
    (config.json -> operadores_distintos guarda los que NO son el mismo).
  - Promedios por labor y temporada (un operador puede podar en su temporada
    y manejar un shaker en cosecha o raleo), comparados con el promedio de
    todos los operadores en la misma labor y temporada.
  - Trabajo sin operador anotado: queda en la maquina, sin operador, con aviso.
"""

import difflib
import json
import os
import re
from datetime import date, datetime, timedelta

import planilla as pl
import reporte_hectareas as rh

RUTA = os.path.join(rh.CARPETA_DATOS, "operadores.json")
DIAS_ULTIMOS = 15        # "sus ultimos dias" en la pagina
# Dia trabajado (regla del usuario 26-oct-2026): con ha o al menos 1 h de trabajo
# (en geocercas + sin geocerca). Detenida, en traslado o en CYH no cuenta.
HORAS_DIA_TRABAJADO = 1.0
PARECIDO_MINIMO = 0.78   # nombres parecidos (difflib): aviso para confirmar


def clave(nombre):
    return re.sub(r"[^a-z0-9 ]", "", pl.normalizar(nombre)).strip()


def mapa_canonico():
    """{clave de cualquier nombre: nombre canonico} segun las equivalencias."""
    salida = {}
    for canon, otros in rh.CONFIG.get("equivalencias_operadores", {}).items():
        salida[clave(canon)] = canon
        for o in otros:
            salida[clave(o)] = canon
    return salida


def canonico(nombre, mapa=None):
    nombre = re.sub(r"\s+", " ", str(nombre or "")).strip()
    if not nombre:
        return ""
    return (mapa if mapa is not None else mapa_canonico()).get(clave(nombre), nombre)


def cargar():
    if os.path.exists(RUTA):
        with open(RUTA, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"dias": {}}


def registrar(plan, hoy=None):
    """Guarda el operador de cada maquina hoy (ultima lectura del dia).
    Devuelve True si cambio algo."""
    if not plan.get("ok"):
        return False
    hoy = (hoy or datetime.now(rh.ZONA_HORARIA).date()).isoformat()
    datos = cargar()
    nuevo = {m: {"operador": f["operador"].strip(), "implemento": f["implemento"].strip(), "campo": f["campo"].strip()}
             for m, f in sorted(plan.get("maquinas", {}).items()) if f.get("operador", "").strip()}
    if datos["dias"].get(hoy) == nuevo:
        return False
    datos["dias"][hoy] = nuevo
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=True)
    return True


def etiqueta_temporada(labor, dia):
    import reporte_v2 as rv
    ini = rv.temporada_inicio(labor, dia)
    if labor in ("Picado", "Poda"):
        return f"{ini.year}-{(ini.year + 1) % 100:02d}"
    return str(ini.year)


def estadia(ctx, maquina, campo_planilla, hasta):
    """Dias (AAAA-MM-DD, hasta 'hasta') de la estadia actual de la maquina en
    el campo de la planilla: hacia atras mientras no termine el dia en CYH ni
    trabaje en otro campo."""
    import reporte_v2 as rv
    campos = set(ctx.campos_wialon(campo_planilla)) | {campo_planilla}
    claves = {pl.normalizar(c) for c in campos}
    dias = sorted((d for d in ctx.por_maquina.get(maquina, {}).get("dias", []) if d["fecha"] <= hasta),
                  key=lambda d: d["fecha"], reverse=True)
    salida = []
    for d in dias:
        trabajados = {rv.CAMPO(g) for g, h in (d.get("horas_geocercas") or {}).items() if h >= 0.1}
        if trabajados and not {pl.normalizar(c) for c in trabajados} & claves:
            break
        if (d.get("fin") or {}).get("lugar") == "CYH":
            break
        salida.append(d["fecha"])
    return salida


def desde_auto(ctx, maquina, campo, hasta=None):
    """"Desde" automatico: dia en que la maquina llego a su campo actual segun
    el GPS (estadia actual; solo los dias del tablero de la flota)."""
    if not campo or pl.normalizar(campo) in ("taller", "cyh"):
        return ""
    dias = estadia(ctx, maquina, campo, hasta or ctx.fa)
    return min(dias) if dias else ""


def parecidos(nombres, distintos):
    """[(nuevo, conocido)] de nombres que se parecen sin ser el mismo."""
    salida, vistos = [], set()
    lista = sorted(nombres)
    for i, a in enumerate(lista):
        for b in lista[i + 1:]:
            ka, kb = clave(a), clave(b)
            if not ka or not kb or ka == kb or (ka, kb) in distintos or (kb, ka) in distintos:
                continue
            ta, tb = ka.split(), kb.split()
            mismo_nombre = ta[0] == tb[0] and (len(ta) == 1 or len(tb) == 1 or ta[1][:1] == tb[1][:1])
            if mismo_nombre or difflib.SequenceMatcher(None, ka, kb).ratio() >= PARECIDO_MINIMO:
                par = tuple(sorted((a, b), key=len))
                if par not in vistos:
                    vistos.add(par)
                    salida.append({"nombre": par[0], "parecido_a": par[1]})
    return salida


def construir(ctx, oper):
    """Datos de la pestana Operadores (reporte_v2.json -> v2.operadores)."""
    import reporte_v2 as rv
    mapa = mapa_canonico()
    historial = cargar()["dias"]
    ayer = ctx.fa

    # (maquina, fecha) -> (operador, exacto)
    asignado = {}
    for fecha, maquinas in historial.items():
        for m, x in maquinas.items():
            asignado[(m, fecha)] = (canonico(x["operador"], mapa), True)
    # Dias sin lectura entre dos lecturas con el mismo operador en la maquina
    # (ej. 23 al 25-oct-2026, antes del Worker nuevo): ese operador, aproximado.
    fechas = sorted(historial)
    for a, b in zip(fechas, fechas[1:]):
        da, db = date.fromisoformat(a), date.fromisoformat(b)
        if (db - da).days > 31:
            continue
        for m, x in historial[a].items():
            y = historial[b].get(m)
            if y and canonico(x["operador"], mapa) == canonico(y["operador"], mapa):
                for k in range(1, (db - da).days):
                    asignado.setdefault((m, (da + timedelta(days=k)).isoformat()), (canonico(x["operador"], mapa), False))
    # "Desde" (regla del usuario 26-oct-2026): los dias desde la llegada al campo
    # (la fecha puesta a mano en la pagina Operacion o, si no, la automatica del
    # GPS) hasta ayer son del operador actual (aproximado si no hay foto del dia).
    for m, f in ctx.planilla.get("maquinas", {}).items():
        op = canonico(f.get("operador"), mapa)
        if not op or f.get("en_cyh"):
            continue
        desde = f.get("desde") or desde_auto(ctx, m, f["campo"])
        if not desde:
            continue
        dia = date.fromisoformat(desde)
        while dia.isoformat() <= ayer:
            asignado.setdefault((m, dia.isoformat()), (op, False))
            dia += timedelta(days=1)

    # Jornadas por maquina y dia: ha (historial), cuarteles, horas (tablero de la flota).
    jornadas = {}
    for r in ctx.historico:
        if r["fecha"] > ayer or r["maquina"] in rv.NO_CYH or r["area_trabajada_ha"] <= 0:
            continue
        j = jornadas.setdefault((r["maquina"], r["fecha"]), {"ha": 0.0, "cuarteles": {}, "labor": None, "horas": 0.0})
        j["ha"] += r["area_trabajada_ha"]
        j["cuarteles"][r["cuartel"]] = j["cuarteles"].get(r["cuartel"], 0) + r["area_trabajada_ha"]
        j["labor"] = rv.labor_visible(r["labor"], r["fecha"])
    for m in ctx.flota.get("maquinas", []):
        if m["nombre"] in rv.NO_CYH:
            continue
        for d in m.get("dias", []):
            if d["fecha"] > ayer:
                continue
            h = sum((d.get("horas_geocercas") or {}).values())
            h_sin = sum(x.get("horas", 0) for x in d.get("sin_geocerca") or [])
            if h + h_sin < 0.1:
                continue
            j = jornadas.setdefault((m["nombre"], d["fecha"]), {"ha": 0.0, "cuarteles": {}, "labor": None, "horas": 0.0})
            j["horas"] = h
            j["horas_sin"] = h_sin
            for g in d.get("horas_geocercas") or {}:
                j["cuarteles"].setdefault(g, 0.0)
    # Hectareas estimadas sin geocerca del dia (horas x rendimiento real, sin_geocerca.json).
    for t in ctx.sin_geo:
        if t["fecha"] > ayer or t["maquina"] in rv.NO_CYH or t.get("estado") == "ninguno":
            continue
        j = jornadas.setdefault((t["maquina"], t["fecha"]), {"ha": 0.0, "cuarteles": {}, "labor": None, "horas": 0.0})
        j["ha_sin"] = j.get("ha_sin", 0.0) + (t.get("ha") or 0.0)
    unidades = ctx.unidades

    filas_op = []   # jornadas con operador
    sin_operador = []
    for (m, fecha), j in sorted(jornadas.items(), key=lambda x: x[0][1]):
        if j["ha"] <= 0 and j.get("ha_sin", 0) <= 0 and j["horas"] + j.get("horas_sin", 0) < HORAS_DIA_TRABAJADO:
            continue  # no es dia trabajado: no cuenta en los promedios
        labor = j["labor"] or rv.labor_visible(rh.labor_de(unidades[m]) if m in unidades else "", fecha)
        temporada = etiqueta_temporada(labor, date.fromisoformat(fecha))
        campos = sorted({rv.CAMPO(c) for c in j["cuarteles"]})
        fila = {"fecha": fecha, "maquina": m, "labor": labor, "temporada": temporada, "campos": campos,
                "cuarteles": [{"cuartel": c, "ha": round(h, 2)} for c, h in sorted(j["cuarteles"].items())],
                "horas": round(j["horas"], 1), "ha": round(j["ha"], 2), "ha_sin": round(j.get("ha_sin", 0.0), 1)}
        op = asignado.get((m, fecha))
        if op:
            filas_op.append({**fila, "operador": op[0], "exacto": op[1]})

    # Promedios de todos los operadores por labor y temporada.
    todos = {}
    for f in filas_op:
        t = todos.setdefault((f["labor"], f["temporada"]), {"ha": 0.0, "horas": 0.0, "ha_con_horas": 0.0, "dias": 0})
        t["ha"] += f["ha"] + f["ha_sin"]; t["dias"] += 1
        if f["horas"]:
            t["horas"] += f["horas"]; t["ha_con_horas"] += f["ha"]
    promedio = {k: {"ha_dia": round(v["ha"] / v["dias"], 2) if v["dias"] else None,
                    "ha_hora": round(v["ha_con_horas"] / v["horas"], 2) if v["horas"] else None} for k, v in todos.items()}

    # Hoy segun la planilla (maquina, implemento, campo) y estado.
    estado_maq = {f["maquina"]: f for f in oper["filas"]}
    hoy = {}
    for m, f in ctx.planilla.get("maquinas", {}).items():
        op = canonico(f.get("operador"), mapa)
        if not op:
            continue
        g = ctx.gps(m)
        fo = estado_maq.get(m, {})
        if f.get("en_cyh") or g["lugar"] == "CYH":
            estado = "en CYH"
        elif g["dias_sin_senal"] is not None and g["dias_sin_senal"] >= 1:
            estado = "sin señal"
        elif fo.get("ayer_trabajo"):
            estado = "trabajó ayer"
        else:
            estado = "no trabajó ayer"
        hoy.setdefault(op, []).append({"maquina": m, "implemento": f.get("implemento", ""), "campo": f.get("campo", ""),
                                       "estado": estado, "nombre_planilla": f.get("operador", "").strip()})

    # Aviso: maquina fuera de CYH trabajando sin operador anotado.
    for f in oper["filas"]:
        p = ctx.planilla.get("maquinas", {}).get(f["maquina"]) or {}
        if not (p.get("operador") or "").strip() and f.get("gps") != "CYH" and f.get("ayer_trabajo"):
            sin_operador.append({"maquina": f["maquina"], "campo_planilla": f.get("campo_planilla", "")})

    nombres = {f["operador"] for f in filas_op} | set(hoy)
    for dia in historial.values():
        nombres |= {canonico(x["operador"], mapa) for x in dia.values()}
    distintos = {tuple(sorted((clave(a), clave(b)))) for a, b in rh.CONFIG.get("operadores_distintos", [])}

    lista = []
    for op in sorted(nombres, key=lambda x: pl.normalizar(x)):
        mias = [f for f in filas_op if f["operador"] == op]
        grupos = {}
        for f in mias:
            g = grupos.setdefault((f["labor"], f["temporada"]), {"maquinas": set(), "campos": set(), "dias": 0, "horas": 0.0,
                                                                  "ha": 0.0, "ha_sin": 0.0, "ha_con_horas": 0.0, "aproximado": False})
            g["maquinas"].add(f["maquina"]); g["campos"].update(f["campos"]); g["dias"] += 1
            g["ha"] += f["ha"]; g["ha_sin"] += f["ha_sin"]; g["aproximado"] |= not f["exacto"]
            if f["horas"]:
                g["horas"] += f["horas"]; g["ha_con_horas"] += f["ha"]
        labores = []
        for (labor, temporada), g in sorted(grupos.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True):
            labores.append({"labor": labor, "temporada": temporada, "maquinas": sorted(g["maquinas"], key=rh.orden_flota),
                            "campos": sorted(g["campos"]), "dias": g["dias"], "horas": round(g["horas"], 1), "ha": round(g["ha"], 2),
                            "ha_sin": round(g["ha_sin"], 1),
                            # ha/dia por DIAS TRABAJADOS (con ~ha sin geocerca); ha/hora solo en geocercas.
                            "ha_dia": round((g["ha"] + g["ha_sin"]) / g["dias"], 2) if g["dias"] else None,
                            "ha_hora": round(g["ha_con_horas"] / g["horas"], 2) if g["horas"] else None,
                            "aproximado": g["aproximado"], "promedio_todos": promedio.get((labor, temporada))})
        otros = sorted({o for k, v in rh.CONFIG.get("equivalencias_operadores", {}).items() if k == op for o in v})
        lista.append({"operador": op, "otros_nombres": otros, "hoy": hoy.get(op, []), "labores": labores,
                      "ultimos": [{k: f[k] for k in ("fecha", "maquina", "labor", "campos", "cuarteles", "horas", "ha", "ha_sin", "exacto")}
                                  for f in sorted(mias, key=lambda f: f["fecha"], reverse=True)[:DIAS_ULTIMOS]]})
    return {"lista": lista, "sin_operador": sin_operador, "parecidos": parecidos(nombres, distintos),
            "desde_exacto": min(historial) if historial else None,
            "equivalencias": rh.CONFIG.get("equivalencias_operadores", {})}
