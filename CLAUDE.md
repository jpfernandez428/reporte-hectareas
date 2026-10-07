# Reporte de hectáreas — decisiones del proyecto

Leer esto antes de cualquier cambio. Son decisiones tomadas con el usuario; no
cambiarlas sin preguntar.

## Reglas generales

- **Responder siempre en español** (pedido del usuario, 1-oct-2026).
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
- La corrida diaria automática (`.github/workflows/diario.yml`, 05:00 UTC desde el 5-oct-2026; el tablero de la flota corre aparte cada 4 horas) se
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
    - **Excepción GPS espaciado** (regla del usuario, 2-oct-2026; desde el
      5-oct-2026 se mide por tiempo): si el GPS de la máquina manda un punto
      cada 30 s o más (`intervalo_gps_espaciado_s`; mediana del día de cada
      máquina, guardada en `_estilo_maquinas.json` → `intervalo_gps`; sin ese
      dato se usa la distancia entre puntos ≥ 20 m) y el patrón es regular (al menos 5 líneas,
      `minimo_lineas_patron_regular`), un hueco de hasta 3 hileras entre dos
      pasadas vecinas cuenta como trabajado (`hileras_hueco_gps_espaciado`;
      hueco máximo = 4 × espaciado). Gonzalo Sánchez 2 – Picado: 90,5 →
      100 %. Aurora (Tractores 10 y 13 también con un punto por minuto) se
      mantiene: Aurora 1 al 22-09 sigue en 92,6 %.
  - **Patrón ancho** (7 m o más: saltándose una o varias hileras; ej.
    Solfrut 27–53 m, Longaví 8 ~35 m, Longaví 15 y 16 ~8–10 m): todos los
    huecos entre la primera y la última pasada cuentan como trabajados,
    aunque la separación varíe o siga una secuencia (saltar 2, luego 4,
    luego 2...). Límite de seguridad: huecos de hasta 75 m
    (`hueco_maximo_patron_ancho_m`).
- **Borde con patrón** (regla del usuario, 1-oct-2026): la franja entre la
  última pasada del patrón y el límite de la geocerca cuenta como trabajada
  solo si es más angosta que la separación del patrón, o sea si ahí no cabe
  otra pasada (`franja_sin_espacio_para_otra_pasada`: distancia de la celda
  al trabajo + media franja de la pasada + distancia al límite < separación).
  Si cabe otra pasada y no se hizo, sigue pendiente: así no se inflan
  cuarteles que quedaron a medias. Reemplaza la regla anterior de media
  separación.
- El operador no cambia de patrón en el cuartel, y la máquina puede ir y
  volver entre geocercas vecinas: si en una geocerca hay pocas pasadas, se
  usa la separación típica de esa máquina ese día en todas las geocercas que
  recorrió (`memoria_hileras/_estilo_maquinas.json`).
- Entre dos pasadas vecinas se rellena el trapecio que forman sus extremos
  reales (sigue el largo de cada hilera, ej. contra un borde en diagonal).
- Además se rellena **por tramos a lo largo** de las hileras
  (`rellenar_por_tramos`): en cada tramo, entre dos pasadas que pasan por
  ahí, con la posición real de cada pasada en ese punto (no todas son
  paralelas). Así una pasada cortada en pedazos por el GPS no deja huecos
  (El Volcán 14: el Tractor 7 reporta un punto por minuto).
- **Patrón del campo** (regla del usuario, 30-sep-2026): el campo es la raíz
  del nombre del cuartel, sin el número ni lo que sigue ("El Volcán 14" →
  "el volcan", "Solfrut 8" → "solfrut"). Cuando una máquina tiene 15 líneas
  o más en un cuartel (`lineas_patron_claro`), su separación típica queda
  como referencia del campo para esa labor. En un cuartel con menos
  líneas se usa la mediana de las referencias del mismo campo y labor; si el
  campo no tiene ninguna, la de esa máquina ese día en las geocercas
  vecinas, y si tampoco, la propia. Se guarda en
  `memoria_hileras/_estilo_maquinas.json` (`por_campo`).
  - Cada día se usa el patrón del campo conocido al empezar el día
    (`ESTILOS_CAMPO_REFERENCIA`): el resultado no depende del orden en que
    se calculan los cuarteles ese día (Gonzalo Sánchez 2 – Picado daba
    90,5 % o 100 % según el orden).
  - **Patrón propio claro** (regla del usuario, 5-oct-2026): con menos de 15
    líneas, si la separación propia del cuartel calza (±25 %,
    `coincidencia_patron_dia`) con la de la máquina ese mismo día en las
    geocercas vecinas, se usa la propia; si no, la del campo. Solfrut 10 –
    Picado: propia 27,3 m vs día 28,4 m → propia (el campo "solfrut"
    mezcla cuarteles de 4 a 15 m) → 100 %. El Volcán 14: propia 6,5 m vs
    día 9,1 m → campo.
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

### GPS (reglas del 30-sep-2026, calibradas con AA7, Don Cristóbal y El Volcán 14)

- **Puntos detenidos**: un punto se usa solo si la máquina se movió al menos
  3 m desde el último que quedó (`movimiento_minimo_punto_m`). El Shacker
  SBS 12 manda un punto cada 3 s y se detiene en cada árbol: el "baile" del
  GPS detenido cortaba sus pasadas en pedazos.
