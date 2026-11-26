"""
recuperar_pasadas_sin_geocerca.py

Recupera las pasadas (trazos) del trabajo sin geocerca ya guardado, para
dibujarlo en el mapa del informe (pedido del usuario 26-nov-2026). Desde esa
fecha la corrida de la noche las guarda sola; esto es para el trabajo anterior.

SOLO LECTURA de Wialon: baja el GPS de esa maquina ese dia y vuelve a detectar
las pasadas con el mismo criterio de la corrida de la noche
(rh.detectar_trabajo_fuera). No cambia horas, hectareas ni campos: solo agrega
trazos a docs/datos/sin_geocerca_pasadas.json.

Variables (opcionales): DESDE y HASTA (AAAA-MM-DD). Se lanza a mano con el
workflow "Recuperar pasadas sin geocerca" (pasadas_sin_geocerca.yml).
"""

import json
import os
from datetime import datetime

import reporte_hectareas as rh
import sin_geocerca as sg


def main():
    desde = os.environ.get("DESDE", "").strip()
    hasta = os.environ.get("HASTA", "").strip()
    with open(sg.RUTA, "r", encoding="utf-8") as f:
        trabajos = json.load(f)["trabajos"]
    pasadas = {}
    if os.path.exists(sg.RUTA_PASADAS):
        with open(sg.RUTA_PASADAS, "r", encoding="utf-8") as f:
            pasadas = json.load(f)
    pendientes = [t for t in trabajos
                  if t.get("estado") != "resuelto" and sg.clave_pasadas(t) not in pasadas
                  and (not desde or t["fecha"] >= desde) and (not hasta or t["fecha"] <= hasta)]
    rango = f" (del {desde or 'inicio'} al {hasta or 'hoy'})" if desde or hasta else ""
    print(f"Trabajos sin geocerca sin pasadas guardadas: {len(pendientes)}{rango}.")
    if not pendientes:
        return

    # Referencia: las geocercas en uso (las mismas de la pagina) y el patio (CYH).
    geos, flota, _, _, _ = sg.cargar_entrada()
    referencia = list(geos.values())
    patio = flota.get("patio")
    if patio:
        c = [tuple(p) for p in patio]
        referencia.append({"nombre": rh.GEOCERCA_PATIO, "contorno": c,
                           "bbox": (min(p[0] for p in c), min(p[1] for p in c), max(p[0] for p in c), max(p[1] for p in c))})
    indice = rh.indice_geocercas(referencia)
    unidades = {u["nombre"]: u for u in rh.CONFIG["unidades"]}

    por_dia = {}
    for t in pendientes:
        por_dia.setdefault((t["maquina"], t["fecha"]), []).append(t)
    sid = rh.wialon_login(rh.TOKEN)
    recuperados = 0
    for i, ((maquina, fecha), lista) in enumerate(sorted(por_dia.items(), key=lambda x: (x[0][1], x[0][0])), 1):
        unidad = unidades.get(maquina)
        if not unidad:
            print(f"  {fecha} {maquina}: no esta en config.json, se omite.")
            continue
        if i % 40 == 0:
            sid = rh.wialon_login(rh.TOKEN)  # la sesion de Wialon vence tras 5 min sin uso
        mensajes = rh.obtener_mensajes(sid, unidad["id"], datetime.strptime(fecha, "%Y-%m-%d"))
        puntos = [{"punto": (m["pos"]["x"], m["pos"]["y"]), "t": m.get("t")} for m in mensajes if m.get("pos")]
        if len(puntos) < 3:
            print(f"  {fecha} {maquina}: sin datos GPS.")
            continue
        por_geocerca = rh.repartir_puntos_por_geocerca(puntos, indice)
        dentro = {p.get("origen", id(p)) for lista_geo in por_geocerca.values() for p in lista_geo}
        alertas = rh.detectar_trabajo_fuera(unidad, fecha, puntos, dentro)
        for t in lista:
            # La zona detectada que coincide con el trabajo guardado (mismo lugar).
            cercanas = sorted((sg.distancia_m((t["lon"], t["lat"]), (a["lon"], a["lat"])), a) for a in alertas
                              if a.get("trazos")) if alertas else []
            if cercanas and cercanas[0][0] <= rh.DISTANCIA_MISMO_LUGAR_M:
                pasadas[sg.clave_pasadas(t)] = cercanas[0][1]["trazos"]
                recuperados += 1
            else:
                print(f"  {fecha} {maquina}: no se encontro la misma zona de trabajo.")
    with open(sg.RUTA_PASADAS, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(pasadas.items())), f, ensure_ascii=False, separators=(",", ":"))
    print(f"Pasadas recuperadas: {recuperados} de {len(pendientes)} trabajos.")


if __name__ == "__main__":
    main()
