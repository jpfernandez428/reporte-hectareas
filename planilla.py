"""
planilla.py

Lee (SOLO LECTURA) la planilla "Maquinas en Operacion" (Excel en el Drive del
usuario) y la hoja "Equivalencias de campos" (Google Sheet), y las cruza con
Wialon. Reglas del usuario (22-oct-2026, ver CLAUDE.md):
  - Las maquinas se cruzan por tipo y numero ("Tractor 14 DF 115" = "Tractor 14
    Deutz Fahr 115", "Shaker SBS 6" = "Shacker SBS 6", "Tractor DF 115 15" =
    "Tractor 15").
  - "Taller" en Campo = esta en CYH.
  - El nombre del campo de la planilla se pasa a Wialon con las equivalencias
    (ej. Siracusa = Aurora; "Bunster (varios campos: A / B / C)" = varios).
  - Si no se puede leer, el correo sale igual con un aviso.
  - No se guarda la planilla completa en el repositorio: solo maquina,
    operador, campo y destino.
"""

import csv
import io
import json
import os
import re
import unicodedata

import requests

URL_PLANILLA = "https://drive.google.com/uc?export=download&id=1D7e_wQwUD00WPS2i0fc8xsw6p27euR3A"
# Desde el 26-oct-2026 la pagina Operacion (docs/operacion.html) reemplaza la
# planilla del Drive: si existe este archivo es la UNICA fuente y el Drive ya
# no se lee (se cargo una vez desde la planilla con operacion_cargar.py).
RUTA_OPERACION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "operacion.json")
URL_EQUIVALENCIAS = "https://docs.google.com/spreadsheets/d/1WfzQbMCZ8DKLHR1jnnQdQR-r2glbIoft_Qkn2bOYuo8/export?format=csv"

TIPOS = [  # (patron en la planilla, tipo comun)
    (r"\bshaker\s+sbs|\bshacker\s+sbs", "Shacker SBS"),
    (r"\bshacker\s+de\s+suelo|\bshaker\s+de\s+suelo", "Shacker de Suelo"),
    (r"\bbarredora", "Barredora"),
    (r"\brecogedora", "Recogedora"),
    (r"\bpodadora|\bautopropulsada", "Podadora"),
    (r"\btractor", "Tractor"),
]
MODELOS = {95, 100, 108, 115, 185, 420}  # numeros de modelo, no de maquina


def normalizar(texto):
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower().strip()


def mismo_nombre(a, b):
    """Mismo nombre sin importar mayusculas, tildes, espacios ni signos
    ("Puerto Lampa" = "puerto  lampa" = "Puerto-Lampa")."""
    clave = lambda t: re.sub(r"[^a-z0-9]", "", normalizar(t))
    return clave(a) == clave(b)


def tipo_y_numeros(nombre):
    n = normalizar(nombre)
    tipo = next((t for patron, t in TIPOS if re.search(patron, n)), None)
    return tipo, [int(x) for x in re.findall(r"\d+", n)]


def cruzar_maquina(nombre_planilla, nombres_wialon):
    """Nombre de Wialon de una fila de la planilla, o None si no calza."""
    tipo, numeros = tipo_y_numeros(nombre_planilla)
    if tipo is None:
        return None
    candidatos = []
    for w in nombres_wialon:
        tw, nw = tipo_y_numeros(w)
        if tw != tipo:
            continue
        propio = next((x for x in nw if x not in MODELOS or x == nw[0]), None) if nw else None
        if propio is not None and propio in numeros:
            candidatos.append(w)
    # Sin numero propio (ej. "Autopropulsada"): calza si hay una sola de ese tipo.
    if not candidatos and not [x for x in numeros if x not in MODELOS]:
        mismos = [w for w in nombres_wialon if tipo_y_numeros(w)[0] == tipo]
        candidatos = mismos if len(mismos) == 1 else []
    # "Tractor 14 DF 115": calza Tractor 14; nunca un numero de modelo solo.
    return candidatos[0] if len(candidatos) == 1 else None


def descargar(url, timeout=60):
    r = requests.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if b"<html" in r.content[:2000].lower() or b"<!doctype html" in r.content[:2000].lower():
        raise RuntimeError("Google pide iniciar sesion: el archivo no esta compartido como "
                           "'Cualquier persona con el enlace (Lector)'")
    return r.content