- **Solo pasó por el borde**: una máquina con menos de 10 pasadas en un
  cuartel, todas con su punto medio cerca del límite, no trabajó ahí y no
  cuenta (`maximo_pasadas_solo_borde`). "Cerca" es a menos de 15 m
  (`distancia_solo_borde_m`) **y** a menos de un tercio de la profundidad
  del cuartel (distancia de su centro al límite,
  `fraccion_profundidad_solo_borde`): en cuarteles chicos o angostos todas
  las pasadas quedan naturalmente a menos de 15 m del límite.
  - Revisión (1-oct-2026, memorias guardadas): con solo los 15 m se
    descartaban 85 máquina+cuartel, entre ellas trabajo real en cuarteles
    chicos. Con el tercio de la profundidad se recuperan 22 en 18 cuarteles,
    ej. Gonzalo Sánchez 8 (0,14 ha) Picado 0 → 74,8 %, Gonzalo Sánchez 9
    Remecido 0 → 85,8 %, Santa Ana 2.6 Recolección 0 → 94,2 % y Remecido
    0 → 97,3 %, EL PRINCIPIO 14 Cosecha 0 → 96,4 %, Viconto 3 Recolección
    0 → 91,1 %, El Volcán 14 Cosecha 55,2 → 99,2 %. Los 63 que siguen
    descartados son pasadas sueltas con poca cobertura.
  - Don Cristóbal Larraín: el Shacker SBS 13 (25–26-02) tiene 2 de sus 4
    pasadas a 29 y 38 m del límite, así que esta regla no lo descarta; lo
    que tapa (0,31 ha) ya lo había cubierto el SBS 11 y en el reporte no se
    le acredita nada (0 ha). El cuartel da 99,1 % con o sin el SBS 13.
- **GPS que reporta poco**: cada hilera guarda la distancia típica entre sus
  puntos (`paso_gps`). El extremo de una hilera se alarga hasta la cabecera
  si queda a menos de 20 m del borde, o a menos de esa distancia si es
  mayor (con un punto por minuto, el final de la hilera queda entre dos
  puntos).
- **Pasadas que cruzan la geocerca** (1-oct-2026): el tramo entre dos puntos
  GPS seguidos se corta en el límite de cada geocerca (se agregan los puntos
  de entrada y salida, con hora interpolada; `repartir_puntos_por_geocerca`).
  Antes solo se usaban los puntos que caían adentro: con un punto por minuto
  (Tractor 14, Shacker de Suelo 8: ~37 m entre puntos) una pasada que cruza
  un cuartel chico dejaba 0–1 puntos adentro y se perdía. Cada visita a la
  geocerca se segmenta por separado (la salida no se une con la siguiente
  entrada). Gonzalo Sánchez 2: Picado 56,1 → 90,5 %, Remecido 70,6 → 93,0 %.

### Cosecha con recibidor (reglas del usuario, 30-sep-2026)

- El shaker va por un lado de la hilera de árboles y el recibidor (sin GPS)
  por el otro. Normalmente el shaker pasa por todas las entrehileras. Cuando
  cosechan hacia el otro lado, el recibidor pasa por una entrehilera y el
  shaker se la salta: eso se ve como un hueco.
- Regla: un hueco de una sola entrehilera entre pasadas de shaker cuenta
  como trabajado; huecos más grandes no.
- **También en remecido de suelo** (regla del usuario, 2-oct-2026): el
  shaker de suelo puede trabajar junto con otra máquina y saltarse una
  entrehilera (`labores_hueco_entrehilera`). Gonzalo Sánchez 2 – Remecido:
  93,0 → 99,3 %.
- Implementación (`relleno_recibidor`): con todos los shakers de la labor
  juntos (se reparten las hileras), el ancho de una entrehilera es la
  mediana de las separaciones entre pasadas largas vecinas que caen entre 4
  y 10 m (`entrehilera_minima_m`, `entrehilera_maxima_m`). Entre pasadas
  largas vecinas separadas hasta 2 entrehileras (±2 m) se rellena toda la
  banda. Los tramos cortos o en diagonal que se cruzan en medio no parten
  el hueco.
- Además, por tramos a lo largo (`rellenar_por_tramos`), con todas las
  pasadas de los shakers (también las cortadas) en su posición real: en
  cada tramo se rellena el hueco entre pasadas vecinas de hasta 2
  entrehileras (±2 m).
- Un shaker que solo pasó por el borde no cuenta ni para el relleno.

### Casos de calibración (verificar después de cada cambio de fórmula)

| Caso | Esperado (terreno) | Resultado actual |
|---|---|---|
Resultados al 2-oct-2026, con GPS crudo (salvo donde se indica), antes de relanzar el año:

