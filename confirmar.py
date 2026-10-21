"""
confirmar.py

Confirmaciones de la pagina para el trabajo sin geocerca (reglas del usuario
21-oct-2026, ver CLAUDE.md). Lo ejecuta .github/workflows/confirmar.yml, que
lanza el Worker de Cloudflare cuando alguien aprieta un boton en la pagina
(abierto, sin clave por ahora).

Acciones (variable ACCION):
  campo     el lugar es de CAMPO (aceptar el probable o elegir otra opcion)
  ninguno   el lugar no es de ningun campo
  deshacer  borra la regla ID

Cada accion queda en docs/datos/confirmaciones.json (fecha, hora, lugar y
campo). La regla del lugar queda en config.json -> lugares_confirmados (un
lugar = a menos de distancia_mismo_lugar_m): desde ahi el trabajo en ese
lugar se asigna solo, como "confirmado". Despues se recalcula
docs/datos/sin_geocerca.json.
"""

import json
import os
import re
import sys
from datetime import datetime

import reporte_hectareas as rh
import sin_geocerca as sg

RUTA_CONFIG = rh.RUTA_CONFIG
RUTA_REGISTRO = os.path.join(rh.CARPETA_DATOS, "confirmaciones.json")


def guardar_reglas(reglas):
    """Reescribe solo la clave lugares_confirmados de config.json (el resto
    del archivo queda igual), una regla por linea."""
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        texto = f.read()
    bloque = '"lugares_confirmados": [' + ("\n" + ",\n".join(
        "    " + json.dumps(r, ensure_ascii=False) for r in reglas) + "\n  ]" if reglas else "]")
    if '"lugares_confirmados"' in texto:
        texto = re.sub(r'"lugares_confirmados": \[.*?\n?  ?\]', lambda _: bloque, texto, count=1, flags=re.S)
    else:
        texto = texto.rstrip().rstrip("}").rstrip() + ",\n  " + bloque + "\n}\n"
    json.loads(texto)  # que siga siendo JSON valido
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        f.write(texto)


def main():
    accion = os.environ.get("ACCION", "").strip()
    ahora = datetime.now(rh.ZONA_HORARIA).strftime("%Y-%m-%d %H:%M")
    reglas = list(rh.CONFIG.get("lugares_confirmados", []))
    registro = []
    if os.path.exists(RUTA_REGISTRO):
        with open(RUTA_REGISTRO, "r", encoding="utf-8") as f:
            registro = json.load(f)

    if accion in ("campo", "ninguno"):
        lat, lon = float(os.environ["LAT"]), float(os.environ["LON"])
        if not (-56 < lat < -17 and -76 < lon < -66):
            sys.exit("Coordenadas fuera de Chile.")
        campo = os.environ.get("CAMPO", "").strip() if accion == "campo" else None
        if accion == "campo":
            geos, *_ = sg.cargar_entrada()
            conocidos = {sg.campo_de(n) for n in geos}
            if campo not in conocidos:
                sys.exit(f"Campo desconocido: {campo!r}")
        # Un lugar tiene una sola regla: la nueva reemplaza a la anterior.
        reglas = [r for r in reglas if sg.distancia_m((lon, lat), (r["lon"], r["lat"])) > sg.LUGAR_M]
        regla = {"id": datetime.now(rh.ZONA_HORARIA).strftime("%Y%m%d%H%M%S"), "lat": round(lat, 6),
                 "lon": round(lon, 6), "campo": campo, "fecha": ahora}
        reglas.append(regla)
        registro.append({"fecha": ahora, "accion": "no es de ningun campo" if campo is None else "campo",
                         "id": regla["id"], "lat": regla["lat"], "lon": regla["lon"], "campo": campo})
    elif accion == "deshacer":
        regla_id = os.environ.get("ID", "").strip()
        borrada = next((r for r in reglas if r["id"] == regla_id), None)
        if not borrada:
            sys.exit(f"No existe la regla {regla_id!r}")
        reglas = [r for r in reglas if r["id"] != regla_id]
        registro.append({"fecha": ahora, "accion": "deshacer", "id": regla_id, "lat": borrada["lat"],
                         "lon": borrada["lon"], "campo": borrada["campo"]})
    else:
        sys.exit(f"Accion desconocida: {accion!r}")

    guardar_reglas(reglas)
    rh.CONFIG["lugares_confirmados"] = reglas
    with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=1)
    sg.main(con_direcciones=False)
    print(f"Listo: {registro[-1]}")


if __name__ == "__main__":
    main()
