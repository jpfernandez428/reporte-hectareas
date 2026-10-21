"""
recalculo_cadena.py

Recalculo del año en una rama de prueba (ej. dia-chile), corriendo completo en
GitHub: cada tramo, al terminar bien, lanza el siguiente (quincenas, hasta la
fecha de recalculo_plan.json). Antes de empezar, cada tramo espera si main
tiene en curso la corrida de la noche o el correo (main tiene prioridad).
Nunca corre en main. Una falla detiene la cadena (el paso siguiente solo
corre si el tramo termino bien).

Uso (desde .github/workflows/diario.yml):
  python3 recalculo_cadena.py esperar
  python3 recalculo_cadena.py siguiente
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

REPO = os.environ["GITHUB_REPOSITORY"]
RAMA = os.environ["GITHUB_REF_NAME"]
API = f"https://api.github.com/repos/{REPO}"
CABECERAS = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}


def plan():
    with open("recalculo_plan.json", "r", encoding="utf-8") as f:
        return json.load(f)


def esperar_a_main(maximo_min=120):
    """Espera mientras main tenga en curso o en cola la corrida o el correo."""
    inicio = time.time()
    while time.time() - inicio < maximo_min * 60:
        ocupado = []
        for wf in ("diario.yml", "correo.yml"):
            for estado in ("in_progress", "queued", "waiting", "pending"):
                r = requests.get(f"{API}/actions/workflows/{wf}/runs", headers=CABECERAS, timeout=60,
                                 params={"branch": "main", "status": estado, "per_page": 3})
                if r.ok and r.json().get("total_count"):
                    ocupado.append(f"{wf} ({estado})")
        if not ocupado:
            return
        print(f"main tiene {', '.join(ocupado)}: el recalculo espera.")
        time.sleep(120)
    print("main sigue ocupada despues de la espera maxima: se continua (corren en grupos separados).")


def siguiente():
    p = plan()
    if not p.get("activo"):
        print("Cadena de recalculo inactiva (recalculo_plan.json).")
        return
    fin_tramo = date.fromisoformat(os.environ["FECHA_FIN_MANUAL"])
    hasta = date.fromisoformat(p["hasta"])
    if fin_tramo >= hasta:
        print(f"RECALCULO TERMINADO: el ultimo tramo llego al {hasta}.")
        return
    desde = fin_tramo + timedelta(days=1)
    fin = desde.replace(day=15) if desde.day <= 15 else (desde.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    fin = min(fin, hasta)
    r = requests.post(f"{API}/actions/workflows/diario.yml/dispatches", headers=CABECERAS, timeout=60,
                      json={"ref": RAMA, "inputs": {"fecha_inicio": desde.isoformat(), "fecha_fin": fin.isoformat()}})
    r.raise_for_status()
    print(f"Lanzado el tramo siguiente: {desde} a {fin} (rama {RAMA}).")


if __name__ == "__main__":
    if RAMA == "main":
        sys.exit("El recalculo encadenado nunca corre en main.")
    {"esperar": esperar_a_main, "siguiente": siguiente}[sys.argv[1]]()
