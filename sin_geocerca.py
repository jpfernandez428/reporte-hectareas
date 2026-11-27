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
# Pasadas (lineas inicio-fin) de cada trabajo sin geocerca, para el mapa del informe
# (pedido del usuario 26-nov-2026). Archivo aparte para no agrandar sin_geocerca.json.
RUTA_PASADAS = os.path.join(rh.CARPETA_DATOS, "sin_geocerca_pasadas.json")


def clave_pasadas(t):
    return f"{t['fecha']}|{t['maquina']}|{round(t['lat'], 4)}|{round(t['lon'], 4)}"


def guardar_pasadas(alertas, trabajos):
    """Agrega las lineas de las alertas vigentes a sin_geocerca_pasadas.json, sin
    borrar las ya guardadas (solo las de trabajos que siguen en el historial).
    Nunca hace fallar la corrida."""
    try:
        previas = {}
        if os.path.exists(RUTA_PASADAS):
            with open(RUTA_PASADAS, "r", encoding="utf-8") as f:
                previas = json.load(f)
        for a in alertas:
            if isinstance(a.get("trazos"), list) and a["trazos"]:
                previas[clave_pasadas(a)] = a["trazos"]
        vigentes = {clave_pasadas(t) for t in trabajos}
        salida = {k: v for k, v in sorted(previas.items()) if k in vigentes}
        with open(RUTA_PASADAS, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Pasadas sin geocerca: {len(salida)} trabajos con lineas guardadas.")
    except Exception as e:
        print(f"No se pudieron guardar las pasadas sin geocerca ({e}).")
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


# ---------------------------------------------------------------------------
# Campo segun la pagina Operacion (reglas del usuario 26-nov-2026):
#  1. Lugar confirmado a mano (regla del lugar) manda sobre todo.
#  2. Campo anotado en Operacion ese dia y el GPS calza (trabajo a menos de 2 km
#     del campo): ese campo.
#  3. Traslado: si no calza, otro campo anotado 1 o 2 dias antes o despues con
#     el que el GPS si calza: ese otro.
#  4. Si no calza con ninguno: el campo de Operacion de ese dia, con la alerta
#     "GPS no calza con Operacion" (salvo que la ubicacion del campo sea solo
#     aprendida y aun no confirmada, o no se conozca).
#  5. Sin campo en Operacion ese dia: la regla anterior (asignado / probable con
#     una sola opcion); si con eso no hay campo, un campo anotado 1 o 2 dias antes
#     o despues con el que el GPS calza.
# Solo desde que existe la foto diaria de Operacion (22-oct-2026); antes, la
# regla anterior. Ubicacion de un campo sin geocerca: lugares confirmados; si no
# hay, la "aprendida" = donde trabajaron la mayoria de los dias anotados en ese
# campo (se muestra en la pagina para confirmarla).
# ---------------------------------------------------------------------------
FECHA_OPERACION = rh.CONFIG.get("fecha_inicio_operacion", "2026-10-22")
DIAS_TRASLADO = 2


def ubicaciones_aprendidas(trabajos, operacion, canon, con_geocerca, confirmadas):
    """{campo: {campo, lon, lat, trabajos, de}} para campos sin geocerca ni lugar
    confirmado: el grupo de trabajos (a menos de 2 km entre si) que reune a la
    mayoria de los trabajos anotados en ese campo en Operacion."""
    por_campo = {}
    for t in trabajos:
        if t.get("estado") == "resuelto" or t["fecha"] < FECHA_OPERACION:
            continue
        op = operacion.get((t["maquina"], t["fecha"]))
        if not op:
            continue
        c = canon(op)
        if c in con_geocerca or pl_normalizar(c) in confirmadas:
            continue
        por_campo.setdefault(c, []).append((t["lon"], t["lat"]))
    salida = {}
    for c, puntos in por_campo.items():
        mejor = max(puntos, key=lambda p: sum(1 for q in puntos if distancia_m(p, q) <= DISTANCIA_CAMPO_M))
        grupo = [q for q in puntos if distancia_m(mejor, q) <= DISTANCIA_CAMPO_M]
        if len(grupo) >= 2 and 2 * len(grupo) > len(puntos):
            salida[c] = {"campo": c, "lon": round(sum(q[0] for q in grupo) / len(grupo), 6),
                         "lat": round(sum(q[1] for q in grupo) / len(grupo), 6),
                         "trabajos": len(grupo), "de": len(puntos)}
    return salida


def campos_vecinos_operacion(operacion, maquina, fecha, excepto=None):
    """Campos anotados en Operacion para la maquina 1 y 2 dias antes/despues,
    del dia mas cercano al mas lejano (sin repetir ni el de ese dia)."""
    dia, vistos = date.fromisoformat(fecha), []
    for k in (1, -1, 2, -2)[:2 * DIAS_TRASLADO]:
        c = operacion.get((maquina, (dia + timedelta(days=k)).isoformat()))
        if c and c != excepto and c not in vistos:
            vistos.append(c)
    return vistos


# ---------------------------------------------------------------------------
# Traslados (reglas del usuario 26-nov-2026): con el GPS se detecta el dia real en
# que cada maquina cambio de lugar y se compara con el dia en que cambio el campo
# anotado en Operacion.
#  - Lugar de cada dia: el campo donde trabajo mas horas (en geocerca, o sin geocerca
#    ubicado por cercania); si no trabajo, donde termino el dia. CYH es un lugar.
#  - Campo conocido -> otro campo distinto = traslado, aunque esten cerca. Entre
#    lugares sin campo conocido, solo si estan a mas de 5 km.
#  - CYH en el medio (campo -> CYH -> campo) son dos traslados solo si se queda en CYH
#    un dia completo o mas; si no, es un solo traslado.
#  - Fecha segun GPS: el primer dia en el lugar nuevo (o el dia anterior si ya termino
#    ese dia ahi). Con dias sin senal entre medio: "fecha incierta (sin senal)", sin alerta.
#  - Alerta si la fecha del GPS y la de Operacion difieren en mas de 2 dias, o si hubo
#    traslado segun el GPS y Operacion no cambio (o al reves).
# ---------------------------------------------------------------------------
DISTANCIA_TRASLADO_M = 5000
DIAS_ESPERA_OPERACION = 7   # dias para que el GPS lleve la maquina al campo de Operacion (y viceversa)


def punto_de_mapa(url):
    try:
        lat, lon = url.split("q=")[1].split(",")[:2]
        return (float(lon), float(lat))
    except Exception:
        return None


def fechas_operacion():
    """Dias que tienen foto de Operacion (una maquina sin campo anotado no sale ese dia)."""
    try:
        with open(os.path.join(rh.CARPETA_DATOS, "operadores.json"), "r", encoding="utf-8") as f:
            return sorted(json.load(f).get("dias", {}))
    except Exception:
        return []


def cambios_operacion(operacion, maquina, fechas):
    """[(dia, antes, ahora)] de la maquina en Operacion. Sin campo anotado: si antes tenia un
    campo, se toma como paso a CYH (Taller); si nunca tuvo, None. Un cambio es pasar a otro
    valor que no sea None (de None a un campo cuenta como cambio a ese campo)."""
    salida, previo = [], None
    for i, f in enumerate(fechas):
        v = operacion.get((maquina, f))
        estado = v if v is not None else ("CYH" if previo is not None else None)
        if i and estado is not None and estado != previo:
            salida.append((f, previo, estado))
        previo = estado
    return salida


def operacion_completa(canon):
    """{(maquina, fecha): campo o "CYH"} de la foto diaria de Operacion (Taller = CYH)."""
    try:
        with open(os.path.join(rh.CARPETA_DATOS, "operadores.json"), "r", encoding="utf-8") as f:
            dias = json.load(f).get("dias", {})
    except Exception:
        return {}
    eq = {pl_normalizar(k): v for k, v in rh.CONFIG.get("equivalencias_campos", {}).items()}
    salida = {}
    for fecha, maquinas in dias.items():
        for m, x in maquinas.items():
            c = (x.get("campo") or "").strip()
            if not c:
                continue
            if pl_normalizar(c) in ("taller", "cyh", "taller (cyh)"):
                salida[(m, fecha)] = "CYH"
                continue
            w = eq.get(pl_normalizar(c))
            salida[(m, fecha)] = canon(w[0] if w and len(w) == 1 else c)
    return salida


def aplicar_traslados_confirmados(operacion, canon):
    """Estadias confirmadas a mano por el usuario (config.json -> traslados_confirmados:
    maquina, campo, desde, hasta): esos dias el campo de la maquina es ese, por sobre lo
    anotado en Operacion (ej. Tractor 10 en Ferbas del 16 al 20-11-2026)."""
    for c in rh.CONFIG.get("traslados_confirmados", []):
        try:
            dia, fin = date.fromisoformat(c["desde"]), date.fromisoformat(c["hasta"])
        except Exception:
            continue
        while dia <= fin:
            operacion[(c["maquina"], dia.isoformat())] = canon(c["campo"])
            dia += timedelta(days=1)
    return operacion


def detectar_traslados(flota, operacion, ubicar, geos, estadias=None, ubicado=None):
    """Lista de traslados por maquina (ultimos dias del tablero) comparados con Operacion.
    Regla del usuario (26-nov-2026): la fecha real del traslado es la del GPS; Operacion
    solo dice a que campo va (se puede cambiar antes o despues). Alerta solo si el GPS la
    lleva a un campo distinto del de Operacion, si se movio y Operacion nunca cambio, o si
    a los 7 dias de cambiar Operacion el GPS aun no la lleva a ese campo. Deja en
    `estadias` donde estuvo fisicamente cada maquina."""
    estadias = {} if estadias is None else estadias
    ubicado = ubicado or (lambda c: False)
    hoy = max((d["fecha"] for mm in flota.get("maquinas", []) for d in mm.get("dias", [])), default="")
    def lugar_de_punto(p):
        for g in geos.values():
            x1, y1, x2, y2 = g["bbox"]
            if x1 <= p[0] <= x2 and y1 <= p[1] <= y2 and rh.punto_en_poligono(p, g["contorno"]):
                return ("campo", campo_de(g["nombre"]), p)
        c = ubicar(p)
        return ("campo", c, p) if c else ("punto", None, p)

    def lugar_del_dia(d):
        if d.get("sin_datos"):
            return None
        horas = {}
        for g, h in (d.get("horas_geocercas") or {}).items():
            if h >= 0.1 and g in geos:
                c = geos[g]["contorno"][0]
                k = ("campo", campo_de(g))
                horas.setdefault(k, [0.0, c])[0] += h
        for x in d.get("sin_geocerca") or []:
            p = punto_de_mapa(x.get("mapa", ""))
            if not p:
                continue
            tipo, nombre, _ = lugar_de_punto(p)
            k = (tipo, nombre) if nombre else ("punto", round(p[0], 2), round(p[1], 2))
            horas.setdefault(k, [0.0, p])[0] += x.get("horas") or 0
        fin = d.get("fin") or {}
        p_fin = (fin["lon"], fin["lat"]) if fin.get("lon") is not None else None
        if fin.get("lugar") == "CYH":
            l_fin = ("cyh", "CYH", p_fin)
        elif p_fin:
            l_fin = lugar_de_punto(p_fin)
        else:
            l_fin = None
        if horas:
            k = max(horas, key=lambda x: horas[x][0])
            l = ("campo", k[1], horas[k][1]) if k[0] == "campo" else ("punto", None, horas[k][1])
        else:
            l = l_fin
        return {"lugar": l, "fin": l_fin}

    def mismo(a, b):
        if a is None or b is None:
            return True
        if a[0] == "cyh" or b[0] == "cyh":
            return a[0] == b[0]
        if a[0] == "campo" and b[0] == "campo":
            return pl_normalizar(a[1]) == pl_normalizar(b[1])
        return distancia_m(a[2], b[2]) <= DISTANCIA_TRASLADO_M

    def nombre(l):
        return "CYH" if l[0] == "cyh" else (l[1] if l[0] == "campo" else "lugar sin campo conocido")

    salida = []
    fechas_op_todas = fechas_operacion()
    for m in flota.get("maquinas", []):
        dias = sorted(m.get("dias", []), key=lambda d: d["fecha"])
        cambios_m = cambios_operacion(operacion, m["nombre"], fechas_op_todas)
        if not dias:
            continue
        secuencia = [(d["fecha"], lugar_del_dia(d)) for d in dias]
        # Tramos de dias seguidos en el mismo lugar (los dias sin senal no cortan el tramo).
        tramos = []
        for i, (fecha, info) in enumerate(secuencia):
            if info is None or info["lugar"] is None:
                if tramos:
                    tramos[-1]["sin_senal_despues"] = True
                continue
            l = info["lugar"]
            if tramos and mismo(tramos[-1]["lugar"], l):
                tramos[-1]["hasta"] = fecha
                tramos[-1]["sin_senal_despues"] = False
                continue
            # Llego el dia anterior si ese dia ya termino en el lugar nuevo.
            llegada = fecha
            if i > 0 and secuencia[i - 1][1] and secuencia[i - 1][1]["fin"] is not None \
                    and mismo(secuencia[i - 1][1]["fin"], l) and secuencia[i - 1][0] > (tramos[-1]["desde"] if tramos else ""):
                llegada = secuencia[i - 1][0]
            incierta = bool(tramos and tramos[-1].get("sin_senal_despues"))
            tramos.append({"lugar": l, "desde": fecha, "hasta": fecha, "llegada": llegada, "incierta": incierta,
                           "sin_senal_despues": False})
        # CYH en el medio sin un dia completo: un solo traslado (se salta el tramo de CYH).
        limpios = []
        for t in tramos:
            if t["lugar"][0] == "cyh" and t["desde"] == t["hasta"] and limpios:
                t["paso_por_cyh"] = True
            limpios.append(t)
        reales = []
        for i, t in enumerate(limpios):
            if t.get("paso_por_cyh") and 0 < i < len(limpios) - 1:
                continue
            if reales and mismo(reales[-1]["lugar"], t["lugar"]):
                reales[-1]["hasta"] = t["hasta"]
                continue
            reales.append(t)
        # Estadias segun el GPS (donde esta fisicamente cada dia): manda sobre Operacion.
        estadias[m["nombre"]] = [{"lugar": nombre(t["lugar"]), "tipo": t["lugar"][0], "desde": t["llegada"] if k else t["desde"],
                                  "hasta": t["hasta"], "desde_inicio": k == 0} for k, t in enumerate(reales)]
        # Operacion de cada dia (sin campo anotado despues de tener uno = CYH).
        op_dia, previo = {}, None
        for f in fechas_op_todas:
            v = operacion.get((m["nombre"], f))
            previo = v if v is not None else ("CYH" if previo is not None else None)
            op_dia[f] = previo
        con_operacion = any(v is not None for v in op_dia.values())
        sin_senal_en = lambda f1, f2: any(info is None for fecha, info in secuencia if f1 <= fecha <= f2)
        mas = lambda f, n: (date.fromisoformat(f) + timedelta(days=n)).isoformat()
        for k, (a, b) in enumerate(zip(reales, reales[1:])):
            fecha_gps, destino, origen = b["llegada"], nombre(b["lugar"]), nombre(a["lugar"])
            # Operacion puede cambiar antes (varios dias) o despues: se mira desde el traslado
            # anterior hasta 7 dias despues de este.
            ini = reales[k]["llegada"] if k else mas(fecha_gps, -30)
            fin_v = min(mas(fecha_gps, DIAS_ESPERA_OPERACION), hoy)
            ventana = [(f, v) for f, v in sorted(op_dia.items()) if ini <= f <= fin_v and v is not None]
            iguales = [f for f, v in ventana if pl_normalizar(v) == pl_normalizar(destino)]
            fecha_op = None
            if iguales:
                # Dia en que Operacion paso a ese destino: inicio de la racha mas cercana al GPS.
                rachas, todas_f = [], [f for f, _ in ventana]
                for f in iguales:
                    if rachas and todas_f.index(f) == todas_f.index(rachas[-1][-1]) + 1:
                        rachas[-1].append(f)
                    else:
                        rachas.append([f])
                dist = lambda r: 0 if r[0] <= fecha_gps <= r[-1] else min(abs((date.fromisoformat(x) - date.fromisoformat(fecha_gps)).days) for x in (r[0], r[-1]))
                fecha_op = min(rachas, key=dist)[0]
            distintos = [v for f, v in ventana if pl_normalizar(v) not in (pl_normalizar(origen), pl_normalizar(destino))]
            alerta = None
            if b["incierta"] or not con_operacion or fecha_gps < FECHA_OPERACION:
                alerta = None
            elif b["lugar"][0] == "punto":
                if not distintos and not iguales and fin_v >= mas(fecha_gps, DIAS_ESPERA_OPERACION):
                    alerta = "se movió según el GPS y en Operación nunca cambió el campo"
            elif not iguales:
                if distintos:
                    dice = op_dia.get(fecha_gps) or distintos[-1]
                    alerta = f"el GPS la lleva a {destino}, pero Operación dice {dice}"
                elif fin_v >= mas(fecha_gps, DIAS_ESPERA_OPERACION):
                    alerta = "se movió según el GPS y en Operación nunca cambió el campo"
            salida.append({"maquina": m["nombre"], "desde_lugar": origen, "hacia": destino,
                           "fecha_gps": fecha_gps, "fecha_operacion": fecha_op, "incierta": b["incierta"],
                           "alerta": alerta,
                           "punto": [round(b["lugar"][2][0], 6), round(b["lugar"][2][1], 6)] if b["lugar"][2] else None})
        # Operacion cambio a X y a los 7 dias el GPS aun no la lleva a X.
        conocidos = lambda x: x == "CYH" or ubicado(x)
        for f, antes, ahora in cambios_m:
            if f < max(dias[0]["fecha"], FECHA_OPERACION) or mas(f, DIAS_ESPERA_OPERACION) > hoy:
                continue
            fin_v = mas(f, DIAS_ESPERA_OPERACION)
            if conocidos(ahora):
                llego = any(pl_normalizar(e["lugar"]) == pl_normalizar(ahora) and e["desde"] <= fin_v and e["hasta"] >= f
                            for e in estadias[m["nombre"]])
            else:  # campo sin ubicacion conocida: basta que el GPS la lleve a algun lugar sin campo conocido
                llego = any(e["tipo"] == "punto" and e["desde"] <= fin_v and e["hasta"] >= f for e in estadias[m["nombre"]])
            if llego or sin_senal_en(f, fin_v):
                continue
            if any(t["maquina"] == m["nombre"] and t.get("alerta") and t["fecha_gps"]
                   and mas(f, -DIAS_ESPERA_OPERACION) <= t["fecha_gps"] <= fin_v for t in salida):
                continue  # ya hay una alerta de ese traslado
            donde = next((e["lugar"] for e in reversed(estadias[m["nombre"]]) if e["desde"] <= fin_v), "otro lugar")
            salida.append({"maquina": m["nombre"], "desde_lugar": antes or "—", "hacia": ahora, "fecha_gps": None,
                           "fecha_operacion": f, "incierta": False,
                           "alerta": f"Operación dice {ahora} pero la máquina no ha llegado (sigue en {donde})",
                           "punto": None})
    return sorted(salida, key=lambda t: (t["fecha_gps"] or t["fecha_operacion"], t["maquina"]))



def unir_traslados(previos, nuevos):
    """Los traslados de los dias del tablero se recalculan; los anteriores se conservan."""
    desde = min((t["fecha_gps"] or t["fecha_operacion"] for t in nuevos), default=None)
    viejos = [t for t in previos if desde and (t.get("fecha_gps") or t.get("fecha_operacion")) < desde]
    return viejos + nuevos

def operacion_segun_traslados(operacion, estadias):
    """Mientras el GPS no la mueva, la maquina sigue en el campo donde esta fisicamente:
    en los dias de una estadia en un campo conocido, el campo es ese (aunque Operacion ya
    diga otro); en CYH no hay campo; en un lugar sin campo conocido, el de Operacion."""
    ajustada = dict(operacion)
    for maquina, lista in estadias.items():
        for e in lista:
            dia, fin = date.fromisoformat(e["desde"]), date.fromisoformat(e["hasta"])
            while dia <= fin:
                f = dia.isoformat()
                if e["tipo"] == "campo":
                    ajustada[(maquina, f)] = e["lugar"]
                elif e["tipo"] == "cyh":
                    ajustada.pop((maquina, f), None)
                dia += timedelta(days=1)
    return ajustada


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
    previos, previos_traslados = [], []
    if os.path.exists(RUTA):
        with open(RUTA, "r", encoding="utf-8") as f:
            guardado = json.load(f)
            previos, previos_traslados = guardado.get("trabajos", []), guardado.get("traslados", [])
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
    # Nombre del campo como en Wialon (sin mayusculas ni tildes) o tal cual si no tiene geocerca.
    canon_geo = {pl_normalizar(c): c for c in cuarteles_por_campo}
    canon = lambda c: canon_geo.get(pl_normalizar(c), c)
    operacion = {k: canon(v) for k, v in operacion.items()}
    confirmadas = {}
    for r in rh.CONFIG.get("lugares_confirmados", []):
        if r.get("campo") and not r.get("resuelto"):
            confirmadas.setdefault(pl_normalizar(canon(r["campo"])), []).append((r["lon"], r["lat"]))
    aprendidas = ubicaciones_aprendidas(por_clave.values(), operacion, canon, cuarteles_por_campo, confirmadas)

    def ubicar(punto):
        """Campo conocido mas cercano a menos de 2 km (cuartel, lugar confirmado o aprendida)."""
        opciones = {c: d for c, (d, _) in campos_cercanos(punto, cuarteles_por_campo).items()}
        for c, lugares in confirmadas.items():
            for q in lugares:
                dd = distancia_m(punto, q)
                if dd <= DISTANCIA_CAMPO_M:
                    nombre = next((r["campo"] for r in rh.CONFIG.get("lugares_confirmados", [])
                                   if r.get("campo") and pl_normalizar(canon(r["campo"])) == c), c)
                    opciones[canon(nombre)] = min(dd, opciones.get(canon(nombre), dd))
        for c, a in aprendidas.items():
            dd = distancia_m(punto, (a["lon"], a["lat"]))
            if dd <= DISTANCIA_CAMPO_M:
                opciones[c] = min(dd, opciones.get(c, dd))
        return min(opciones, key=opciones.get) if opciones else None

    # Traslados segun el GPS comparados con Operacion; el dia real del traslado manda.
    traslados, estadias = [], {}
    try:
        ubicado = lambda c: c in cuarteles_por_campo or pl_normalizar(c) in confirmadas or c in aprendidas
        op_confirmada = aplicar_traslados_confirmados(operacion_completa(canon), canon)
        traslados = detectar_traslados(flota, op_confirmada, ubicar, geos, estadias, ubicado)
        operacion = {k: v for k, v in operacion_segun_traslados(op_confirmada, estadias).items() if v != "CYH"}
    except Exception as e:
        print(f"No se pudieron detectar los traslados ({e}).")

    def calza(punto, campo):
        """El GPS calza con el campo: trabajo a menos de 2 km de un cuartel del campo o
        de su ubicacion conocida (lugar confirmado o aprendida). None = no se sabe."""
        if campo in cuarteles_por_campo:
            return campo in campos_cercanos(punto, {campo: cuarteles_por_campo[campo]})
        lugares = confirmadas.get(pl_normalizar(campo)) or ([(aprendidas[campo]["lon"], aprendidas[campo]["lat"])] if campo in aprendidas else [])
        if not lugares:
            return None
        return any(distancia_m(punto, q) <= DISTANCIA_CAMPO_M for q in lugares)

    def alerta_posible(campo):
        """Solo hay alerta si la ubicacion del campo es segura (geocerca o lugar confirmado)."""
        return campo in cuarteles_por_campo or pl_normalizar(campo) in confirmadas

    for t in por_clave.values():
        if t.get("estado") == "resuelto":
            continue
        for k in ("segun_operacion", "gps_no_calza", "traslado", "ubicacion_aprendida"):
            t.pop(k, None)
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
        if t["fecha"] >= FECHA_OPERACION:
            campo_op = operacion.get((t["maquina"], t["fecha"]))
            elegido = None
            if campo_op:
                if calza(punto, campo_op) is not False:
                    elegido = campo_op
                else:
                    otro = next((c for c in campos_vecinos_operacion(operacion, t["maquina"], t["fecha"], campo_op)
                                 if calza(punto, c)), None)
                    if otro:
                        elegido, t["traslado"] = otro, True
                    else:
                        elegido = campo_op
                        if alerta_posible(campo_op):
                            t["gps_no_calza"] = True
            elif not t.get("campo"):
                elegido = next((c for c in campos_vecinos_operacion(operacion, t["maquina"], t["fecha"])
                                if calza(punto, c)), None)
                if elegido:
                    t["traslado"] = True
            if elegido:
                t["campo"], t["estado"], t["segun_operacion"] = elegido, "asignado", True
                if elegido in aprendidas:
                    t["ubicacion_aprendida"] = True
        # Antes de la foto diaria de Operacion: el campo de Operacion ese dia es el probable.
        elif t["estado"] in ("sin campo", "probable") and not t.get("campo"):
            campo_op = operacion.get((t["maquina"], t["fecha"]))
            if campo_op:
                t["campo"], t["estado"], t["segun_operacion"] = campo_op, "probable", True
    trabajos = sorted(por_clave.values(), key=lambda t: (t["fecha"], t["maquina"]))
    guardar_pasadas(alertas, trabajos)
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump({"distancia_campo_km": DISTANCIA_CAMPO_M / 1000, "lugar_m": LUGAR_M,
                   # Direccion del Worker de Cloudflare que recibe las confirmaciones.
                   "url_confirmar": rh.CONFIG.get("url_confirmaciones"),
                   "lugares_confirmados": rh.CONFIG.get("lugares_confirmados", []),
                   # Campos sin geocerca con ubicacion aprendida de Operacion, por confirmar.
                   "ubicaciones_aprendidas": sorted(aprendidas.values(), key=lambda a: a["campo"]),
                   # Traslados del tablero (30 dias) segun el GPS y Operacion, con alertas.
                   "traslados": unir_traslados(previos_traslados, traslados),
                   # Donde estuvo fisicamente cada maquina (30 dias del tablero), para el "Desde".
                   "estadias": estadias,
                   "trabajos": trabajos}, f, ensure_ascii=False, indent=0)
    from collections import Counter
    print(f"Trabajo sin geocerca: {len(trabajos)} registros; "
          f"{dict(Counter(t['estado'] for t in trabajos))}")


if __name__ == "__main__":
    main(con_direcciones="--sin-direcciones" not in sys.argv)
