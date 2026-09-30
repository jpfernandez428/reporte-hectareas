# Reporte de hectáreas — decisiones del proyecto

Leer esto antes de cualquier cambio. Son decisiones tomadas con el usuario; no
cambiarlas sin preguntar.

## Reglas generales

- **Wialon es solo de lectura.** Nunca escribir, modificar ni borrar nada en
  Wialon. Solo se usa para descargar geocercas y tracks GPS. El token de
  Wialon vive en el secret `WIALON_TOKEN` de GitHub (en `config.json` solo hay
  un texto de relleno; nunca poner el token real ahí).
- **Borrar resultados calculados** (memoria, historial, KML, geometría,
  avance) solo con aprobación explícita, mostrando antes la lista exacta.
  Nunca tocar código, `config.json` ni Wialon en una limpieza, salvo que se
  pida.
- **Antes de aplicar un cambio de fórmula, explicarlo y mostrar su efecto**
  con datos reales. No relanzar recálculos sin que el usuario lo pida.
- El token de GitHub (permisos repo + workflow) está en el Llavero del Mac y se
  lee con `git credential fill`. Nunca mostrarlo en pantalla ni en registros.
- Recálculos largos: por tramos en orden cronológico, uno a la vez, lanzados
  por la API. Un tramo sin commit solo se acepta si su registro dice "No se
  encontro actividad" y no tiene errores; cualquier otra falla detiene todo.
  Ningún tramo debe acercarse a las 6 h de GitHub Actions. Mantener el Mac
  despierto con `caffeinate` mientras dure.
- La corrida diaria automática (`.github/workflows/diario.yml`, 09:00 UTC) se
  pausa durante los recálculos y se reactiva recién cuando termina el último
  tramo.

## Fórmula de avance (aprobada)

- Cobertura sobre una grilla de celdas de 1 m dentro de cada geocerca (celda
  más grande solo en geocercas enormes).
- Cada hilera marca una franja de un espaciado de ancho, alargada hasta el
  borde si llega a menos de 20 m (cabecera). Se rellenan solo las franjas sin
  marcar más angostas que un espaciado; una hilera saltada queda sin cubrir.
- El espaciado entre hileras se mide agrupando las pasadas a menos de 1,5 m
  (el GPS parte una misma hilera en varias líneas).
- No cuentan como hilera los tramos cruzados (traslados en diagonal,
  vueltas) ni las pasadas aisladas (ver correcciones abajo).
- Umbral de cierre: **95 %** (`umbral_cierre_porcentaje` en `config.json`).
- **Calibración de terreno (poda, hasta el 22 de septiembre de 2026).**
  Cualquier cambio de fórmula debe mantener esto:
  - Aurora 3, 5, 6, 7, 8 y 9: terminados al 100 %.
  - Aurora 1 y 2: casi terminados (no deben quedar completos).
  - Aurora 4: 4,8 ha podadas.
  - Con la fórmula actual: Aurora 3 99,6 %, 5 99,8 %, 6 95,9 %, 7 99,4 %,
    8 97,6 %, 9 98,7 %; Aurora 1 92,4 %, 2 88,4 %; Aurora 4 67,7 % (4,86 ha).
- Colores del mapa: **verde** = cuartel terminado (todas sus hileras en
  verde), **azul** = hilera completa en un cuartel en proceso, **rojo** =
  hilera parcial.

### Correcciones aplicadas en el código (septiembre 2026, falta relanzar)

- Espaciado (ancho asumido de cada hilera) acotado a **2,5–5 m**; 4 m por
  defecto si hay menos de 10 hileras. Nunca más de 5 m (una máquina con
  pocas hileras llegaba a dar 30–400 m e inflaba el avance, ej. Solfrut 8).
- No se rellenan huecos de más de un espaciado (máx. 5 m): cada pasada
  cuenta solo su propia franja.
- Pasadas aisladas no cuentan: una pasada cuenta si tiene al menos 2 pasadas
  paralelas de la misma máquina a menos de 40 m (trabajo en serie, aunque se
  salte hileras). Así los traslados por el borde quedan fuera (Juan
  Valenzuela_Cuartel 4: Barrido 0 %, Cosecha con recibidor ~46 %, ambos
  confirmados en terreno).
- El avance de cada geocerca + labor nunca baja: se acredita solo lo que
  supera el máximo ya alcanzado (la suma del historial no puede pasar del
  área). Estado en `memoria_hileras/_avance_por_labor.json`.
- **Franja junto al límite de 8 m** (`franja_borde_m`): las celdas a menos
  de 8 m del límite de la geocerca cuentan como trabajadas solo donde el
  trabajo cubierto llega hasta ellas (cabeceras y bordes que la franja de la
  hilera no alcanza a tapar, ej. Aurora 6, triangular). Una franja de borde
  al lado de una zona sin trabajar sigue sin contar. Aplica a todas las
  labores y geocercas.