| Caso | Esperado (terreno) | Resultado actual |
|---|---|---|
| Aurora 3, 5, 6, 7, 8, 9 – Poda (al 22-09) | ≥ 95 % | 100 / 100 / 99,4 / 99,7 / 100 / 100 % ✓ |
| Aurora 4 – Poda (al 22-09) | ~4,8 ha | 4,83 ha ✓ |
| Aurora 2 – Poda (al 22-09) | casi terminado | 92,1 % ✓ |
| Aurora 1 – Poda, datos hasta el 22-09 | < 95 % | 92,6 % ✓ |
| Aurora 1 – Poda, datos hasta el 29-09 (Tractor 13 terminó el 24–25) | ≥ 95 % | 100 % ✓ |
| Solfrut 8 – Picado (Tractor 16, 17 y 18-08) | ≥ 95 % | 100 % ✓ |
| Solfrut 10 – Picado (Tractor 16, 17 y 18-08) | ≥ 95 % | 100 % ✓ |
| Longaví 8 – Poda (Tractor 11, 27-06) | ~2,4 ha | 2,55 ha ✓ (+6 %) |
| Longaví 5 – Poda (Tractor 11, 27-06) | 0 ha (solo pasó) | 0 ha ✓ |
| Barredora 1, 23-09, Bernardo Lira Chiñihue N3 | ~8,05 ha (dos partes) | 8,50 ha ✓ (+6 %) |
| Juan Valenzuela_Cuartel 4 | Barrido 0 %, Cosecha con recibidor ~46 % | 0 % y 50,9 % ✓ |
| Longaví 15 y 16 – Poda (Tractor 11, 2 al 14-07) | completos (≥ 95 %) | 100 % y 100 % ✓ (patrón ancho de ~8–10 m) |
| Viconto – Barrido (Barredoras 6 y 5497, 7 al 9-04) | 4,7 ha en 3 partes (1,5 + 1,8 + 1,4); la franja central sin barrer es correcta | 5,23 ha ✓ (+11 %) |
| Viconto 4 – Barrido (Barredoras 6 y 5497, 8 y 9-04) | ~9,3 ha en 3 partes | 9,38 ha ✓ |
| Agrícola Aeropuerto 7 – Cosecha con recibidor (Shacker SBS 9 y SBS 12, 7 al 17-04) | completo (≥ 95 %) | 99,9 % ✓ |
| Agrícola Aeropuerto 8 – Cosecha con recibidor (Shacker SBS 9 y SBS 12, 7 al 17-04) | completo (≥ 95 %) | 99,6 % ✓ |
| Don Cristóbal Larraín – Cosecha con recibidor (febrero) | completo (≥ 95 %); solo trabajó el Shacker SBS 11; el SBS 13 solo pasó por el borde (25–26-02) y no debe contar | 99,3 % ✓ (igual con y sin el SBS 13; al SBS 13 se le acreditan 0 ha) |
| El Volcán 14 – Cosecha con recibidor | completa | 99,2 % ✓ (memoria; con la regla del borde solo por 15 m daba 55,2 %) |
| El Volcán 14 – Picado (Tractor 7, 7-07) | completo en terreno; el lóbulo sur-oeste no se pasó. **Caso conocido: el usuario acepta ~92,6 %** | 93,4 % ✓ (aceptado) |
| Cuarteles chicos (< 0,5 ha), ej. Gonzalo Sánchez 8 – Picado (Tractor 14) | el trabajo real no se descarta como "solo pasó por el borde" | 100 % ✓ (antes 0 %) |
| Gonzalo Sánchez 2 – Barrido (Barredora 7) | completo el 27-02 y después repasado | 100 % + línea "repaso" 46,7 % (04-03) ✓ |
| Gonzalo Sánchez 2, 7, 8 y 9 – 20-03 (Tractor 14 y Barredora 7) | no hubo trabajo (solo giros y esquinas de la geocerca vecina) | no cuenta ✓ (`trabajo_descartado`); GS 8 repaso 61,4 % (04-03), GS 9 sin repaso |
| Gonzalo Sánchez 2 – Picado (Tractor 14, todo el 28-02; la franja sin pasadas es por el GPS de un punto por minuto) | ≥ 95 % | 100 % ✓ (regla de GPS espaciado) |
| Gonzalo Sánchez 2 – Remecido de suelo (Shacker de Suelo 8, todo el cuartel) | ≥ 95 % | 99,3 % ✓ (hueco de una entrehilera) |
| Gonzalo Sánchez 7 – Barrido (Barredora 7, 03-03, 2 pasadas, probando) | 0 % | 0 % ✓ |
| Gonzalo Sánchez 7 – Picado (Tractor 14, 04-03) | no se picó completo; 78 % es correcto (confirmado por el usuario, 5-oct-2026) | 78,4 % ✓ |
| Gonzalo Sánchez 9 – Barrido, pasadas del 04-03 | no cuentan (pasó y no siguió) | no cuentan ✓ |

Viconto: las dos barredoras trabajaron dentro de "Viconto" solo el 7 de
abril (el 8 en Viconto 4, el 9 en Viconto 4 y 4.1). El GPS de la Barredora
5497 está sano: sin saltos, 15 satélites de mediana, un punto cada ~41 s
(la Barredora 6 cada ~20 s); detenida manda un punto por hora.

Aurora 1 al 22-09 daba 95,9 % mientras se rellenaba el patrón también en
hileras pegadas: tapaba el 58 % de las hileras que el Tractor 13 completó el
24–25. Por eso con hileras pegadas no se rellena.

**Gonzalo Sánchez (revisión 1-oct-2026, GPS crudo):**
- GS 2 es un pentágono de 0,25 ha (~45 × 60 m) que se superpone en parte
  con la geocerca MP1. El Tractor 14 y el Shacker de Suelo 8 reportan un
  punto por minuto (~37 m entre puntos): sus pasadas cruzan GS 2 en
  diagonal, siguiendo las hileras de los bloques vecinos.
