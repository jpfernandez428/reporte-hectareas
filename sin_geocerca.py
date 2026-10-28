"""
sin_geocerca.py

Trabajo sin geocerca: lo guarda todo (historial acumulado, no solo los
ultimos 30 dias) y lo asigna a un campo. Reglas del usuario (21-oct-2026,
ver CLAUDE.md, "Trabajo sin geocerca por campo"):

  1. Lugar confirmado en la pagina (config.json -> lugares_confirmados, a
     menos de DISTANCIA_MISMO_LUGAR_M): ese campo, "confirmado" (o "ninguno").
  2. Campos con algun cuartel a menos de 2 km del trabajo:
     - la maquina trabajo en un cuartel (con geocerca) de ese campo ese dia,
       o esta entre dos dias en que trabajo ahi sin ir a otro campo ni a CYH:
       "asignado" a ese campo;
     - si no, estadia ampliada: ese dia no trabajo en otro campo ni paso por
       CYH -> "probable". Con dos o mas campos posibles no se elige: quedan
       como opciones ("probable: Aurora o El Volcan") y el usuario elige.
  3. Si no: "sin campo".
Las hectareas son un estimado (horas x rendimiento real de la maquina) y
nunca se suman al total exacto.

Deja docs/datos/sin_geocerca.json (lo lee la pagina). Solo lectura de
Wialon (direcciones, si hay token).
"""

import json
import math
import os
import sys
from datetime import date, timedelta

import reporte_hectareas as rh
import reporte_correo as rc

RUTA = os.path.join(rh.CARPETA_DATOS, "sin_geocerca.json")
DISTANCIA_CAMPO_M = rh.CONFIG.get("distancia_sin_geocerca_campo_m", 2000)
LUGAR_M = rh.DISTANCIA_MISMO_LUGAR_M
UNIDOS = {r: k for k, v in rh.CONFIG.get("campos_unidos", {}).items() for r in v}


def campo_de(nombre_cuartel):
    """Mismo criterio que campoDe() de la pagina (informe.js)."""
    return rh.campo_de_cuartel(nombre_cuartel)


def pl_normalizar(texto):
    import unicodedata
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower().strip()


def distancia_m(a, b):
    return math.hypot(*rh.punto_a_metros(b, a))


def distancia_segmento(p, a, b):
    ax, ay = rh.punto_a_metros(a, p)
    bx, by = rh.punto_a_metros(b, p)
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1.0)))
    return math.hypot(ax + t * dx, ay + t * dy)


def cargar_entrada():
    geos = {}
    with open(rh.RUTA_GEOCERCAS_WEB, "r", encoding="utf-8") as f:
        for nombre, g in json.load(f).items():
            c = [tuple(p) for p in g["contorno"]]
            geos[nombre] = {"nombre": nombre, "contorno": c,
                            "bbox": (min(p[0] for p in c), min(p[1] for p in c),
                                     max(p[0] for p in c), max(p[1] for p in c))}
    with open(rh.RUTA_FLOTA, "r", encoding="utf-8") as f:
        flota = json.load(f)
    with open(rh.RUTA_ESTADO_MAQUINAS, "r", encoding="utf-8") as f:
        alertas = json.load(f).get("alertas", [])
    with open(rh.RUTA_AVANCE_CUARTELES, "r", encoding="utf-8") as f:
        avance = json.load(f).get("cuarteles", {})
    return geos, flota, alertas, rh.cargar_historico(), avance


def campos_cercanos(punto, cuarteles_por_campo):
    """{campo: (distancia_m, cuartel)} de los campos con un cuartel a menos de 2 km."""
    salida = {}
    for campo, cuarteles in cuarteles_por_campo.items():
        for g in cuarteles:
            x1, y1, x2, y2 = g["bbox"]
            if punto[0] < x1 - 0.03 or punto[0] > x2 + 0.03 or punto[1] < y1 - 0.025 or punto[1] > y2 + 0.025:
                continue  # a mas de ~2,5 km
            c = g["contorno"]
            d = 0.0 if rh.punto_en_poligono(punto, c) else min(
                distancia_segmento(punto, c[i], c[(i + 1) % len(c)]) for i in range(len(c)))
            if d < DISTANCIA_CAMPO_M and (campo not in salida or d < salida[campo][0]):
                salida[campo] = (d, g["nombre"])
    return salida


