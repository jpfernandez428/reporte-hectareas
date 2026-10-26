"""
v2_manana.py

Paso de la manana de reporte2.html (pedido del usuario 26-oct-2026): DESPUES
de que el correo diario de las 07:45 ya salio, arma docs/datos/reporte_v2.json
con el reporte_diario.json que publico el correo + el bloque "v2" (planilla del
Drive, operadores, trabajo por campo). No toca el correo ni sus archivos.

Lo lanza .github/workflows/v2.yml al terminar cada corrida del correo y en
horarios de respaldo. Si el correo de hoy todavia no sale, o reporte2 ya esta
armado con el dia de hoy, no hace nada. Si falla, el workflow avisa solo a
CORREO_PRUEBA (v2_aviso.py).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta

import reporte_hectareas as rh
import reporte_v2 as rv
import reporte_correo as rc


def main():
    hoy = datetime.now(rh.ZONA_HORARIA).date()
    enviado = rv.leer_json(os.path.join(rh.CARPETA_DATOS, "correo_enviado.json")) or {}
    forzar = os.environ.get("FORZAR", "") == "si"
    if not forzar and (enviado.get("fecha") != hoy.isoformat() or not enviado.get("reporte")):
        print("El correo de hoy todavia no sale: reporte2 se arma despues.")
        return
    v1 = rv.leer_json(rc.RUTA_DATOS_PAGINA) or {}
    v2 = rv.leer_json(rv.RUTA_V2) or {}
    if not forzar and v1.get("fecha") and (v2.get("v2") or {}).get("fecha") == v1["fecha"] and v2.get("generado") == v1.get("generado"):
        print(f"reporte2 ya esta armado con el dia {v1['fecha']}.")
        return
    usuario = None
    if os.environ.get("WIALON_TOKEN"):
        try:
            _, usuario = rc.login()  # solo lectura: comunas de las maquinas sin geocerca
        except Exception as e:
            print(f"Sin comunas de Wialon ({e}).")
    if not rv.rearmar_pagina(base_nueva=True, usuario=usuario):
        sys.exit("No se pudo armar reporte2 (ver arriba).")


if __name__ == "__main__":
    main()