- Picado 28-02 (Tractor 14): las pasadas dentro de GS 2 quedan en los
  laterales 5, 9, 16, 23, 31, 35, 40, 44, 58, 68 y 72 m; entre 44 y 58 m
  (~12–15 m) el GPS no muestra ninguna pasada. El patrón de picado del campo
  es de hileras pegadas (4–5 m), así que ese hueco no se rellenaba (90,5 %).
  El usuario confirmó que se picó entero: resuelto con la regla de GPS
  espaciado (100 %).
- Remecido (Shacker de Suelo 8): queda una franja de ~8 m sin pasada entre
  dos pasadas, más la punta sur → 93,0 %. Resuelto con la regla del hueco
  de una entrehilera en remecido (99,3 %).
- 20-03 (Tractor 14 y Barredora 7 en GS 2, 7, 8 y 9): no fue traslado puro.
  Ambas máquinas trabajaban los bloques vecinos (MP1, GS 6, GS 1) con
  hileras largas NO–SE; lo que cae dentro de GS 2, 7 y 8 son vueltas de
  cabecera (entran, giran y salen por el mismo lado) y puntas de hileras
  que cortan una esquina. En GS 9 el Tractor 14 entró al campo cruzándolo a
  lo largo (09:15–09:23) y giró adentro (10:26–10:31); la Barredora 7 hizo
  ~8 pasadas a lo largo de GS 9 (07:56–08:45), que parece barrido real.
  **Confirmado por el usuario (1-oct-2026): el 20-03 no hubo trabajo en
  ningún GS (2, 7, 8, 9), tampoco la Barredora 7 en GS 9; solo giros y
  esquinas cortadas al trabajar la geocerca vecina.** Se descarta con la
  lista `trabajo_descartado` de `config.json`.
  Se probaron 4 criterios automáticos y ninguno separa esas vueltas del
  trabajo real con GPS de un punto cada 30–60 s en cuarteles tan chicos:
  cantidad de pasadas, metros recorridos adentro vs necesarios (Shacker de
  Suelo 8 en GS 2 el 26-02, real: 0,48; Barredora 7 el 20-03: 0,46),
  pasadas que cruzan de borde a borde por un tramo largo (Barredora 7 el
  20-03: 6; Shacker el 26-02, real: 4) y "fila dueña" (a qué geocerca
  pertenece cada fila completa del día: Tractor 14 en GS 8 el 03-03, real:
  28 % propio; en GS 2 el 20-03: 63 %).

**Caso conocido – El Volcán 14, Picado (aceptado por el usuario, 1-oct-2026):**
queda en 92,6 % aunque en terreno está completo. El lóbulo sur-oeste (5,4 %
del cuartel) no tiene ningún punto del Tractor 7; entre el trabajo y el
límite quedan ~15–21 m, y con la separación del patrón (7,5 m) caben 2
pasadas más, así que la regla de borde con patrón lo deja pendiente. El
usuario prefiere aceptar la diferencia antes que una regla especial que pueda
inflar otros cuarteles. No crear reglas para cerrarlo.

## Geocercas

Regla: **siempre el cuartel más detallado, nunca agregados.**

- Sacar "C&H Maquinaria" (patio donde se guardan las máquinas).
- Sacar todas las geocercas "Completo" y "Total".
- Kankura: usar los cuarteles "EL PRINCIPIO"; sacar "Kankura C", "KANKURA
  Lado a", "Kankura Lado B" y "Kankura Completo".
- Dejar: las canchas, "Matias Cardoen C7 prueba", las "Nueva geocerca" y las
  geocercas chicas (< 0,5 ha).
- Geocercas con nombre repetido en Wialon se distinguen agregando su id.

### Geocercas superpuestas (regla del usuario, aplicada el 2-oct-2026)

Orden: **primero las decisiones explícitas** de `config.json` (Kankura con
EL PRINCIPIO, sacar "Completo" y "Total", patio), **después la regla del
95 %** entre las geocercas que quedan (`resolver_superposiciones`, resultado
en `memoria_hileras/_superposiciones.json`; se recalcula solo si cambian las
geocercas de Wialon, ~3 min):
- Una chica está "contenida" si al menos el 75 % de su área queda dentro de
  la grande (`fraccion_contenida`).
- Si las chicas juntas cubren el **95 % o más** del área de la grande, se
  usan las chicas y la grande no se calcula.
- Si cubren **menos del 85 %**, se usa solo la grande y las chicas no se
  calculan.
- **Duda** (entre 85 y 95 %) y **superposiciones parciales** (30–75 % de la
  chica adentro) entre geocercas que quedan en uso: se calculan las dos, y
  cada día, por máquina, el tramo común se le da solo a la que mejor calza
  con el recorrido (donde la máquina recorrió más metros ese día, o sea la
  que capta más trabajo); nunca se cuenta en dos a la vez
  (`resolver_conflictos_del_dia`). Así se resuelven también las geocercas
  duplicadas o con errores (regla del usuario: usar la geocerca donde se
  trabajó, la que mejor calce con el recorrido).