def regla_confirmada(punto):
    for r in rh.CONFIG.get("lugares_confirmados", []):
        if distancia_m(punto, (r["lon"], r["lat"])) <= LUGAR_M:
            return r
    return None


def campo_de_la_operacion():
    """{(maquina, fecha): campo} segun la foto diaria de la pagina Operacion
    (docs/datos/operadores.json; regla del usuario 26-oct-2026: el campo de la
    operacion es el campo probable del trabajo sin geocerca). Los nombres de la
    operacion pasan a Wialon con las equivalencias. Nunca falla: sin foto, {}."""
    try:
        with open(os.path.join(rh.CARPETA_DATOS, "operadores.json"), "r", encoding="utf-8") as f:
            dias = json.load(f).get("dias", {})
        eq = {pl_normalizar(k): v for k, v in rh.CONFIG.get("equivalencias_campos", {}).items()}
        salida = {}
        for fecha, maquinas in dias.items():
            for m, x in maquinas.items():
                campo = (x.get("campo") or "").strip()
                if not campo or pl_normalizar(campo) in ("taller", "cyh"):
                    continue
                wialon = eq.get(pl_normalizar(campo))
                salida[(m, fecha)] = wialon[0] if wialon and len(wialon) == 1 else campo
        return salida
    except Exception as e:
        print(f"Sin foto de la operacion ({e}).")
        return {}


FRACCION_RESUELTO = 0.9   # pasadas dentro de geocercas en uso para "resuelto" completo
FRACCION_PARCIAL = 0.1    # desde aqui, solo queda sin geocerca la parte de afuera


def dentro_de_geocercas(puntos, geos):
    """{geocerca: n de puntos dentro} y total de puntos dentro."""
    cuenta, total = {}, 0
    for lon, lat in puntos:
        for g in geos.values():
            x1, y1, x2, y2 = g["bbox"]
            if x1 <= lon <= x2 and y1 <= lat <= y2 and rh.punto_en_poligono((lon, lat), g["contorno"]):
                cuenta[g["nombre"]] = cuenta.get(g["nombre"], 0) + 1
                total += 1
                break
    return cuenta, total


def resolver(trabajos, geos, hoy, reglas=None):
    """Regla permanente (usuario 28-oct-2026): el trabajo sin geocerca cuyas
    pasadas caen dentro de geocercas en uso (por ejemplo, creadas despues) pasa
    a "resuelto: ahora en <geocerca>" y deja de sumarse en las ~ha estimadas,
    alertas, correo, Operadores, Trabajo por campo y Preguntas (queda como
    registro). Si una geocerca cubre solo una parte, queda sin geocerca solo la
    parte de afuera (horas y ~ha en proporcion). Lo mismo con los lugares
    confirmados que quedaron dentro de una geocerca. Devuelve los cambios."""
    cambios = []
    for t in trabajos:
        if t.get("estado") == "resuelto":
            continue
        puntos = [tuple(p) for p in (t.get("muestras") or [])] or [(t["lon"], t["lat"])]
        cuenta, total = dentro_de_geocercas(puntos, geos)
        f = total / len(puntos)
        if f < FRACCION_PARCIAL:
            continue
        donde = sorted(cuenta, key=lambda g: -cuenta[g])
        if f >= FRACCION_RESUELTO:
            cambios.append(("resuelto", t, donde, f))
            t["estado_anterior"], t["campo_anterior"] = t.get("estado"), t.get("campo")
            t["estado"], t["resuelto_en"], t["fecha_resuelto"] = "resuelto", donde, hoy
        elif not t.get("parte_resuelta") or f > t["parte_resuelta"]:
            cambios.append(("parcial", t, donde, f))
            t.setdefault("ha_original", t["ha"]); t.setdefault("horas_original", t["horas"])
            t["ha"] = round(t["ha_original"] * (1 - f), 2)
            t["horas"] = round(t["horas_original"] * (1 - f), 2)
            t["parte_resuelta"], t["resuelto_en"], t["fecha_resuelto"] = round(f, 2), donde, hoy
    for r in reglas or []:
        if r.get("resuelto"):
            continue
        cuenta, total = dentro_de_geocercas([(r["lon"], r["lat"])], geos)
        if total:
            g = next(iter(cuenta))
            cambios.append(("lugar", r, [g], 1.0))
            r["resuelto"], r["fecha_resuelto"] = f"ya tiene geocerca: {g}", hoy
    return cambios


