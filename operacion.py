"""
operacion.py

Pagina Operacion (docs/operacion.html), pedido del usuario 26-oct-2026:
reemplaza la planilla del Drive "Maquinas en Operacion". Una fila por maquina
activa: implemento, operador, campo ("Taller" = en CYH; un campo de Wialon o
uno sin geocerca), desde (dia en que llego al campo) y proximo destino.

  - docs/datos/operacion.json          estado actual (unica fuente desde la carga)
  - docs/datos/operacion_cambios.json  historial: fecha y hora, maquina, que
                                       cambio (antes -> despues)
  - docs/datos/operadores.json         foto diaria (operador y campo de cada
                                       maquina cada dia; ver operadores.py)

Uso:
  python3 operacion.py cargar      (UNA vez: copia la planilla del Drive de hoy)
  python3 operacion.py guardar     (CAMBIOS = JSON de la pagina, via el Worker)
Despues de guardar se rearman los datos de reporte2 (reporte_v2.json) con lo
ya publicado, sin bajar GPS de Wialon.
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import planilla as pl
import reporte_hectareas as rh

RUTA = pl.RUTA_OPERACION
RUTA_CAMBIOS = os.path.join(rh.CARPETA_DATOS, "operacion_cambios.json")
# Tiempo de cada guardado (pedido del usuario 26-oct-2026): desde que el Worker
# lo recibe hasta que queda publicado en GitHub Pages. Para decidir si se pasa a
# guardar en Cloudflare (KV).
RUTA_TIEMPOS = os.path.join(rh.CARPETA_DATOS, "operacion_tiempos.json")
URL_PUBLICADA = "https://jpfernandez428.github.io/reporte-hectareas/datos/operacion.json"
CAMPOS_FILA = ("implemento", "operador", "campo", "desde", "destino")
NOMBRES = {"implemento": "Implemento", "operador": "Operador", "campo": "Campo", "desde": "Desde", "destino": "Próximo destino"}


def ahora():
    return datetime.now(rh.ZONA_HORARIA).strftime("%d-%m-%Y %H:%M")


def leer(ruta, defecto):
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    return defecto


def escribir(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def activas():
    """Maquinas activas en el orden fijo de la flota (sin las "No incluir")."""
    return sorted((u["nombre"] for u in rh.UNIDADES), key=rh.orden_flota)


def cargar_desde_drive():
    """Carga UNICA: la planilla del Drive de hoy pasa a operacion.json."""
    if os.path.exists(RUTA):
        sys.exit("operacion.json ya existe: la pagina Operacion ya es la fuente (no se vuelve a cargar el Drive).")
    import reporte_v2 as rv
    import operadores
    nombres = activas()
    plan = pl.cargar(nombres, rh.CONFIG.get("equivalencias_campos", {}), forzar_drive=True)
    if not plan.get("ok"):
        sys.exit(f"No se pudo leer la planilla: {plan.get('aviso')}")
    ayer = datetime.now(rh.ZONA_HORARIA).date() - timedelta(days=1)
    ctx = rv.Contexto(ayer, plan)
    maquinas = {}
    for m in nombres:
        f = plan["maquinas"].get(m)
        if not f:
            maquinas[m] = {k: "" for k in CAMPOS_FILA}
            continue
        campo = "Taller" if f["en_cyh"] else f["campo"].strip()
        desde = ""
        if not f["en_cyh"]:
            dias = operadores.estadia(ctx, m, campo, ayer.isoformat())
            desde = min(dias) if dias else ""
        maquinas[m] = {"implemento": f["implemento"].strip(), "operador": f["operador"].strip(), "campo": campo,
                       "desde": desde, "destino": f["destino"].strip()}
    escribir(RUTA, {"actualizado": ahora(), "origen": f"Cargada una vez desde la planilla del Drive el {ahora()}",
                    "maquinas": maquinas})
    cambios = leer(RUTA_CAMBIOS, [])
    cambios.append({"fecha": ahora(), "maquina": "(todas)", "cambio": "Carga inicial desde la planilla del Drive",
                    "antes": "", "despues": f"{sum(1 for x in maquinas.values() if x['campo'])} máquinas con campo"})
    escribir(RUTA_CAMBIOS, cambios)
    sin = [f["maquina_planilla"] for f in plan.get("sin_cruce", [])]
    print(f"Operacion cargada: {len(maquinas)} maquinas activas, {sum(1 for x in maquinas.values() if x['campo'])} con campo.")
    if sin:
        print(f"Filas de la planilla que no calzan con ninguna maquina de Wialon (no se cargaron): {', '.join(sin)}")


def limpiar(valor, largo=80):
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:largo]


def guardar(cambios_json, id_guardado="", recibido=""):
    """Aplica los cambios de la pagina (lista de filas completas) y registra
    cada campo que cambio en el historial."""
    cambios = json.loads(cambios_json)
    if not isinstance(cambios, list) or not cambios or len(cambios) > 150:
        sys.exit("Cambios invalidos.")
    datos = leer(RUTA, None)
    if datos is None:
        sys.exit("Falta operacion.json (primero: python3 operacion.py cargar).")
    validas = set(activas())
    historial = leer(RUTA_CAMBIOS, [])
    fecha = ahora()
    n = 0
    for c in cambios:
        m = limpiar(c.get("maquina"))
        if m not in validas:
            print(f"Maquina desconocida, se ignora: {m!r}")
            continue
        fila = datos["maquinas"].setdefault(m, {k: "" for k in CAMPOS_FILA})
        nuevo = {k: limpiar(c.get(k)) for k in CAMPOS_FILA}
        if nuevo["desde"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", nuevo["desde"]):
            nuevo["desde"] = fila.get("desde", "")
        if pl.es_taller(nuevo["campo"]):
            nuevo["campo"] = "Taller"
        # "Desde" vacio = automatico (llegada al campo segun el GPS). Cambio de campo
        # sin fecha nueva: vuelve a automatico.
        if nuevo["campo"] != fila.get("campo") and nuevo["desde"] == fila.get("desde"):
            nuevo["desde"] = ""
        for k in CAMPOS_FILA:
            if nuevo[k] != (fila.get(k) or ""):
                antes, despues = fila.get(k) or "", nuevo[k]
                if k == "desde":
                    antes, despues = antes or "automática", despues or "automática"
                historial.append({"fecha": fecha, "maquina": m, "cambio": NOMBRES[k], "antes": antes, "despues": despues,
                                  "id": id_guardado})
                n += 1
        fila.update(nuevo)
    datos["actualizado"] = fecha
    if id_guardado:
        # La pagina reconoce su guardado (sincronizando… -> ✓ guardado) por este id.
        datos["guardados"] = (datos.get("guardados") or [])[-49:] + [
            {"id": id_guardado, "recibido": recibido, "aplicado": int(datetime.now().timestamp() * 1000), "cambios": n}]
    escribir(RUTA, datos)
    escribir(RUTA_CAMBIOS, historial)
    print(f"Operacion guardada: {n} cambios.")


def medir(id_guardado, recibido):
    """Espera (hasta 20 min) a que el guardado se vea en GitHub Pages y anota el
    tiempo desde que el Worker lo recibio. Nunca falla el guardado."""
    import time
    import requests
    if not id_guardado or not recibido:
        print("Guardado sin id (Worker anterior): no se mide.")
        return
    inicio = time.time()
    publicado = None
    while time.time() - inicio < 20 * 60:
        try:
            r = requests.get(URL_PUBLICADA, params={"x": int(time.time())}, timeout=30, headers={"Cache-Control": "no-cache"})
            if r.ok and any(g.get("id") == id_guardado for g in r.json().get("guardados", [])):
                publicado = int(time.time() * 1000)
                break
        except Exception as e:
            print(f"Reintento ({e})")
        time.sleep(10)
    tiempos = leer(RUTA_TIEMPOS, [])
    segundos = round((publicado - int(recibido)) / 1000) if publicado else None
    tiempos.append({"id": id_guardado, "fecha": ahora(), "recibido": int(recibido), "publicado": publicado, "segundos": segundos})
    escribir(RUTA_TIEMPOS, tiempos[-500:])
    print(f"Guardado {id_guardado}: " + (f"publicado en {segundos} s" if segundos is not None else "no se vio publicado en 20 min"))


if __name__ == "__main__":
    if sys.argv[1:] == ["cargar"]:
        cargar_desde_drive()
    elif sys.argv[1:] == ["guardar"]:
        guardar(os.environ["CAMBIOS"], os.environ.get("ID_GUARDADO", ""), os.environ.get("RECIBIDO", ""))
        import reporte_v2
        reporte_v2.rearmar_pagina()  # incluye la foto del dia (operadores.registrar)
    elif sys.argv[1:] == ["medir"]:
        medir(os.environ.get("ID_GUARDADO", ""), os.environ.get("RECIBIDO", ""))
    else:
        sys.exit(__doc__)