- Resultado con las geocercas del 2-oct-2026: 1.068 → 1.031 en uso. No se
  calculan: MP1–MP4 (se usan los Gonzalo Sánchez), Matias Campos 1–5 (se
  usan los Trinidad), Juan Valenzuela_Cuertel 5–10 (se usan los Juan V
  Nogales), Maria Ignacia Eyzaguirre Campo 1/2/3 2024, Pirque Ciruelos 1,
  "ochagavia 2025 pa borrar", Ochagavia Manantiales 7, Ochagavia San
  Gregorio C1 y C3, Santa Ana 2.17 (id …-355), Sas Gregorio Ag. el Carmen
  C1, San Gregorio Ag. el Carmen C2, Ag_El_Carmen…Cuartel_2, Carizalillo 14
  y 15, Carrizalillo Guara Hornos Flores; y como chicas de una grande con
  menos de 85 %: Carizalillo 7, 9, 10, 11 y las Carrizalillo Guara Hornos,
  Guara La Cruz y Guara La Loma. Se deciden día a día: Carrizalillo Huerto
  Antiguo 66%NP con Carizalillo, 1, 2 y 4 (89,6 %); Carrizalillo La Cruz
  con Carizalillo 12; Carrizalillo Los Hornos 50%NP con Carizalillo 8;
  Ochagavia (San Gregorio) con su C2 (94,4 %); San Gregorio Ag. El Carmen
  C4 con Ag. El Carmen Cuartel 1 (94,5 %).

Inventario previo (antes de aplicar las exclusiones explícitas primero), 1-oct-2026
(1.086 polígonos en Wialon; una chica se considera "contenida" si al menos
el 75 % de su área queda dentro de la grande, porque varias chicas quedan
84–88 % adentro por diferencias de dibujo: GS 2 y GS 8 en MP1, GS 9 en MP2):
55 geocercas contienen a otras. Con anidamiento (se decide de la más grande
a la más chica; si se usa la grande, todas las de adentro quedan fuera).

Cambios respecto de las decisiones anteriores (consultados al usuario):
- **Kankura**: Kankura Completo → chicas (99,4 %), pero KANKURA Lado a
  (93,0 %), Kankura Lado B (93,4 %) y Kankura C (91,8 %) quedarían en uso y
  los 14 EL PRINCIPIO dejarían de calcularse (hoy es al revés).
- **"Completo"/"Total" con chicas < 95 %** pasarían a usarse en vez de sus
  cuarteles: Matias Cardoen Completo (93,6 %, 10 chicas), Ochagavia San
  Gregorio Completo (88,9 %, 8), Andraca Anania Total (81,4 %, 4), Los Tilos
  Talagante Completo (56,6 %, 3).
- **Carrizalillo** tiene dos juegos de geocercas (Carizalillo 1–15 y zonas
  como "Huerto Antiguo 66%NP", "La Cruz", "Los Hornos 50%NP", "Guara ..."):
  la regla mezcla ambos (ej. Huerto Antiguo 89,6 % deja fuera Carizalillo,
  1, 2 y 4).
- MP1 (95,6 %), MP2 (98,6 %), MP3 (99,6 %) y MP4 (99,6 %) dejan de
  calcularse y se usan los Gonzalo Sánchez.
- Otras grandes que hoy se calculan y dejarían de calcularse porque sus
  chicas cubren ≥ 95 %: Maria Ignacia Eyzaguirre Campo 1/2/3 2024, Matias
  Campos 1–5 (Trinidad), Juan Valenzuela_Cuertel 5–10 (Juan V Nogales),
  Pirque Ciruelos 1, Ochagavia Manantiales 7, "ochagavia 2025 pa borrar",
  Carizalillo 14 y 15, Ochagavia San Gregorio C1 y C3, Santa Ana 2.17 (id
  …-355), varias de Ag. El Carmen San Gregorio.
- Grandes en uso con chicas < 95 % (las chicas dejarían de calcularse):
  Carrizalillo La Cruz, Carrizalillo Los Hornos 50%NP, Carizalillo 3, 8 y 12,
  San Gregorio Agricola El Carmen C4 (94,5 %).

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
- **Línea de repaso** (pedido del usuario, 1-oct-2026): cuando la primera
  pasada está cerrada, la línea "Cuartel – Barrido" queda en 100 % y aparece
  otra, "Cuartel – Barrido – repaso", con el % de la pasada en curso (si ya
  hubo repasos completos: "N repasos completos + X %"). Solo aparece cuando
  la regla de pasadas abrió una pasada nueva (otro día, o el mismo día con
  ≥ 50 % del cuartel después del cierre).
- **Una pasada (y un repaso) solo empieza con un día de TRABAJO** (regla del
  usuario, 5-oct-2026): lo barrido ese día, por sí solo y con los filtros de
  siempre (pasadas en serie), cubre al menos el 1 % del cuartel
  (`fraccion_minima_dia_trabajo`). Pasar, girar o cortar una esquina nunca
  crea una pasada ni un repaso: esos tramos quedan pendientes y se suman a la
  pasada si dentro de 30 días hay un día de trabajo (si no, se descartan).
  Ej. Gonzalo Sánchez 9: la Barredora 7 solo pasó el 19-03 (y el 04-03) →
  sin repaso. En el relanzamiento del 2-oct había ~25 repasos armados solo
  con días así (A2, A7Bb, A14, A15, Bruno Raggi 13/14/17/21/22, Bernardo
  Lira Chiñihue A4/A5/A12/A21/A22, Achurra 3 y 5, Ballerina N7D, El Volcán
  9, El Volcán 2022 3, Los Migueles, Rafael Peña 1/2/3, Candelaria 4,
  Gonzalo Sánchez 9).
- **Pasada vencida** (regla del usuario, 5-oct-2026): si pasan más de 30
  días sin barrer el cuartel (`dias_vence_pasada`), la pasada abierta se
  cierra como incompleta (queda en `incompletas` del estado) y el próximo
  día de trabajo empieza una pasada nueva. Ej. Bernardo Lira Chiñihue N3:
  la pasada de abril quedó en 83 %; el barrido del 23-09 es una pasada nueva
  y se acreditan 8,5 ha (terreno ~8,05 ha).
