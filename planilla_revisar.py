"""
planilla_revisar.py

Desde el 26-oct-2026: con la pagina Operacion como fuente (operacion.json) ya
no se lee el Drive; el boton "Actualizar" rearma reporte2 y la revision cada
30 min queda apagada (sin Cron en el Worker). Antes: revisaba la planilla
"Maquinas en Operacion" del Drive (SOLO LECTURA) y, solo si cambio algo, volvia a armar los datos de reporte2.html con lo ya publicado,
sin bajar GPS de Wialon (pedido del usuario 22-oct-2026). Lo ejecuta
.github/workflows/planilla.yml, que lanza el Worker de Cloudflare cada 30 min
de 07:00 a 21:00 de Chile (ORIGEN=cron) o el boton "Actualizar desde la
planilla" de la pagina (ORIGEN=boton).

Para no chocar con la corrida de la noche, el correo ni las confirmaciones:
  - cron: si alguno de esos workflows esta corriendo en main, se salta esta
    revision (la corrida queda "cancelada": no cuenta como lectura);
  - boton: espera hasta 20 min a que terminen la corrida de la noche y las
    confirmaciones (el correo diario no escribe los datos de la pagina).
El recalculo de la rama dia-chile no se toca: corre en su rama y no usa estos
archivos.
"""

import os
import sys
import time

import requests

REPO = "jpfernandez428/reporte-hectareas"
API = f"https://api.github.com/repos/{REPO}"


def corriendo(workflows):
    """Workflows de main que estan en cola o corriendo (sin contar esta corrida)."""
    h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
    propios = []
    for wf in workflows:
        for estado in ("in_progress", "queued"):
            r = requests.get(f"{API}/actions/workflows/{wf}/runs", headers=h, timeout=30,
                             params={"status": estado, "branch": "main", "per_page": 20})
            r.raise_for_status()
            propios += [wf for x in r.json()["workflow_runs"] if str(x["id"]) != os.environ.get("GITHUB_RUN_ID")]
    return sorted(set(propios))


def saltar(motivo):
    """Se salta la revision: cancela esta corrida (no cuenta como lectura)."""
    print(f"Se salta esta revision: {motivo}.")
    h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
    requests.post(f"{API}/actions/runs/{os.environ['GITHUB_RUN_ID']}/cancel", headers=h, timeout=30)
    time.sleep(120)
    sys.exit(0)


def main():
    origen = os.environ.get("ORIGEN", "cron")
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_RUN_ID"):
        if origen == "cron":
            ocupados = corriendo(["diario.yml", "correo.yml", "confirmar.yml"])
            if ocupados:
                saltar(f"esta corriendo {', '.join(ocupados)}")
        else:
            for _ in range(40):
                ocupados = corriendo(["diario.yml", "confirmar.yml"])
                if not ocupados:
                    break
                print(f"Esperando a {', '.join(ocupados)}…")
                time.sleep(30)
            else:
                saltar("la corrida de la noche o una confirmacion sigue corriendo")
    import reporte_v2
    # Desde el 26-oct-2026 la fuente es la pagina Operacion (operacion.json), no
    # el Drive: el boton "Actualizar" rearma siempre; el cron (apagado) solo si cambio.
    reporte_v2.rearmar_pagina(solo_si_cambio=(origen == "cron"))


if __name__ == "__main__":
    main()