def main(con_direcciones=True, solo_revisar=False):
    geos, flota, alertas, historico, avance = cargar_entrada()
    cuarteles_por_campo = {}
    for g in geos.values():
        cuarteles_por_campo.setdefault(campo_de(g["nombre"]), []).append(g)
    rend = rc.rendimientos(flota, historico, avance)

    # Campos con trabajo en geocerca por maquina y dia; dias que termino en CYH.
    trabajo, en_cyh = {}, {}
    for m in flota.get("maquinas", []):
        for d in m.get("dias", []):
            trabajo.setdefault((m["nombre"], d["fecha"]), set()).update(
                campo_de(g) for g, h in (d.get("horas_geocercas") or {}).items() if h >= 0.1)
            en_cyh[(m["nombre"], d["fecha"])] = (d.get("fin") or {}).get("lugar") == "CYH"
    for r in historico:
        if r["area_trabajada_ha"] > 0:
            trabajo.setdefault((r["maquina"], r["fecha"]), set()).add(campo_de(r["cuartel"]))

    def en_estadia(maquina, fecha, campo, ventana=10):
        if campo in trabajo.get((maquina, fecha), set()):
            return True
        dia = date.fromisoformat(fecha)
        antes = despues = False
        for k in range(1, ventana + 1):
            f = (dia - timedelta(days=k)).isoformat()
            cs = trabajo.get((maquina, f), set())
            if en_cyh.get((maquina, f)) or (cs and campo not in cs):
                break
            if campo in cs:
                antes = True
                break
        for k in range(1, ventana + 1):
            if en_cyh.get((maquina, (dia + timedelta(days=k - 1)).isoformat())):
                break
            cs = trabajo.get((maquina, (dia + timedelta(days=k)).isoformat()), set())
            if cs and campo not in cs:
                break
            if campo in cs:
                despues = True
                break
        return antes and despues

    def estadia_ampliada(maquina, fecha):
        """Ese dia no trabajo en otro campo ni paso por CYH."""
        return not trabajo.get((maquina, fecha)) and not en_cyh.get((maquina, fecha))

    # Historial acumulado: lo anterior se conserva aunque ya no venga en las alertas.
    previos = []
    if os.path.exists(RUTA):
        with open(RUTA, "r", encoding="utf-8") as f:
            previos = json.load(f).get("trabajos", [])
    por_clave = {(t["fecha"], t["maquina"], round(t["lat"], 4), round(t["lon"], 4)): t for t in previos}
    for a in alertas:
        if not rh.alerta_visible(a) or rh.alerta_resuelta(a, list(geos.values())):
            continue
        clave = (a["fecha"], a["maquina"], round(a["lat"], 4), round(a["lon"], 4))
        ha_h = (rend.get(a["maquina"]) or (None,))[0]
        t = por_clave.get(clave, {})
        if t.get("estado") == "resuelto" or t.get("parte_resuelta"):
            continue  # ya resuelto (o en parte) por una geocerca: no se vuelve a sumar
        t.update({"fecha": a["fecha"], "maquina": a["maquina"], "labor": a["labor"], "lat": a["lat"],
                  "lon": a["lon"], "horas": round(a["horas"], 2), "mapa": a["mapa"],
                  "ha": round(a["horas"] * ha_h, 2) if ha_h else round(a["ha_aprox"], 2),
                  "muestras": [[round(x, 6), round(y, 6)] for x, y in a.get("muestras", [])][:60]})
        por_clave[clave] = t

    operacion = campo_de_la_operacion()
    usuario = None
    if con_direcciones and os.environ.get("WIALON_TOKEN"):
        try:
            _, usuario = rc.login()
        except Exception as e:
            print(f"Sin direcciones de Wialon ({e}).")
    # Pasadas de las alertas aun vigentes para los trabajos guardados sin ellas.
    muestras = {(a["fecha"], a["maquina"], round(a["lat"], 4), round(a["lon"], 4)): a.get("muestras", []) for a in alertas}
    for k, t in por_clave.items():
        if not t.get("muestras") and muestras.get(k):
            t["muestras"] = [[round(x, 6), round(y, 6)] for x, y in muestras[k]][:60]
    from datetime import datetime as _dt
    hoy = _dt.now(rh.ZONA_HORARIA).date().isoformat()
    reglas = [dict(r) for r in rh.CONFIG.get("lugares_confirmados", [])]
    cambios = resolver(list(por_clave.values()), geos, hoy, reglas)
    if solo_revisar:
        return cambios
    if any(c[0] == "lugar" for c in cambios):
        import confirmar
        confirmar.guardar_reglas(reglas)
        rh.CONFIG["lugares_confirmados"] = reglas
    for t in por_clave.values():
        if t.get("estado") == "resuelto":
            continue
        punto = (t["lon"], t["lat"])
        if usuario and not t.get("comuna"):
            t["comuna"] = rc.localidad(rc.direccion(usuario, *punto))
        regla = regla_confirmada(punto)
        if regla and regla.get("resuelto"):
            regla = None  # el lugar ya tiene geocerca
        cercanos = campos_cercanos(punto, cuarteles_por_campo)
        t["opciones"] = sorted(cercanos, key=lambda c: cercanos[c][0])
        t["distancias_km"] = {c: round(cercanos[c][0] / 1000, 1) for c in t["opciones"]}
        if regla:
            t["campo"], t["estado"] = (regla["campo"] or None), ("confirmado" if regla["campo"] else "ninguno")
            continue
        seguros = [c for c in t["opciones"] if en_estadia(t["maquina"], t["fecha"], c)]
        if len(seguros) == 1:
            t["campo"], t["estado"] = seguros[0], "asignado"
        elif t["opciones"] and estadia_ampliada(t["maquina"], t["fecha"]) or len(seguros) > 1:
            posibles = seguros or t["opciones"]
            t["campo"] = posibles[0] if len(posibles) == 1 else None
            t["estado"] = "probable"
            t["opciones"] = posibles
        else:
            t["campo"], t["estado"] = None, "sin campo"
        # Sin campo seguro: el campo de la pagina Operacion ese dia es el probable.
        if t["estado"] in ("sin campo", "probable") and not t.get("campo"):
            campo_op = operacion.get((t["maquina"], t["fecha"]))
            if campo_op:
                t["campo"], t["estado"], t["segun_operacion"] = campo_op, "probable", True
    trabajos = sorted(por_clave.values(), key=lambda t: (t["fecha"], t["maquina"]))
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump({"distancia_campo_km": DISTANCIA_CAMPO_M / 1000, "lugar_m": LUGAR_M,
                   # Direccion del Worker de Cloudflare que recibe las confirmaciones.
                   "url_confirmar": rh.CONFIG.get("url_confirmaciones"),
                   "lugares_confirmados": rh.CONFIG.get("lugares_confirmados", []),
                   "trabajos": trabajos}, f, ensure_ascii=False, indent=0)
    from collections import Counter
    print(f"Trabajo sin geocerca: {len(trabajos)} registros; "
          f"{dict(Counter(t['estado'] for t in trabajos))}")


if __name__ == "__main__":
    main(con_direcciones="--sin-direcciones" not in sys.argv)