- Las hectáreas de barrido del historial suman todas las pasadas (pueden
  superar el área del cuartel); las del día se reparten entre las barredoras
  según los metros que barrió cada una.

## Mapas

- **Filtro por fechas (regla del usuario, 7-oct-2026):** con "desde" y
  "hasta", la tabla y el mapa muestran solo lo hecho entre esas fechas y
  como estaba a la fecha "hasta", no lo de hoy:
  - Hectáreas y %: el trabajo de las máquinas y fechas elegidas (historial).
  - Estado "completo" (✓ en la tabla, verde y "COMPLETA" en el mapa): el
    cuartel + labor llegaba al 95 % a la fecha "hasta", sumando todas las
    máquinas de esa labor (historial hasta ese día).
  - Mapa: cada pasada se dibuja con el tramo recorrido ese día (las
    pasadas guardan su fecha desde el 7-oct-2026: `intervalos` = [desde,
    hasta, fecha]; la geometría trae `tramos` por fecha cuando la hilera se
    trabajó en varios días); la hilera es "completa" (azul) si a la fecha
    "hasta" ya llegaba de borde a borde (`completa_desde`).
  - Lo calculado antes del 7-oct-2026 no tiene la fecha de cada pasada: en
    las hileras trabajadas en un solo día (93 %) es exacto igual; en las de
    varios días (7 %) el mapa dibuja el largo completo y la hilera cuenta
    como completa recién el último día (`tramos_aprox`), hasta recalcular.

- No guardar KML por máquina en el repositorio (hacía crecer mucho el
  historial de git). La web los genera desde `docs/datos/geometria/`.
- El KML generado debe ser XML válido (escapar `&`, `<`, `>` y comillas en
  nombres).

## Tablero de la flota (aprobado por el usuario el 5-oct-2026)

Pestaña **"Flota"** abajo en la web (botones "Hectáreas | Flota"; enlace
directo `#flota`): abre el tablero a ancho completo, separado del reporte de
hectáreas. Reemplaza el panel lateral anterior. Datos en
`docs/datos/flota.json`, armado por `construir_flota`.

- **Cuándo se actualiza:** corrida liviana cada 4 horas
  (`.github/workflows/flota.yml`, `MODO_FLOTA=1`, 00/04/08/12/16/20 UTC: solo
  el tablero, sin hectáreas; sube `flota.json`) y al final de la corrida
  completa diaria (05:00 UTC). Ambas en el mismo grupo de concurrencia (una
  a la vez). Costo: el repositorio es público → minutos de GitHub Actions sin
  costo. La página nunca se conecta a Wialon (es pública y expondría el
  token): solo lee los archivos publicados.
- **Listado:** todas las máquinas configuradas (sin "No incluir"), siempre en
  el mismo orden: Barredoras, Shacker SBS, Tractores y luego el resto
  (Shacker de Suelo, Shaker Orchard Rite, Recogedoras, Podadora, otras); dentro
  de cada tipo por número real (Barredora 2 antes que Barredora 10); los
  números no correlativos (> 100, ej. Barredora 5497) al final del grupo. El
  orden no cambia con el color.
- **Columnas:** nombre, labor, estado (color + texto), ubicación (geocerca,
  "CYH" o "Fuera de geocercas", con enlace a Google Maps del último punto) y
  última conexión (fecha y hora del último dato GPS, de Wialon).
- **Estados (en este orden de prioridad):**
  1. **Rojo:** trabajó sin geocerca en los últimos 7 días (alerta visible: ≥ 1
     h por día) y la geocerca sigue sin crearse, aunque hoy esté en CYH o en
     otra geocerca. "Sin geocerca desde hace N días".
  2. **Gris (sin señal hace más de 30 días):** "Sin señal desde el …", en su
     lugar del orden fijo, aunque su última posición sea CYH.
  3. **Amarillo:** su último punto está en CYH ("C&H Maquinaria"). "En CYH
     desde el …" (llegada a CYH, siguiendo los fines de día en CYH; los días
     sin datos GPS con la máquina guardada no cortan la estadía).
  4. **Verde:** hoy o ayer trabajó (≥ 1 h en movimiento) dentro de una o más
     geocercas. "En <geocercas> desde el …" (días seguidos trabajando ahí).
  5. **Gris:** lo demás: "Sin señal desde el …" (más de 24 h sin datos) o
     "Detenida en/fuera de geocercas desde el …" (último movimiento).
- **Alerta "GPS sin señal"** (destacada arriba del tablero): máquina que lleva
  más de 24 horas sin enviar datos (`horas_sin_senal`), solo si la perdió en
  los últimos 30 días; muestra la fecha y hora de la última señal y la última
  ubicación. Desaparece sola cuando vuelve a enviar datos. Con 24 h al
  5-oct-2026 salían 12 alertas: 11 máquinas guardadas en CYH (su GPS deja de
  mandar datos al guardarlas) y el Tractor 7 (fuera de geocercas, sin señal
  desde el 28-09). **Decisión del usuario (5-oct-2026):
  `alerta_sin_senal_en_cyh: false`**: si la última ubicación conocida está
  dentro de CYH no hay alerta (el GPS se apaga al guardarla); fuera de CYH y
  con más de 24 h sin señal, sí. Los colores del tablero no cambian.