- Con estas reglas: Solfrut 8 – Picado 16,6 %, Solfrut 10 – Picado 12,1 %;
  Juan Valenzuela_Cuartel 4 – Barrido 0 %, Cosecha con recibidor 47 %.

### Patrones de trabajo (reglas del usuario, 30-sep-2026)

- Solo en **poda y picado** (`labores_con_patron`). Las barredoras siempre
  pasan por todas las hileras; dos pasadas por la misma hilera cuentan una
  sola vez y no crean una pasada nueva.
- Dos estilos, según la separación típica (mediana de la distancia entre
  líneas vecinas) de cada máquina en cada cuartel:
  - **Hileras pegadas** (menos de 7 m, `separacion_patron_ancho_m`; ej.
    Aurora, 3–5 m): se pasa por todas las hileras. Un hueco de una o más
    hileras es trabajo pendiente y no se rellena.
  - **Patrón ancho** (7 m o más: saltándose una o varias hileras; ej.
    Solfrut 27–53 m, Longaví 8 ~35 m, Longaví 15 y 16 ~8–10 m): todos los
    huecos entre la primera y la última pasada cuentan como trabajados,
    aunque la separación varíe o siga una secuencia (saltar 2, luego 4,
    luego 2...). Límite de seguridad: huecos de hasta 75 m
    (`hueco_maximo_patron_ancho_m`). Junto al límite de la geocerca cuenta
    hasta media separación del patrón (`fraccion_borde_patron_ancho`), solo
    donde el trabajo llega hasta ella.
- El operador no cambia de patrón en el cuartel, y la máquina puede ir y
  volver entre geocercas vecinas: si en una geocerca hay pocas pasadas, se
  usa la separación típica de esa máquina ese día en todas las geocercas que
  recorrió (`memoria_hileras/_estilo_maquinas.json`).
- Entre dos pasadas vecinas se rellena el trapecio que forman sus extremos
  reales (sigue el largo de cada hilera, ej. contra un borde en diagonal).
- Pasada extra (repasar una hilera saltada) no suma ni rompe el patrón. Dos
  pasadas a menos de 1,5 m son la misma línea (también una pasada cortada
  por un salto del GPS).
- Pasadas sueltas: en poda y picado cuenta una pasada paralela con al menos
  una vecina paralela a menos de 75 m; en las demás labores se piden dos
  (así los recorridos por el borde de las barredoras no cuentan).
- Contorno: una pasada a menos de 2 m del límite y paralela a él nunca
  cuenta (`distancia_contorno_m`; con 4 m se perdía una hilera real de
  Aurora 6).
- La detección no depende de conocer el espaciado de hileras.

### Cosecha con recibidor (reglas del usuario, 30-sep-2026)

- El shaker va por un lado de la hilera de árboles y el recibidor (sin GPS)
  por el otro. Normalmente el shaker pasa por todas las entrehileras. Cuando
  cosechan hacia el otro lado, el recibidor pasa por una entrehilera y el
  shaker se la salta: eso se ve como un hueco.
- Regla: un hueco de una sola entrehilera entre pasadas de shaker cuenta
  como trabajado; huecos más grandes no.
- Implementación (`relleno_recibidor`): con todos los shakers de la labor
  juntos (se reparten las hileras), el ancho de una entrehilera es la
  mediana de las separaciones entre pasadas largas vecinas que caen entre 4
  y 10 m (`entrehilera_minima_m`, `entrehilera_maxima_m`). Entre pasadas
  largas vecinas separadas hasta 2 entrehileras (±2 m) se rellena toda la
  banda. Los tramos cortos o en diagonal que se cruzan en medio no parten
  el hueco.

### Casos de calibración (verificar después de cada cambio de fórmula)

