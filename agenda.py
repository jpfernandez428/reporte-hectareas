"""
agenda.py

Agenda de trabajos (pedido del usuario 29-oct-2026; seccion Operacion de
docs/app.html): cada trabajo programado tiene campo, labor, inicio y termino
aproximado, hectareas o cuarteles, que se necesita (tipo y cantidad de
maquinas), estado (por confirmar -> confirmado -> en curso -> terminado),
notas, y las maquinas y operadores exactos cuando se asignan.

  - docs/datos/agenda.json          trabajos (copia en GitHub; con D1, la base
                                    del Worker es la que manda)
  - docs/datos/agenda_cambios.json  historial: fecha y hora, trabajo, que
                                    cambio (antes -> despues)

Uso:
  python3 agenda.py guardar   (TRABAJO = trabajo completo en JSON, o {"borrar": id}; via el Worker)
El termino previsto, el avance y los atrasos los calcula la pagina con el
rendimiento real (reporte_v2.json -> trabajo_campo).
"""

import json
import os
import re
import sys
from datetime import datetime

import reporte_hectareas as rh

RUTA = os.path.join(rh.CARPETA_DATOS, "agenda.json")
RUTA_CAMBIOS = os.path.join(rh.CARPETA_DATOS, "agenda_cambios.json")
ESTADOS = ("por_confirmar", "confirmado", "en_curso", "terminado")
NOMBRES = {"campo": "Campo", "labor": "Labor", "inicio": "Inicio", "termino": "Término (a mano)", "ha": "Hectáreas",
           "cuarteles": "Cuarteles", "necesita": "Qué se necesita", "estado": "Estado", "notas": "Notas",
           "maquinas": "Máquinas", "operadores": "Operadores"}
FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


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


def corto(valor, largo):
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:largo]


def limpiar(t):
    """Trabajo limpio (mismas reglas que el Worker) o None si no sirve."""
    if not isinstance(t, dict) or not re.fullmatch(r"[a-z0-9]{6,30}", str(t.get("id", ""))):
        return None
    lista = lambda v, largo: [x for x in (corto(y, largo) for y in (v if isinstance(v, list) else [])[:30]) if x]
    necesita = []
    for x in (t.get("necesita") if isinstance(t.get("necesita"), list) else [])[:10]:
        tipo = corto((x or {}).get("tipo"), 40)
        try:
            cantidad = max(1, min(50, int((x or {}).get("cantidad") or 1)))
        except (TypeError, ValueError):
            cantidad = 1
        if tipo:
            necesita.append({"tipo": tipo, "cantidad": cantidad})
    r = {"id": t["id"], "campo": corto(t.get("campo"), 80), "labor": corto(t.get("labor"), 60),
         "inicio": corto(t.get("inicio"), 10), "termino": corto(t.get("termino"), 10),
         "termino_previsto": corto(t.get("termino_previsto"), 10), "ha": corto(t.get("ha"), 10),
         "cuarteles": lista(t.get("cuarteles"), 80), "necesita": necesita,
         "estado": t.get("estado") if t.get("estado") in ESTADOS else "por_confirmar",
         "notas": corto(t.get("notas"), 1000), "maquinas": lista(t.get("maquinas"), 80),
         "operadores": lista(t.get("operadores"), 80), "creado": corto(t.get("creado"), 20)}
    if not r["campo"] or not FECHA.fullmatch(r["inicio"]):
        return None
    if any(r[k] and not FECHA.fullmatch(r[k]) for k in ("termino", "termino_previsto")):
        return None
    if r["ha"] and not re.fullmatch(r"\d{1,5}([.,]\d{1,2})?", r["ha"]):
        return None
    return r


def texto(k, v):
    if isinstance(v, list):
        return ", ".join(f'{x["cantidad"]} {x["tipo"]}' for x in v) if k == "necesita" else ", ".join(v)
    return str(v or "")


def guardar(entrada, id_guardado="", recibido=""):
    pedido = json.loads(entrada)
    datos = leer(RUTA, {"actualizado": "", "trabajos": {}})
    historial = leer(RUTA_CAMBIOS, [])
    fecha = ahora()
    nombre = lambda t: f'{t.get("campo", "")} · {t.get("labor") or "sin labor"}'
    if isinstance(pedido, dict) and pedido.get("borrar"):
        antes = datos["trabajos"].pop(str(pedido["borrar"]), None)
        if antes:
            historial.append({"fecha": fecha, "trabajo": nombre(antes), "cambio": "Borrado", "antes": nombre(antes),
                              "despues": "", "id": id_guardado})
        n = 1 if antes else 0
    else:
        t = limpiar(pedido)
        if not t:
            sys.exit("Trabajo invalido.")
        antes = datos["trabajos"].get(t["id"])
        n = 0
        if not antes:
            historial.append({"fecha": fecha, "trabajo": nombre(t), "cambio": "Creado", "antes": "",
                              "despues": t["inicio"] + (f' · {t["ha"]} ha' if t["ha"] else ""), "id": id_guardado})
            n = 1
        else:
            for k, nom in NOMBRES.items():
                a, d = texto(k, antes.get(k)), texto(k, t.get(k))
                if a != d:
                    historial.append({"fecha": fecha, "trabajo": nombre(t), "cambio": nom, "antes": a, "despues": d,
                                      "id": id_guardado})
                    n += 1
        datos["trabajos"][t["id"]] = t
    datos["actualizado"] = fecha
    if id_guardado:
        datos["guardados"] = (datos.get("guardados") or [])[-49:] + [
            {"id": id_guardado, "recibido": recibido, "aplicado": int(datetime.now().timestamp() * 1000), "cambios": n}]
    escribir(RUTA, datos)
    escribir(RUTA_CAMBIOS, historial[-2000:])
    print(f"Agenda guardada: {n} cambios.")


if __name__ == "__main__":
    if sys.argv[1:] == ["guardar"]:
        guardar(os.environ["TRABAJO"], os.environ.get("ID_GUARDADO", ""), os.environ.get("RECIBIDO", ""))
    else:
        sys.exit(__doc__)
