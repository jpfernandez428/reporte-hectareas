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

import planilla as pl
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


def guardar_clave(clave, valor):
    """Reescribe solo esa clave de config.json (va al final del archivo)."""
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        datos = json.load(f)
    datos.pop(clave, None)
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        texto = f.read()
    patron = r',\s*"' + re.escape(clave) + r'": \{.*?\n  \}(?=\s*[,}])'
    texto = re.sub(patron, "", texto, count=1, flags=re.S)
    texto = re.sub(r',\s*"' + re.escape(clave) + r'": \{\}', "", texto, count=1)
    bloque = f'"{clave}": ' + ("{\n" + ",\n".join(f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
                                                for k, v in valor.items()) + "\n  }" if valor else "{}")
    texto = texto.rstrip().rstrip("}").rstrip() + ",\n  " + bloque + "\n}\n"
    json.loads(texto)
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        f.write(texto)
    rh.CONFIG[clave] = valor


def cambiar_equivalencia(nombre, campo, agregar):
    """Agrega (o quita) un campo de Wialon a un nombre de la planilla. Sin
    campo al quitar: se borra el nombre completo. Reescribe campos.json."""
    equivalencias = {k: list(v) for k, v in rh.CONFIG.get("equivalencias_campos", {}).items()}
    clave = next((k for k in equivalencias if sg.pl_normalizar(k) == sg.pl_normalizar(nombre)), nombre)
    if agregar:
        lista = equivalencias.setdefault(clave, [])
        if campo and campo not in lista:
            lista.append(campo)
    elif not campo:
        equivalencias.pop(clave, None)
    elif clave in equivalencias:
        equivalencias[clave] = [c for c in equivalencias[clave] if c != campo]
        if not equivalencias[clave]:
            # Quitar el ultimo campo borra el nombre (no lo deja "sin geocerca").
            equivalencias.pop(clave)
    guardar_clave("equivalencias_campos", equivalencias)
    with open(rh.RUTA_GEOCERCAS_WEB, "r", encoding="utf-8") as f:
        rh.escribir_campos_web(sorted(json.load(f)))
    return equivalencias


def guardar_lista(clave, valor):
    """Reescribe solo esa clave (una lista) de config.json, al final."""
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        texto = f.read()
    texto = re.sub(r',\s*"' + re.escape(clave) + r'": \[.*?\](?=\s*[,}])', "", texto, count=1, flags=re.S)
    texto = texto.rstrip().rstrip("}").rstrip() + ",\n  " + f'"{clave}": ' + json.dumps(valor, ensure_ascii=False) + "\n}\n"
    json.loads(texto)
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        f.write(texto)
    rh.CONFIG[clave] = valor