| Caso | Esperado (terreno) | Resultado actual |
|---|---|---|
| Aurora 3, 5, 6, 7, 8, 9 – Poda (al 22-09) | ≥ 95 % | 99,6 / 99,8 / 95,5 / 99,4 / 97,6 / 98,7 % ✓ |
| Aurora 4 – Poda (al 22-09) | ~4,8 ha | 4,86 ha ✓ |
| Aurora 2 – Poda | casi terminado | 88,4 % ✓ |
| Aurora 1 – Poda, datos hasta el 22-09 | < 95 % | 92,4 % ✓ |
| Aurora 1 – Poda, datos hasta el 29-09 (Tractor 13 terminó el 24–25) | ≥ 95 % | 99,5 % ✓ |
| Solfrut 8 – Picado (Tractor 16, 17 y 18-08) | ≥ 95 % | 99,5 % ✓ |
| Solfrut 10 – Picado (Tractor 16, 17 y 18-08) | ≥ 95 % | 99,6 % ✓ |
| Longaví 8 – Poda (Tractor 11, 27-06) | ~2,4 ha | 2,63 ha ✓ (+10 %) |
| Longaví 5 – Poda (Tractor 11, 27-06) | 0 ha (solo pasó) | 0 ha ✓ |
| Barredora 1, 23-09, Bernardo Lira Chiñihue N3 | ~8,05 ha (dos partes) | 8,89 ha ✓ (+10 %) |
| Juan Valenzuela_Cuartel 4 | Barrido 0 %, Cosecha con recibidor ~46 % | 0 % y 49,9 % ✓ |
| Longaví 15 y 16 – Poda (Tractor 11, 2 al 14-07) | completos (≥ 95 %) | 95,6 % y 97,4 % ✓ (patrón ancho de ~8–10 m) |
| Viconto – Barrido (Barredoras 6 y 5497, 7 al 9-04) | 4,7 ha en 3 partes (1,5 + 1,8 + 1,4); la franja central sin barrer es correcta | 5,13 ha (1,6 + 2,0 + 1,55) ✓ (+9 %) |
| Viconto 4 – Barrido (Barredoras 6 y 5497, 8 y 9-04) | ~9,3 ha en 3 partes | 9,28 ha ✓ |
| Agrícola Aeropuerto 7 – Cosecha con recibidor (Shacker SBS 9 y SBS 12, 7 al 17-04) | completo (≥ 95 %) | 91,9 % ✗ |
| Agrícola Aeropuerto 8 – Cosecha con recibidor (Shacker SBS 9 y SBS 12, 7 al 17-04) | completo (≥ 95 %) | 95,2 % ✓ |

Viconto: las dos barredoras trabajaron dentro de "Viconto" solo el 7 de
abril (el 8 en Viconto 4, el 9 en Viconto 4 y 4.1). El GPS de la Barredora
5497 está sano: sin saltos, 15 satélites de mediana, un punto cada ~41 s
(la Barredora 6 cada ~20 s); detenida manda un punto por hora.

Aurora 1 al 22-09 daba 95,9 % mientras se rellenaba el patrón también en
hileras pegadas: tapaba el 58 % de las hileras que el Tractor 13 completó el
24–25. Por eso con hileras pegadas no se rellena.

## Geocercas

Regla: **siempre el cuartel más detallado, nunca agregados.**

- Sacar "C&H Maquinaria" (patio donde se guardan las máquinas).
- Sacar todas las geocercas "Completo" y "Total".
- Kankura: usar los cuarteles "EL PRINCIPIO"; sacar "Kankura C", "KANKURA
  Lado a", "Kankura Lado B" y "Kankura Completo".
- Dejar: las canchas, "Matias Cardoen C7 prueba", las "Nueva geocerca" y las
  geocercas chicas (< 0,5 ha).
- Geocercas con nombre repetido en Wialon se distinguen agregando su id.

## Labores

Asignación máquina → labor en `config.json` (campo `labor` de cada unidad),
editable por el usuario.

| Labor | Máquinas |
|---|---|
| Poda | Tractor 2 (Wialon: "Tractor 2 Same Explorer 95", es el SAME INDIO 95), Tractores 9, 10, 11, 13 y 15 (DF 115), Podadora 1 (autopropulsada) |
| Picado | Tractor 1 (Wialon: "Tractor 1 Deutz-Fahr Agroplus", es el 420), Tractor 3 Same Frutetto 100, Tractor 4 Frutetto 100, Tractor 7 Kubota 95, Tractores 8, 16 y 17 Kubota 108, Tractor 14 DF 115 |
| Cosecha con recibidor | Shacker SBS (trabaja en pareja con recibidor; es una sola labor) |
| Remecido de suelo | Shacker de Suelo y Shaker Orchard Rite (botan al suelo; después pasa la recogedora) |
| Recolección | Recogedoras 1 a 7 |
| Barrido | Barredoras (con conteo de pasadas) |
| No incluir por ahora | "Tractor # 1 (T-7)" y "Tractor # 2 (T-8)" (nombres antiguos), Tractor 5 y Tractor 6 Same Explorer 95, Tractor Same Explorer 95 desp, Agrotron 185 |

- Dentro de la misma labor, las máquinas se unen y lo repetido cuenta una sola
  vez (ej. Tractores 10 y 13 se reparten Aurora). Entre labores distintas se
  cuenta por separado, aunque pasen por la misma hilera.
- En el resumen, cada geocerca aparece una vez por labor, por ejemplo
  "Aurora 7 – Poda: X ha (Y %)".

### Barredoras: pasadas completas

- Todas las barredoras se unen (a veces una sola hace el cuartel, a veces
  dos juntas). El repaso normalmente se hace al menos un día después.