def leer_planilla(contenido):
    """[{fila, maquina_planilla, implemento, operador, campo, destino}]"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    filas = [list(r) for r in ws.iter_rows(values_only=True)]
    i_enc = next(i for i, f in enumerate(filas) if any(normalizar(v) == "tractor" for v in f if v))
    enc = [normalizar(v) for v in filas[i_enc]]
    col = lambda nombre: next((j for j, v in enumerate(enc) if v == nombre), None)
    c_maq, c_impl, c_op, c_campo, c_dest = col("tractor"), col("maquina"), col("operador"), col("campo"), col("destino")
    salida = []
    for k, f in enumerate(filas[i_enc + 1:], start=i_enc + 2):
        valor = lambda c: (str(f[c]).strip() if c is not None and c < len(f) and f[c] is not None else "")
        if not valor(c_maq):
            continue
        salida.append({"fila": k, "maquina_planilla": valor(c_maq), "implemento": valor(c_impl),
                       "operador": valor(c_op), "campo": valor(c_campo), "destino": valor(c_dest)})
    return salida


def leer_equivalencias(contenido):
    """{nombre en planilla (normalizado): [campos de Wialon]} ([] = sin geocerca)."""
    salida = {}
    lector = csv.reader(io.StringIO(contenido.decode("utf-8-sig")))
    for k, fila in enumerate(lector):
        if k == 0 or len(fila) < 2 or not fila[0].strip():
            continue
        destino = fila[1].strip()
        if "sin geocerca" in normalizar(destino) or not destino:
            campos = []
        elif "varios campos:" in normalizar(destino):
            campos = [c.strip(" )") for c in destino.split(":", 1)[1].split("/") if c.strip(" )")]
        else:
            campos = [destino]
        salida[normalizar(fila[0])] = campos
    return salida


def es_taller(campo):
    return normalizar(campo) in ("taller", "cyh", "taller (cyh)")


def cargar_operacion(nombres_wialon, equivalencias=None):
    """Misma estructura que cargar(), desde docs/datos/operacion.json (pagina
    Operacion). Las maquinas sin campo anotado quedan fuera ("no esta en la
    operacion"), como las que no estaban en la planilla."""
    resultado = {"ok": False, "aviso": None, "maquinas": {}, "sin_cruce": [], "fuente": "operacion",
                 "equivalencias": {normalizar(k): v for k, v in (equivalencias or {}).items()}}
    try:
        with open(RUTA_OPERACION, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception as e:
        resultado["aviso"] = f"No se pudo leer la pagina Operacion: {e}"
        return resultado
    for m, x in datos.get("maquinas", {}).items():
        campo = (x.get("campo") or "").strip()
        if m not in nombres_wialon or not campo:
            continue
        resultado["maquinas"][m] = {"fila": None, "maquina_planilla": m, "implemento": (x.get("implemento") or "").strip(),
                                    "operador": (x.get("operador") or "").strip(), "campo": "Taller" if es_taller(campo) else campo,
                                    "destino": (x.get("destino") or "").strip(), "desde": x.get("desde") or "",
                                    "en_cyh": es_taller(campo)}
    resultado["ok"] = True
    resultado["actualizado"] = datos.get("actualizado")
    return resultado


def cargar(nombres_wialon, equivalencias=None, forzar_drive=False):
    """{"ok", "aviso", "maquinas": {nombre Wialon: fila}, "sin_cruce": [filas],
    "equivalencias": {...}}. Nunca falla: si no se puede leer, ok=False y aviso.
    Las equivalencias vienen de config.json -> equivalencias_campos (desde el
    23-oct-2026 se editan en la pagina; la hoja del Drive ya no se usa)."""
    if os.path.exists(RUTA_OPERACION) and not forzar_drive:
        return cargar_operacion(nombres_wialon, equivalencias)
    resultado = {"ok": False, "aviso": None, "maquinas": {}, "sin_cruce": [],
                 "equivalencias": {normalizar(k): v for k, v in (equivalencias or {}).items()}}
    try:
        filas = leer_planilla(descargar(URL_PLANILLA))
    except Exception as e:
        resultado["aviso"] = f"No se pudo leer la planilla 'Maquinas en Operacion': {e}"
        return resultado
    for f in filas:
        f["en_cyh"] = normalizar(f["campo"]) in ("taller", "cyh", "")
        w = cruzar_maquina(f["maquina_planilla"], nombres_wialon)
        if w and w not in resultado["maquinas"]:
            resultado["maquinas"][w] = f
        else:
            resultado["sin_cruce"].append(f)
    resultado["ok"] = True
    return resultado