- **"Ver máquinas sin geocerca de los últimos 30 días"** (desplegable, en
  rojo, debajo del listado): todas las que trabajaron sin geocerca en ese
  plazo (también las de más de 7 días): máquina, fechas, días trabajados,
  horas, hectáreas aproximadas y mapa. Una línea por máquina y lugar.
- **Detalle por máquina** (al apretarla): sus últimos 30 días, por día: en qué
  geocercas trabajó (horas en movimiento dentro de cada una y hectáreas del
  historial) o si fue sin geocerca (horas, hectáreas aproximadas y mapa),
  labor, horas, hectáreas y dónde quedó al final del día (lugar, hora y
  mapa). Los días completos se guardan y se reutilizan; la primera corrida
  baja los 30 días (~880 días-máquina), después solo lo que falta y hoy.
- **Qué es trabajo sin geocerca** (las alertas, sin cambios): mismo criterio
  de las hileras (tramos rectos a velocidad de trabajo, alineados y en serie;
  al menos 6 pasadas por zona), al menos 4 líneas distintas que cubran 12 m
  de ancho (no caminos), horas solo en movimiento (≥ 1 km/h, intervalos de
  hasta 10 min, más giros de cabecera), **mínimo 1 hora por día**
  (`horas_minimas_alerta`). Plazo de **30 días** (el mismo de la
  recuperación de geocercas nuevas).
- **Al crear la geocerca** en Wialon la alerta desaparece: cuenta como
  resuelta si la mayoría de sus pasadas caen dentro de geocercas (desde el
  5-oct-2026 también si quedan repartidas en varias vecinas, ej. Aurora 19 y
  22).

## Geocercas nuevas (activa en la corrida diaria)

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
- Límites: una geocerca creada durante el día espera a la corrida diaria
  siguiente (el tablero de la flota quita sus alertas antes, en la corrida
  de cada 4 horas), y el trabajo anterior a 30 días no se recupera solo: para
  eso está la recuperación manual con fecha de inicio (ver abajo).

## Recuperación manual de geocercas (con fecha de inicio)

Para calcular geocercas creadas tarde (trabajo anterior a los 30 días de la
recuperación automática) o volver a calcular algunas, sin tocar las demás.
Se lanza a mano el workflow "Reporte diario de hectareas" (Actions → Run
workflow) con:

- `fecha_inicio`: desde cuándo (AAAA-MM-DD), ej. `2026-09-01`.
- `fecha_fin`: hasta cuándo, normalmente ayer, ej. `2026-10-06`.
- `recuperar_geocercas`: qué geocercas, separadas por coma. Cada una puede ser
  un nombre exacto (`Aurora 23`), un campo completo (`Avoamerica` = todas las
  Avoamerica; es la raíz del nombre, sin el número) o un rango de números
  (`Candelaria 5-12`). Sin importar tildes ni mayúsculas.
- Los demás campos vacíos.

Ejemplo: `fecha_inicio` 2026-09-01, `fecha_fin` 2026-10-06,
`recuperar_geocercas` "Aurora, Avoamerica, Candelaria 5-12, Puerto Lampa".

Qué hace (`RECUPERAR_GEOCERCAS`): primero borra los resultados de esas
geocercas desde `fecha_inicio` (historial, fechas de las hileras en la
memoria —se borran las hileras que solo tienen fechas desde ese día—,
avance y pasadas de barrido), y después las calcula en todas las labores y
con todas las máquinas en ese período; así nada se cuenta dos veces y lo
anterior a `fecha_inicio` se mantiene. Las registra como conocidas (otras
geocercas nuevas siguen esperando la corrida diaria). No toca las demás
geocercas ni el panel de máquinas. Costo: ~40 min por mes de GPS.

Registro:
- 7-oct-2026: recuperación del 2026-09-01 al 2026-10-06 de Aurora 1–25,
  Avoamerica 1–45, Candelaria 5–12 y Puerto Lampa 1–4 (82 geocercas, 35 min,
  sin errores; la corrida diaria de esa noche ya las había detectado desde el
  7-sep). Recuperado: Aurora – Poda 76,28 ha, Avoamerica – Picado 68,34 ha
  (Avoamerica 31 se picó el 4-sep, antes de los 30 días automáticos),
  Candelaria 5–12 – Barrido 25,56 ha, Puerto Lampa – Barrido 15,91 ha.
  Calibración de Aurora sin cambios (Aurora 1/2/4 al 22-09: 92,4 % / 92,2 %
  / 4,83 ha; Aurora 3, 5–9 ≥ 99,4 %).
- Pendiente: el Tractor 13 trabajó en hileras el 2 y 3-sep (~12 ha de poda)
  en -35.584, -71.477, sin geocerca (la más cercana, agrosocoin 1, está a
  4,7 km). Cuando el usuario cree esa geocerca, recuperarla con
  `fecha_inicio` 2026-09-01 y su nombre en `recuperar_geocercas`.

## Pendientes