- Una pasada se cierra cuando entre todas las barredoras cubren el 95 % del
  cuartel.
- Lo que sigan barriendo ese mismo día (hora de Chile) sigue siendo parte de
  esa pasada (terminar el 5 % restante).
- La pasada nueva empieza cuando vuelven otro día.
- Excepción: si el mismo día ya completaron el cuartel y empiezan a barrer de
  nuevo hileras que ya habían barrido en esa pasada, eso cuenta como pasada
  nueva. Criterio (aprobado): lo barrido ese día después del cierre debe
  cubrir por sí solo al menos el 50 % del cuartel
  (`fraccion_repaso_mismo_dia`). Con datos reales, terminar el 5 % restante
  cubre entre 5 % y 32 % (la franja de cada hilera se superpone con lo ya
  barrido), así que un criterio por tramos sueltos marcaba repasos falsos.
- El resumen muestra cuántas pasadas completas lleva cada cuartel y el % de
  la pasada en curso. **No** usar la mediana de días por hilera.
- Las hectáreas de barrido del historial suman todas las pasadas (pueden
  superar el área del cuartel); las del día se reparten entre las barredoras
  según los metros que barrió cada una.

## Mapas

- No guardar KML por máquina en el repositorio (hacía crecer mucho el
  historial de git). La web los genera desde `docs/datos/geometria/`.
- El KML generado debe ser XML válido (escapar `&`, `<`, `>` y comillas en
  nombres).

## Panel de estado de máquinas (en prueba)

Panel a la derecha de la web (`docs/datos/estado_maquinas.json`), según el
último día procesado:

- **Máquinas en CYH:** las que terminan el día dentro de la geocerca "C&H
  Maquinaria" (`geocerca_patio` en `config.json`).
- **⚠ Máquinas trabajando sin geocerca:** solo trabajo reciente, de los
  **últimos 30 días** (el mismo plazo de la recuperación de geocercas nuevas).
  Nunca alertas viejas del historial del año.
- **Formato:** una sola línea por máquina y lugar, no una por día:
  "Tractor 7 Kubota 95 – trabajando hace 5 días sin geocerca – [mapa]".
  "Hace N días" = días desde la primera vez que trabajó en ese lugar sin
  geocerca, dentro de los 30 días. Si la misma máquina trabajó en dos
  lugares distintos (a más de 600 m), una línea por lugar. Orden: de más días
  a menos.
- **Qué es trabajo:** mismo criterio de las hileras (tramos rectos a
  velocidad de trabajo, alineados y en serie; al menos 6 pasadas por zona).
  Además, para no confundir caminos de acceso con trabajo aunque la máquina
  vaya lento: la zona debe tener al menos 4 líneas distintas (a más de 1,5 m
  entre sí) que cubran al menos 12 m de ancho (un camino, aunque se recorra
  lento o varias veces, son 1–3 líneas en pocos metros).
- **Horas:** solo cuenta el tiempo en movimiento (≥ 1 km/h entre puntos GPS,
  intervalos de hasta 10 min porque algunos GPS mandan puntos espaciados),
  más los giros de cabecera. Un rato detenido no suma horas.
- **Mínimo por día (aprobado):** 1 hora de trabajo en esa zona
  (`horas_minimas_alerta`). Con datos reales
  (26-ago a 24-sep): 30 min → 58 líneas en el panel, 1 h → 55, 2 h → 45
  (2 h ya pierde trabajo claro, ej. 1,5–1,9 h con 2–2,7 ha).
- **Al crear la geocerca** en Wialon, la alerta de esa máquina en ese lugar
  desaparece (las alertas se revisan en cada corrida contra las geocercas
  actuales).

## Geocercas nuevas (en prueba)

- Se guarda la lista de geocercas conocidas por id de Wialon
  (`memoria_hileras/_geocercas_conocidas.json`). La primera vez se registran
  todas, sin recalcular.
- Cuando la corrida diaria encuentra una geocerca nueva, la calcula **solo a
  ella** con los últimos 30 días de TODAS las máquinas, por labor y con las
  mismas reglas (unión dentro de la labor, franja de borde de 8 m, pasadas de
  barredoras, etc.). Las demás geocercas siguen con el día normal.
- Se conecta con el panel: el trabajo que salió como alerta se recupera y la
  alerta desaparece.
- Costo: bajar 30 días de todas las máquinas toma ~40 min (solo el día en
  que aparecen geocercas nuevas; varias nuevas se calculan juntas).

## Pendientes

- Agrícola Aeropuerto 7 (Cosecha con recibidor) queda en 91,9 %: lo que
  falta está donde el recorrido del Shacker SBS 12 viene muy cortado y en
  diagonal. Consultado al usuario.
- Relanzar el año completo con la fórmula actual (lo lanza el usuario).