def cerrar(registro):
    with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=1)
    print(f"Listo: {registro[-1]}")


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
        if accion == "campo" and not (0 < len(campo) <= 80):
            # Puede ser un campo de Wialon o uno de la planilla aun sin geocerca.
            sys.exit(f"Campo invalido: {campo!r}")
        # Un lugar tiene una sola regla: la nueva reemplaza a la anterior.
        reglas = [r for r in reglas if sg.distancia_m((lon, lat), (r["lon"], r["lat"])) > sg.LUGAR_M]
        regla = {"id": datetime.now(rh.ZONA_HORARIA).strftime("%Y%m%d%H%M%S"), "lat": round(lat, 6),
                 "lon": round(lon, 6), "campo": campo, "fecha": ahora}
        reglas.append(regla)
        registro.append({"fecha": ahora, "accion": "no es de ningun campo" if campo is None else "campo",
                         "id": regla["id"], "lat": regla["lat"], "lon": regla["lon"], "campo": campo})
        nombre_planilla = os.environ.get("PLANILLA", "").strip()
        if campo and nombre_planilla and not pl.mismo_nombre(nombre_planilla, campo):
            cambiar_equivalencia(nombre_planilla, campo, True)
            registro.append({"fecha": ahora, "accion": "equivalencia (al confirmar)", "nombre": nombre_planilla,
                             "campo": campo})
    elif accion in ("equivalencia", "borrar_equivalencia") and \
            os.environ.get("PLANILLA", "").strip().lower().startswith(("operador:", "operador-distinto:")):
        # Equivalencias de OPERADORES (22-oct-2026). Usan el mismo camino que las
        # de campos (sin cambiar el Worker): PLANILLA = "operador: <otro nombre>"
        # y CAMPO = <nombre que queda>; "operador-distinto: A" + CAMPO B = no es el mismo.
        tipo, nombre = os.environ["PLANILLA"].split(":", 1)
        nombre, otro = nombre.strip(), os.environ.get("CAMPO", "").strip()
        if not (0 < len(nombre) <= 80) or len(otro) > 80:
            sys.exit("Nombre de operador invalido.")
        if tipo.strip().lower() == "operador-distinto":
            distintos = [list(p) for p in rh.CONFIG.get("operadores_distintos", [])]
            if accion == "equivalencia" and otro and [nombre, otro] not in distintos:
                distintos.append([nombre, otro])
            elif accion == "borrar_equivalencia":
                distintos = [p for p in distintos if p != [nombre, otro]]
            guardar_lista("operadores_distintos", distintos)
            registro.append({"fecha": ahora, "accion": "operador distinto" if accion == "equivalencia" else "borrar operador distinto",
                             "nombre": nombre, "otro": otro})
        else:
            if accion == "equivalencia" and (not otro or pl.mismo_nombre(nombre, otro)):
                print(f"No se guarda: {nombre!r} y {otro!r} son el mismo nombre.")
                return
            eq = {k: list(v) for k, v in rh.CONFIG.get("equivalencias_operadores", {}).items()}
            if accion == "equivalencia":
                lista = eq.setdefault(otro, [])
                if nombre not in lista:
                    lista.append(nombre)
            else:
                for k in list(eq):
                    eq[k] = [x for x in eq[k] if not (x == nombre and (not otro or k == otro))]
                    if not eq[k]:
                        eq.pop(k)
            guardar_clave("equivalencias_operadores", eq)
            registro.append({"fecha": ahora, "accion": "equivalencia operador" if accion == "equivalencia" else "borrar equivalencia operador",
                             "nombre": nombre, "operador": otro or "(todos)"})
        cerrar(registro)
        return
    elif accion in ("equivalencia", "borrar_equivalencia"):
        # Equivalencias planilla -> Wialon (desde el 23-oct-2026 las edita el
        # usuario en la pagina; un nombre puede tener varios campos).
        nombre = os.environ.get("PLANILLA", "").strip()
        campo = os.environ.get("CAMPO", "").strip()
        if not (0 < len(nombre) <= 80) or len(campo) > 80:
            sys.exit("Nombre o campo invalido.")
        if accion == "equivalencia" and pl.mismo_nombre(nombre, campo):
            # "Puerto Lampa = Puerto Lampa" no es una equivalencia (regla del usuario 22-oct-2026).
            print(f"No se guarda: {nombre!r} y {campo!r} son el mismo nombre.")
            return
        equivalencias = cambiar_equivalencia(nombre, campo, accion == "equivalencia")
        registro.append({"fecha": ahora, "accion": "equivalencia" if accion == "equivalencia" else "borrar equivalencia",
                         "nombre": nombre, "campo": campo or "(todo el nombre)",
                         "resultado": equivalencias.get(nombre)})
        cerrar(registro)
        return
    elif accion == "maquina":
        # Planilla vs GPS (opcion B, 22-oct-2026): queda en config.json ->
        # maquinas_confirmadas y genera el aviso "Actualizar planilla" hasta que
        # la planilla cambie. VALOR: "cyh" o "campo"; PLANILLA: lo que decia la
        # planilla; CAMPO: el campo (si esta en el campo).
        maquina = os.environ.get("MAQUINA", "").strip()
        if maquina not in {u["nombre"] for u in rh.UNIDADES}:
            sys.exit(f"Maquina desconocida: {maquina!r}")
        valor = os.environ.get("CAMPO", "").strip()
        planilla = os.environ.get("PLANILLA", "").strip()
        en_taller = planilla.lower() in ("taller", "cyh", "")
        if valor == "cyh":
            texto = "en CYH" + (" (GPS con falla)" if en_taller else "")
            aviso = None if en_taller else "Taller"
        else:
            campo = valor.split(":", 1)[1].strip() if ":" in valor else planilla
            texto = f"en el campo {campo}" + (" (GPS con falla)" if not en_taller else "")
            aviso = campo if en_taller else None
        confirmadas = dict(rh.CONFIG.get("maquinas_confirmadas", {}))
        confirmadas[maquina] = {"planilla": planilla, "texto": texto, "aviso": aviso, "fecha": ahora,
                                "id": datetime.now(rh.ZONA_HORARIA).strftime("%Y%m%d%H%M%S")}
        guardar_clave("maquinas_confirmadas", confirmadas)
        registro.append({"fecha": ahora, "accion": "maquina", "maquina": maquina, "planilla": planilla, "valor": texto,
                         "id": confirmadas[maquina]["id"]})
        with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=1)
        print(f"Listo: {registro[-1]}")
        return
    elif accion == "deshacer_maquina":
        maquina = os.environ.get("MAQUINA", "").strip()
        confirmadas = dict(rh.CONFIG.get("maquinas_confirmadas", {}))
        borrada = confirmadas.pop(maquina, None)
        if not borrada:
            sys.exit(f"No hay confirmacion para {maquina!r}")
        guardar_clave("maquinas_confirmadas", confirmadas)
        registro.append({"fecha": ahora, "accion": "deshacer maquina", "maquina": maquina, "valor": borrada["texto"]})
        with open(RUTA_REGISTRO, "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=1)
        print(f"Listo: {registro[-1]}")
        return
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
    # Vuelve a armar los datos de reporte2.html (sin bajar GPS de Wialon) para
    # que la confirmacion se vea en 2-3 minutos.
    import reporte_v2
    reporte_v2.rearmar_pagina()