- **Pasadas sueltas pendientes** (regla aprobada por el usuario el
  1-oct-2026, **falta implementar**): solo se rescatan cuando la misma
  labor vuelve a TRABAJAR de verdad el cuartel, no cuando solo pasa, gira o
  corta una esquina (ej. GS 9: las pasadas de barrido del 04-03 no se
  rescatan con el 20-03). Bloqueo: no hay un criterio automático confiable
  de "trabajo de verdad" en cuarteles chicos con GPS de 30–60 s (ver
  Gonzalo Sánchez); falta acordarlo con el usuario. Diseño:
  1. Cada día, por máquina + cuartel + labor, las pasadas de ese día se
     clasifican: "trabajo" o "sueltas" (las que hoy se descartan). Las
     sueltas se guardan en la memoria marcadas como pendientes, con su
     fecha; no suman.
  2. Cuando otro día posterior la misma labor (cualquier máquina de la
     labor) trabaja ese cuartel, las pendientes anteriores pasan a contar
     junto con el trabajo nuevo, desde ese día.
  3. El avance nunca baja: las rescatadas solo agregan celdas; las
     hectáreas nuevas se acreditan el día del rescate (máximo nuevo − máximo
     anterior). Los días pasados del historial no se reescriben.
  4. Barrido: las rescatadas se suman a la pasada en curso del día del
     rescate (el repaso), nunca a una pasada ya cerrada.
  - Los días de `trabajo_descartado` nunca rescatan pendientes.
- Longaví 8 y 5: los casos de calibración son del día 27-06 solo; en el año
  completo el Tractor 11 ya había trabajado esos cuarteles antes, así que se
  verifican solo con la prueba de ese día (2,55 ha y 0 ha).
- Pasadas sueltas pendientes en poda, picado y las demás labores: aprobada,
  falta implementar (en barrido ya se aplica, ver "Barredoras").

## Recálculo por labores

- Entrada `labores` del workflow (ej. `Poda,Picado,Barrido`, variable
  `LABORES_RECALCULO`): solo se bajan y procesan las máquinas de esas
  labores; el avance, el historial, los mapas y la web se arman con la
  memoria de todas. No se toca el panel de máquinas ni se calculan geocercas
  nuevas. Antes se limpian solo los resultados de esas labores (memoria de
  sus máquinas, sus entradas en `_avance_por_labor.json`, `_estilo_maquinas`
  e historial, y la geometría de sus máquinas).
- En este modo **no se registran geocercas como conocidas**: una geocerca
  creada mientras corre el recálculo queda como nueva y la corrida diaria
  recupera sus 30 días en todas las labores.
- 5-oct-2026: recálculo de Poda, Picado y Barrido del 2026-01-01 al
  2026-10-04, por quincenas (19 tramos de 7 a 17 min, sin errores), con la
  corrida diaria pausada (pedido por el usuario tras las correcciones 1–4).
  Un tramo registró como conocidas Aurora 19–22 (creadas ese día) sin
  recuperar las otras labores: se sacaron de la lista y se limpiaron sus
  resultados (memoria, avance e historial) para que la corrida diaria las
  calcule con sus 30 días en todas las labores. Corrida diaria reactivada a
  las 05:00 UTC.

## Registro del relanzamiento (2-oct-2026)

- Pedido por el usuario; lo lanzó Claude con el token del Llavero. Antes:
  casos de calibración verificados (todos ✓ con GPS crudo) y limpieza solo
  de resultados calculados (commit 821f645: memoria_hileras/*.json,
  docs/datos/geometria, docs/datos/kml, hileras_detectadas.kml,
  avance_cuarteles.json, historico.json vacío).
- 19 quincenas del 2026-01-01 al 2026-10-01, una a la vez, de 7 a 26 min
  cada una (lejos del límite de 6 h). Corrida diaria pausada mientras duró
  y reactivada al terminar (commit 9f32280). Mac despierto con caffeinate.
- Incidente: el tramo 2026-01-16 a 2026-01-31 falló al guardar la geometría
  de la web (los puntos de cruce del límite tenían números de numpy y un
  valor sí/no de numpy no se puede escribir en JSON). No alcanzó a subir
  nada. Se arregló (commit 724c983), se probó localmente con datos reales y
  se reanudó desde ese tramo; el resto terminó sin errores.
- Resultado: 1.031 geocercas en uso, 505 cuarteles con avance, 1.199 líneas
  cuartel + labor, 143 líneas de repaso de barrido. Panel al 2026-10-01: 9
  máquinas en CYH, 47 máquinas/lugares trabajando sin geocerca (30 días).
- Calibración con los datos del relanzamiento: Aurora 1/2/4 al 22-09 92,4 %
  / 92,1 % / 4,83 ha ✓; Aurora 3, 5–9 ≥ 99,4 % ✓; Solfrut 8 100 % ✓;
  Solfrut 10 92,3 % ✗; Longaví 15 y 16 100 % ✓; JV4 Barrido 0 % y Cosecha
  50,9 % ✓; Viconto 7–9 abr 5,28 ha ✓ (+12 %); Viconto 4 8–9 abr 8,72 ha ✓
  (−6 %); AA7 99,9 %, AA8 99,6 %, Don Cristóbal 99,3 % ✓; El Volcán 14
  Cosecha 98,6 % ✓ y Picado 93,5 % (aceptado) ✓; GS 2 Barrido 100 % +
  repaso 46,7 % ✓, Remecido 99,4 % ✓, Picado 92,6 % ✗; GS 7 Barrido 0 % ✓;
  GS 8 Barrido 100 % + repaso 61,4 %, Picado y Remecido 100 % ✓; N3
  Barrido del 23-09 0,32 ha ✗ (ver pendientes); Longaví 8/5 no comparables.
