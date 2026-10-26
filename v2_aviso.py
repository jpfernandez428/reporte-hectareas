"""Aviso a CORREO_PRUEBA (solo al usuario) cuando falla el paso de la manana de reporte2."""
import os
import reporte_correo as rc

url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
texto = ("Fallo el paso que arma los datos de reporte2.html despues del correo diario. "
         "El correo diario no se ve afectado. Detalle: " + url)
rc.enviar("Aviso: no se armaron los datos de reporte2", f"<p>{texto}</p>", texto, rc.destinatarios_de("CORREO_PRUEBA"))
print("Aviso enviado a CORREO_PRUEBA.")
