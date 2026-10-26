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

## Informe para el cliente (Excel y PDF) — reglas del usuario, 7-oct-2026

- Una sola versión, filtrable por uno o varios campos (raíz del nombre:
  "Aurora", "Avoamerica") y por período (desde – hasta). Solo los campos
  filtrados; sin alertas ni trabajo fuera de geocerca.
- Hoja "Resumen" (y si hay varios campos, además una hoja "Resumen <campo>"
  por cada uno):
  - Encabezado: C&H Maquinaria, campo(s), período, labores incluidas y fecha
    de emisión.
  - Indicadores: hectáreas trabajadas, cuarteles completos, cuarteles en
    proceso, días trabajados, máquinas utilizadas.
  - Trabajo por día: una fila por día con las hectáreas por labor y total
    del día; total al final.
  - Avance por cuartel (cuarteles trabajados en el período): labor, área de
    la geocerca, hectáreas en el período, % de avance y estado al último día
    del período (completo en verde, en proceso en amarillo), fecha en que se
    completó; en barrido, pasadas completas en el período. Total al final.
- Hoja "Por máquina": hectáreas por máquina y día, labor, cuarteles
  trabajados, total por máquina.
- Hoja "Detalle": por cuartel, día y máquina.
- Hoja "Notas": cómo se calcula, en simple.
- Formato: títulos claros, encabezados verdes, filas alternadas, miles y 2
  decimales, % con 1 decimal, columnas ajustadas, encabezados fijos.
- PDF: el resumen general y el de cada campo, más un mapa de cada campo con
  los cuarteles coloreados (verde completo, amarillo en proceso con su %,
  gris sin trabajo en el período).
- **Cuartel completo = área total** (también en la página y el historial): al
  llegar al 95 % se acredita el área total de la geocerca; la diferencia se
  suma el día en que se completó (repartida entre las máquinas de ese día) y
  después ya no suma. En barrido, cada pasada completa ya suma el área total.
  No requiere recalcular el GPS: se ajusta el historial y el avance.
- **Implementado (7-oct-2026)** en la página: botón "Descargar informe" →
  elegir campos (lista con buscador) y fechas → "Descargar Excel" o
  "Descargar PDF". Se arma en el navegador (`docs/informe.js`, con ExcelJS,
  jsPDF y jspdf-autotable desde cdnjs) con `historico.json`,
  `avance_cuarteles.json` (`cierres` = día en que se cerró cada pasada de
  barrido) y `geocercas.json` (contornos de las geocercas en uso, lo publica
  la corrida diaria). En el PDF, un mapa por grupo de cuarteles cercanos (a
  menos de 400 m entre sí), ej. Aurora en 4 grupos.
- **Regla del área total aplicada (7-oct-2026)**: en la corrida diaria
  (`fraccion >= umbral` → 1,0 al acreditar y en el avance) y una vez sobre
  los datos ya calculados: historial 5.403 → 5.328 registros, 8.201,08 →
  8.227,79 ha (329 cuarteles + labor completos, cada uno suma exactamente su
  área); 230 avances llevados a 100 %.
- Ejemplo con datos reales (Aurora y Avoamerica, 1 al 30-sep-2026):
  123,04 ha (122,90 sin la regla del área total), 25 días, 5 máquinas, 45
  cuarteles trabajados (30 completos al 30-09).

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

## Reporte diario por correo (en construcción, pedido del usuario 19-oct-2026)

- `reporte_correo.py` + `.github/workflows/correo.yml`. Modos (`modo`):
  `vista_previa` (no envía; HTML+PDF como archivo de 1 día que se borra apenas
  se descarga), `prueba` (solo a `CORREO_PRUEBA`), `diario` (el envío normal)
  y `atraso` (medición de GPS tardío, solo lectura). Tarda ~2–3 min.
- **Envío diario ACTIVO desde el jueves 22-oct-2026** a todos los de
  `CORREO_DESTINATARIOS` (4 direcciones), a las 07:45, con Cloudflare y los
  horarios de GitHub de respaldo. El 21-oct se mandó a mano (`modo` `todos`)
  el reporte del 20-oct a las 4 direcciones: 0 rechazos y 0 rebotes (el modo
  `todos` deja la marca del día y revisa rebotes en la casilla que envía,
  sin mostrar direcciones). Sin `CORREO_DESTINATARIOS` el modo diario no
  envía nada. **Los avisos de falla y de atraso van solo a `CORREO_PRUEBA`**
  (el usuario), no a todos. Mientras no se apruebe el recálculo de la rama
  `dia-chile`, el correo y el PDF llevan arriba "Marcha blanca: algunos
  números se están ajustando" (`correo_marcha_blanca` en `config.json`,
  por defecto sí): quitarla al pasar el recálculo a main. Lógica:
  - Lo lanzan: el Worker de Cloudflare a las 07:30 y 09:00 de Chile; los
    horarios de GitHub de `correo.yml` como respaldo (07:40 y 09:10); y
    `workflow_run` al terminar la corrida de la noche. Todos usan la marca del
    día `docs/datos/correo_enviado.json` (fecha y horas, sin direcciones):
    el correo sale una sola vez.
  - Antes de las 07:30 no hace nada. Si la corrida de la noche ya procesó
    ayer (`docs/datos/ultima_corrida.json`), arma el reporte, espera hasta
    las 07:45:00 y lo envía (si termina después, sale apenas esté).
  - Si la "Corrida de la noche" (nombre de la corrida en `diario.yml`) falló:
    correo corto con el paso que falló, las últimas líneas de error y el
    enlace. Si se vuelve a correr y termina bien, el reporte sale solo.
  - A las 09:00 sin terminar: aviso de atraso (una vez) y después el reporte.
  - Si el reporte no se puede armar: correo corto con el error.
  - Con varios destinatarios van en copia oculta.
- **Corrida de la noche**: guarda `docs/datos/ultima_corrida.json` (día
  procesado) y no repite un día ya procesado (si la lanzan Cloudflare y el
  horario de respaldo de GitHub). Antes de correr trae lo último de GitHub.
- **22-oct-2026, primer día real: el correo NO salió a las 07:45** (el usuario lo
  mandó a mano a las 08:14 con `modo` `todos`). En GitHub no hubo ningún
  `workflow_dispatch` del Worker a las 03:00 ni a las 07:30 (la corrida partió
  por el horario de respaldo a las 06:54 y terminó 07:23; el correo lanzado al
  terminar no hizo nada por ser antes de las 07:30). Cambios:
  - Corrida de la noche a las **00:30 de Chile** (Cron `30 3,4 * * *` en vez de
    `0 6,7 * * *`); mismo GPS tardío perdido que a las 03:00 (medición 20-oct).
  - Respaldos de GitHub en minutos que no son en punto: `diario.yml` 00:37,
    02:13 y 04:07 de Chile (cada uno dos veces, verano/invierno; la corrida no
    repite un día ya procesado); `correo.yml` 03:23, 05:47, 07:43 y 09:07.
  - **El correo no se rinde**: si parte antes de las 07:30 (fin de la corrida
    o un respaldo) espera dentro de GitHub, arma el reporte a las 07:30 y sale
    a las 07:45; si la espera supera 5 h 15 min espera eso y se relanza solo
    (`relanzar_correo`); si la corrida termina después de las 07:45 sale apenas
    esté. La marca del día evita duplicados (`correo.yml`: `actions: write`,
    `timeout-minutes: 345`).
  - **Causa (confirmada por el usuario en Cloudflare)**: los Cron Triggers del
    Worker se habían borrado ("No cron triggers configured"; 2 invocaciones,
    0 subrequests), no fue el token. El usuario los volvió a poner el
    22-oct-2026 a las 09:56: `0 6,7 * * *`, `30 10,11 * * *` y `0 12,13 * * *`,
    y dejó desplegado el Worker antiguo (reemplazado por el nuevo a las 16:23,
    ver abajo). La corrida la cubren el Worker a
    las 03:00 o los respaldos de GitHub (desde las 00:37). **Pendiente** (cuando
    el usuario quiera): pegar el `cloudflare/worker.js` nuevo (corrida a las
    00:30, `/probar`, `/confirmar`) y cambiar el Cron `0 6,7 * * *` por
    `30 3,4 * * *`; sin eso los botones de confirmar campo no funcionan.
  - **Worker nuevo desplegado por el usuario el 22-oct-2026 a las 16:23**
    (`cloudflare/worker.js` de main). Cron Triggers revisados después del
    Deploy: `30 3,4 * * *`, `30 10,11 * * *` y `0 12,13 * * *` (borró
    `0 6,7 * * *`). `/probar?hora=07:30` respondió "OK: GitHub acepto lanzar
    correo.yml (07:30). token cargado"; esa corrida no mandó un segundo
    correo ("El reporte de hoy ya se envio a las 08:14"). Dirección:
    `https://disparador-reporte.dawn-band-fd6c.workers.dev/confirmar` (**con
    `/confirmar`**: el Worker solo recibe POST ahí; sin la ruta responde 404 sin
    CORS y la página decía "No se pudo conectar"; las páginas agregan
    `/confirmar` si falta), guardada en
    `config.json` → `url_confirmaciones` (y en `url_confirmar` de
    `reporte_diario.json` y `sin_geocerca.json`): botones de confirmar y
    equivalencias activos. CORS solo desde `https://jpfernandez428.github.io`
    (verificado).
  - Worker (desplegado el 22-oct-2026): prueba a mano `GET /probar?hora=00:30|07:30|09:00` (lanza esa
    tarea al tiro y muestra la respuesta de GitHub y si el token está
    cargado; inofensivo por las marcas del día); errores al lanzar quedan en
    los registros de Cloudflare.
- **Cloudflare** (configurado por el usuario el 21-oct-2026; `cloudflare/worker.js`,
  Worker `disparador-reporte`; solo tiene el disparador programado, sin
  respuesta web: entrar a su dirección workers.dev no lanza nada): Cron
  Triggers `30 3,4 * * *` (00:30 de Chile: corrida de la noche; antes `0 6,7 * * *`), `30 10,11 * * *`
  (07:30: correo) y `0 12,13 * * *` (09:00: aviso de atraso). Cada horario va
  dos veces (verano UTC-3 / invierno UTC-4) y el Worker lanza solo el que
  calza con la hora de Chile. Secreto del Worker: `GITHUB_TOKEN` (token
  fine-grained solo de este repositorio, Actions: Read and write; lo carga el
  usuario en Cloudflare, nunca en el chat ni en el repositorio). Los horarios
  de GitHub siguen activos como respaldo (regla del usuario 20-oct-2026).
- **Token del Worker sin vencimiento** (el usuario lo creó así el 21-oct-2026):
  no hay aviso de renovación en el correo.
- **Tres piezas** (cambios del usuario del 21-oct-2026, reemplazan lo anterior):
  1. **Correo corto** (`armar_html_corto`): "Resumen de ayer (lunes 19-10-2026)"
     con máquinas que trabajaron, ha en geocercas + ~ha estimadas sin
     geocerca (al lado, sin sumar), horas, km camionetas (cuántas de 9 se
     movieron) y km camión; alertas en 2 líneas (GPS sin señal: máquinas y
     desde cuándo; trabajo sin geocerca: máquinas y ~ha); "Máquinas · ayer
     (19-10)": Máquina | Labor · lugar | Ha | Horas, sin geocerca destacada con
     "(~3,8)", total "14,97 (+~12,6)"; "Camionetas · ayer": Camioneta | Dónde
     estuvo (en orden, " · ", campos en negrita y comunas normal, con nota) |
     Km y total; "Camión · ayer": una línea con km, salida–llegada y recorrido
     (CYH → Nancagua → …); últimos 7 días (totales y día por día: Día | Máq. |
     Hectáreas | Horas | Km cam. | Km camión); trabajo sin geocerca en una
     línea (lugares, horas, ~ha y los 4 que más pesan). Cada sección con
     "Ver detalle" a `reporte.html#<sección>`.
  2. **PDF adjunto** = detalle completo (`armar_html`, el reporte largo).
  3. **Página `docs/reporte.html`** (datos `docs/datos/reporte_diario.json`,
     los publica el correo diario y la prueba): todo resumido y se despliega
     al tocar. Camionetas → 7 días (km, salida–llegada, lugares) → al tocar
     un día, las visitas reales en orden con hora de llegada, tiempo ahí y
     mapa. Camión → 7 días con el recorrido. Máquinas → días con dónde
     trabajó, ha (~ha sin geocerca) y horas. Trabajo sin geocerca → una fila
     por lugar (todas las fechas y máquinas de la misma comuna juntas) con
     "cerca de <campo>", rango, horas y ~ha → días con máquina, horas, ~ha y
     mapa. Anclas: `#resumen`, `#maquinas`, `#camionetas`, `#camion`,
     `#semana`, `#sin-geocerca`. Enlazada desde `index.html`.
  - **Privacidad (pendiente, 21-oct-2026)**: la página es pública (el usuario
    lo aceptó por ahora; muestra recorridos de las camionetas). Falta
    protegerla con clave (Cloudflare Access).
- **Hectáreas estimadas sin geocerca** (reglas del usuario 21-oct-2026, en el
  correo y la página): horas sin geocerca × rendimiento real de la máquina =
  ha acreditadas ÷ horas en geocercas, en los días de los últimos 30 con
  ambas cosas y **sin los días en que se completó un cuartel** (ese día se
  acredita el área total; en barrido, los días de cierre de una pasada).
  Propio si tiene al menos 3 días y 10 h de esa labor (`dias_minimos_rendimiento`,
  `horas_minimas_rendimiento`); si no, el promedio de la flota en su labor
  (misma regla); sin referencia, el cálculo del GPS. El cálculo del GPS (el del panel Flota, `ha_aprox`) suma el largo
  de las pasadas × espaciado (2,5–5 m): cuenta dos veces lo que se repasa,
  por eso las barredoras daban 2–3,8 ha/h y su rendimiento real es ~1,1–1,8
  ha/h. El panel Flota sigue con el cálculo del GPS (no se cambió).
- **Área total sin repetir** (regla del usuario 21-oct-2026): en totales, cada
  cuartel + labor cuenta una sola vez (área total y N° de cuarteles); las
  hectáreas trabajadas sí se suman todos los días. Corregido en la tabla
  principal de la página y su descarga (`areaUnica`); el informe para el
  cliente ya lo hacía. Ej. Shacker SBS 8 en Patricio Schlak, 16 y 17-oct:
  área total 7,88 → 3,94 ha, 1 cuartel, 3,94 ha trabajadas.
- **Horómetro** (21-oct-2026): todas las máquinas tienen sensor "Ignición"
  (`io_239`) en Wialon; el horómetro es el contador de horas de motor de cada
  unidad (`cneh`). Sale en el panel Flota (columna y detalle de cada
  máquina), no en el correo. Revisión de solo lectura: `modo` `sensores` de
  `correo.yml` (Excel "Horómetro según Wialon" en Descargas del usuario).
- **Máquinas: sin km en ninguna parte del correo** (pedido del usuario). Solo
  hectáreas (historial), horas y geocercas (tablero de la flota: horas en
  movimiento dentro de geocercas + horas sin geocerca). "Trabajó" = ha > 0,
  ≥ 1 h en alguna geocerca o trabajo sin geocerca. Las máquinas sin señal
  hace más de 30 días se siguen revisando todos los días (corrida de la
  noche y tablero): si una vuelve a transmitir o trabaja, aparece normal ese
  mismo día.
- **Vehículos: solo km y lugares, sin horas.** Km = recorrido GPS del día
  (hora de Chile) sin puntos detenidos (< 3 m, `adelgazar_puntos`) ni saltos
  (punto al que se va y del que se vuelve a más de 160 km/h); menos de 0,5 km
  = no se movió. Salida–llegada = primer y último movimiento. Lugares
  (aprobado por el usuario): CYH, campo de cada geocerca con ≥ 5 min adentro
  y la comuna de cada parada de ≥ 15 min fuera de geocercas (buscador de
  direcciones de Wialon, solo lectura; sin comuna → coordenadas con mapa).
  Donde quedó uno que no se movió: su último punto del día (si no tiene,
  el último anterior).
- **Vehículos** (`config.json` → `vehiculos`, 12 confirmados por el usuario el
  19-oct-2026, con su nombre de Wialon; el camión lleva `"tipo": "camion"`):
  no entran al cálculo de hectáreas ni al panel Flota. KFHF20 FORD RANGER y
  SKTY32 MAXUS T90 están con `"activo": false` (fuera del correo, pedido del
  usuario 20-oct-2026; no borrarlas): quedan 9 camionetas y el camión.
- Por máquina (7 días): un día cuenta si la máquina trabajó o tuvo horas.
- **Trabajo sin geocerca · últimos 7 días** (pedido del usuario 20-oct-2026,
  para saber dónde crear geocercas): las alertas del tablero de esos días,
  un lugar por fila (se juntan días y máquinas a menos de 600 m,
  `distancia_mismo_lugar_m`). Lugar = comuna (direcciones de Wialon) y
  "cerca de <campo>" si hay una geocerca a menos de 5 km. Columnas: Lugar |
  Máquinas | Días | Horas | Ha aprox. | Mapa.
- Los datos de las camionetas no se guardan en el repositorio (es público).
- Gmail con contraseña de aplicación; secretos `CORREO_USUARIO`,
  `CORREO_CLAVE`, `CORREO_PRUEBA`, `CORREO_DESTINATARIOS` (los carga el
  usuario; nunca en el código).
- **Atraso de la corrida de la noche (revisado 19-oct-2026)**: no es nuestro.
  GitHub crea la corrida tarde (hora de creación = hora de inicio, 0 min en
  cola, ninguna cancelada) y desde el 15-oct además se salta corridas del
  tablero de cada 4 h. Inicio de la de 05:00 UTC: 16-oct 09:34, 17-oct
  09:05, 18-oct 09:23, 19-oct 10:36 UTC.
- **Medición del 20-oct-2026 respecto de la medianoche de Chile** (14 días,
  298.421 mensajes de 88 unidades): 82 llegaron después de las 00:00 del día
  siguiente, 58 después de 00:15, 57 después de 00:30–01:30, 55 después de
  02:00–05:00 y 53 después de 08:00 (casi todos de las camionetas FZYB36 y
  SDFD14; de máquinas ~21 en 14 días, algunos con 4 días de atraso). El GPS
  atrasado llega en minutos o recién días después: partir a las 03:00 de
  Chile pierde lo mismo que a las 08:00. Hora elegida: 03:00 de Chile.
- Datos GPS que llegan tarde (7 días, 168.038 mensajes): 26 llegaron después
  de las 04:23 UTC del día siguiente y los mismos 26 después de las 05:00 (23
  de la camioneta FZYB36, 3 de máquinas). Adelantar la corrida no agrega
  pérdida. No volver a procesar un día ya calculado: el historial reemplaza
  el registro y el avance ya está en su máximo, así que quedaría en ~0 ha.
- **Pendiente (pedido del usuario 19-oct-2026, esperando su OK al plan):**
  que el día vaya de 00:00 a 24:00 hora de Chile en TODO el sistema
  (historial, página, panel Flota, correo). Hoy la corrida de hectáreas baja
  el GPS por día UTC (`obtener_mensajes`, `FECHA_INICIO/FIN` con
  `utcnow`, `desde_alertas`), mientras el tablero y los cierres de barrido
  ya usan hora de Chile. Plan aprobado por el usuario el 20-oct-2026: código
  en la rama `dia-chile` (`obtener_mensajes` de 00:00 a 24:00 de Chile,
  ayer y plazo de alertas en hora de Chile; `diario.yml` corre en otra rama
  con su propio grupo y sube a esa rama). Recalcular el año en la rama por
  quincenas, comparar los casos de calibración y los cuarteles que cambien
  más de 2 puntos, y **no reemplazar el historial de main sin el OK del
  usuario**. Limpieza en la rama aprobada y hecha (2.311 memorias, 73
  geometrías, avance, KML, historial vacío); recálculo del 1-ene al 19-oct en
  20 tramos de 10–21 min (20-oct, 15:58 a 22:12), sin fallas. Comparación
  (`comparar.py`, hasta el 19-oct): casos de calibración iguales o a menos de
  1 punto; en el mismo período que main tenía calculado, −1,30 ha de 8.359
  (−0,02 %). Las diferencias grandes no son del día de Chile: la rama
  calculó todo el año en geocercas que main solo tenía desde su creación o
  recuperación (Avoamerica, Candelaria, Puerto Lampa: +330 ha de abril a
  agosto) y 13 Avoamerica que main nunca tuvo. Falta el OK del usuario para
  pasar a main.
- **Arreglo 20-oct-2026**: la corrida de esa noche armó el tablero de la flota
  sin la última conexión de ninguna máquina (63 "Sin datos GPS"): la sesión
  de Wialon vence tras 5 min sin uso y entre la última descarga y el tablero
  pasaron más. Ahora se vuelve a conectar antes del tablero y, si Wialon
  responde error, la corrida falla en vez de publicar un tablero vacío. El
  correo tampoco se arma si `flota.json` viene sin conexiones.

## Pendientes

- **Shacker SBS 6, Rodrigo Bunster C2 y C4, 19 y 20-oct (revisado 21-oct-2026,
  solo lectura)**: el GPS muestra trabajo real (11–14 pasadas de 124–140 m por
  geocerca y día, un punto cada ~50 s), pero se acreditan 0 ha porque esos
  cuarteles quedaron al 100 % de "Cosecha con recibidor" en febrero (Shacker
  SBS 13) y el avance nunca baja. Se corrige con las temporadas (raleo
  separado de la cosecha): daría ~47 % de cada cuartel (2,13 + 2,34 ha).
- **Reglas decididas por el usuario el 21-oct-2026 (a implementar en la rama
  `dia-chile`; recalcular solo después de que apruebe la lista de tractores
  fuera de temporada y la zona de los campos)**:
  - Temporadas: barrido igual que hoy; **Cosecha** (Shacker SBS) ene–may
    desde cada 1 de enero; **Raleo** (Shacker SBS) sep–nov desde cada 1 de
    septiembre, labor aparte (mismas reglas de pasadas que la cosecha con
    recibidor); picado y poda abr–oct desde cada 1 de abril; remecido de
    suelo y recolección ene–may desde cada 1 de enero. Fuera de temporada se
    cuenta igual, con alarma.
  - Shacker SBS en jun–ago o diciembre: **"Revisar labor"**, con alarma, sin
    sumar a ningún avance hasta que el usuario diga cuál fue.
  - Tractores de picado/poda fuera de su temporada: si en ese campo y día
    hubo cosecha (shakers, barredoras, recogedoras) es **"Recolección
    (tractor con recogedora)"** con la temporada de cosecha; si no, "Revisar
    labor" con alarma y sin sumar. Lista de casos mostrada al usuario
    (nov–mar: 3 casos, 69,7 ha, todos con cosecha el mismo día; abr–may está
    dentro de la temporada de picado/poda: 422,7 ha con cosecha el mismo
    día, pendiente que el usuario diga si también aplica).
  - **REPASO**: un cuartel + labor que ya llegó al 95 % en la temporada y se
    vuelve a trabajar es una pasada nueva con sus propias hectáreas, se
    muestra como "REPASO" y levanta alarma. Solo si al menos 3 pasadas del día,
    en hileras distintas una al lado de la otra, van **por hileras ya pasadas
    esa temporada** (por cualquier máquina de la labor; regla del 22-oct-2026).
    Si van por hileras nuevas es terminar el trabajo (ej. las saltadas de un
    patrón ancho, que ya contaban) y no suma; cruzar un cuartel no cuenta.
    (El primer recálculo marcaba repaso con 3 pasadas en paralelo cualquiera:
    117 repasos falsos, ej. Longaví 16 con un repaso del 100 %.)
  - Shacker de Suelo SÍ cuenta como shaker para la recolección con tractor
    (después del remecido se recoge con tractor con recogedora o con
    recogedora autopropulsada): Gonzalo Sánchez 2, 7 y 8 en feb–mar quedan
    como "Recolección (tractor con recogedora)" (confirmado 22-oct-2026; antes
    eran casos de calibración de picado).
  - **Horas**: siempre según el sensor de encendido; si el sensor está malo o
    sin datos, la regla anterior (movimiento + paradas de hasta 15 min dentro
    del cuartel entre la primera y la última pasada del día). Sensor que
    parece malo (apagado mientras trabaja, o encendido todo el día): alarma
    en la página.
  - **Horas por campo**: por máquina, horas con motor encendido desde que
    llega al campo hasta que se va, separadas en trabajando (dentro de los
    cuarteles) y traslado u otras (dentro del campo fuera de los cuarteles,
    y el camino entre grupos lejanos de cuarteles del mismo campo). La
    estadía se corta al ir a otro campo o volver a CYH; entre campos van en
    camión y no cuenta. Zona del campo propuesta: cuarteles del mismo campo a
    menos de 500 m forman un grupo, y cada grupo se agranda 150 m (pendiente
    del OK del usuario). Tractores: acumulado de la estadía ("Tractor 4 en
    Avoamerica desde 13-10: 45 h = 38 h trabajando + 7 h traslado u otras")
    y detalle por día, en la página y el PDF; propuesta para el correo en la
    próxima prueba. Las demás máquinas igual, con menos protagonismo. El
    rendimiento (ha/h) usa las horas trabajando.
  - Geocercas nuevas: recuperar 90 días (no 30), en una corrida aparte para
    no atrasar el correo; si ya había trabajo seguido antes de esos 90 días,
    aviso en el correo y la página (ha y desde qué fecha).
- **Recálculo encadenado en GitHub (desde el 21-oct-2026, no depende del Mac)**:
  en la rama de prueba, `diario.yml` (versión de la rama) espera si main
  tiene en curso la corrida de la noche o el correo, y al terminar bien un
  tramo lanza el siguiente (quincenas) hasta la fecha de
  `recalculo_plan.json` (`recalculo_cadena.py`; nunca corre en main; una falla
  corta la cadena). Recálculo con temporadas, repasos y día de Chile del
  1-ene al 20-oct lanzado el 21-oct (tramo 1 a mano, desde el 2 en cadena).
  Antes, el 21-oct, el tramo 1 falló por un corte de conexión con Wialon
  (sin commit): se agregaron reintentos a la descarga del GPS (rama y main).
- **Campos unidos** (`config.json` → `campos_unidos`, revisados por el usuario el
  21-oct-2026; las 1.031 geocercas en uso quedan en 150 campos): nombres distintos del mismo campo, para las
  horas por campo. Incluye El Volcán Nueces en El Volcán, A1–A15 en
  Ballerina, Campo Lolol AEC en Campo Lolol, Ochagavía Manantiales en
  Ochagavía, y Agrícola El Carmen junto con Ochagavía (San Gregorio). Mismo
  nombre a más de 20 km = campos distintos (ej. las 3 "Nueva geocerca").
- **Página Reporte de Hectáreas (21-oct-2026)**:
  - Botones de período [Ayer] [Últimos 7 días] [Mes ▾] [Año ▾]: solo cambian
    Desde/Hasta (que siguen editables) y aplican al tiro; el activo queda
    destacado. Ayer en hora de Chile; 7 días = los que terminan ayer; Mes y Año
    con un clic = el actual hasta ayer (el 1 del mes, el mes anterior
    completo), con selector para otro mes/año completo. Sin botón de
    temporada. Con filtros combinados, Desde/Hasta acotan además cada uno.
  - Filtro (reemplaza el buscador mezclado, 21-oct-2026): botones [Por máquina]
    [Por campo]; la lista y el buscador muestran solo ese tipo, y debajo
    "Acotar por …" muestra lo otro que aparece en el resultado (ej. Por campo
    Avoamerica → sus máquinas; Por máquina Tractor 4 → sus campos). Al cambiar
    de modo se parte de cero.
  - (Antes) Filtro por campo en el mismo buscador: grupos "Máquinas" y "Campos"
    (`docs/datos/campos.json` = `campos_unidos` + cuarteles en uso, lo
    escribe la corrida de la noche; `campoDe()` en `informe.js`, común a la
    página, el informe y el mapa). Se busca por cualquier nombre o cuartel
    del campo ("Nueces" → El Volcán). Máquinas y campos marcados se combinan
    (solo esas máquinas en esos campos); se aplica en totales, tabla, avance
    por cuartel, mapa KML, filtros combinados, y el informe se abre con los
    campos y fechas del filtro.
- **Trabajo sin geocerca por campo (reglas del usuario 21-oct-2026)**:
  - `sin_geocerca.py` (paso de la corrida de la noche, después del programa):
    guarda TODO el trabajo sin geocerca en `docs/datos/sin_geocerca.json`
    (historial acumulado, no solo 30 días; con comuna de Wialon) y lo asigna:
    1) lugar confirmado (`config.json` → `lugares_confirmados`, a menos de
    600 m) → ese campo "confirmado" (o "ningún campo"); 2) campos con un
    cuartel a menos de 2 km: si la máquina trabajó en un cuartel de ese campo
    ese día o está entre dos días en que trabajó ahí sin ir a otro campo ni a
    CYH → "asignado"; si no, estadía ampliada (ese día no trabajó en otro
    campo ni pasó por CYH) → "probable"; con dos o más campos posibles no se
    elige: "probable: Aurora o El Volcán"; 3) si no, "sin campo". Las ha son
    estimadas (horas × rendimiento real) y nunca se suman al total exacto.
  - Página: con filtro de campo, "X ha en geocercas + ~Y ha estimadas sin
    geocerca" y la lista del campo; sin filtro, "Por confirmar", "Asignados",
    "Sin campo" y "Lugares confirmados · geocercas por crear en Wialon" (con
    mapa y Deshacer). Informe descargable: indicador, hoja (Excel) y página
    (PDF) "Trabajo sin geocerca (estimado)" con el campo y si es probable.
  - Confirmar desde la página (ABIERTO, sin clave, pedido del usuario; la
    clave con Cloudflare Access va después): botones "Aceptar <campo>" /
    "Es <campo>" / "No es de ningún campo" / "Deshacer" → POST al Worker de
    Cloudflare (`/confirmar`, solo desde la página publicada, valida datos)
    → lanza `confirmar.yml` → `confirmar.py` guarda la regla del lugar en
    `config.json` → `lugares_confirmados` (una por lugar; la nueva reemplaza)
    y el registro en `docs/datos/confirmaciones.json` (fecha, hora, lugar,
    campo, acción), y recalcula `sin_geocerca.json`. Dirección del Worker en
    `config.json` → `url_confirmaciones`.
- **Correo y página v2 con la planilla del Drive (pedido del usuario 22-oct-2026;
  en PRUEBA: el envío diario a todos sigue con la versión anterior hasta que
  el usuario apruebe)**:
  - Archivos (SOLO LECTURA, se leen en cada corrida; si no se pueden leer, el
    correo sale igual con un aviso): planilla "Maquinas en Operacion" (Excel,
    `planilla.URL_PLANILLA`; columnas Tractor | Maquina | Operador | Campo |
    Ubicacion | Fecha termino | Destino | PROX X CONFIRMAR; "Taller" = en CYH)
    **Compartida como "Cualquier persona con el enlace (Lector)"** desde el
    22-oct-2026 (antes pedía iniciar sesión y GitHub no la podía leer).
  - **Equivalencias de campos planilla → Wialon (desde el 23-oct-2026 en el
    sistema)**: `config.json` → `equivalencias_campos` ({nombre en la planilla:
    [campos de Wialon]}, varios por nombre; [] = sin geocerca por ahora). Se
    cargaron una vez desde la hoja del Drive "Equivalencias de campos" (que ya
    no se usa) más MGH = Nancagua SBS Campo. Las edita el usuario en la
    sección "Equivalencias" de `reporte2.html` (elegir nombre y campo de una
    lista con buscador → Guardar; Quitar / Borrar todo), con registro de fecha
    y hora en `docs/datos/confirmaciones.json`. Al confirmar un campo en
    "Máquinas en operación" con un nombre de planilla distinto, la
    equivalencia se guarda sola; en "Confirmar · GPS en otro campo" hay un
    botón "Es el mismo campo". Mismo camino que los otros botones (Worker →
    `confirmar.yml` → `confirmar.py`, acciones `equivalencia` y
    `borrar_equivalencia`). Se usan en el cruce con la planilla y en el
    buscador por campo de la página (`docs/datos/campos.json` →
    `equivalencias`, junto con la lista de campos de Wialon). Nunca se
    escribe en las planillas; en el repositorio solo queda máquina, operador,
    campo y destino (en `docs/datos/reporte_v2.json` → `v2`; antes en `reporte_diario.json`).
  - **Los nombres de operadores SÍ salen en la página y el correo** (autorizado
    por el usuario el 22-oct-2026).
  - Cruce de nombres por tipo y número (`planilla.cruzar_maquina`; solo
    unidades activas, sin las "No incluir"; números de modelo 95/100/108/115/
    185/420 no cuentan; "Autopropulsada" = Podadora 1).
  - Correo v2 (`reporte_v2.py`, `modo` `prueba_v2` de `correo.yml`, solo a
    `CORREO_PRUEBA`): 0) alerta roja grande si una máquina está en un campo
    según la planilla y su GPS lleva más de 15 días sin señal; 1) resumen de
    ayer + máquinas que trabajaron (Máquina | Labor | Operador | Dónde | Horas
    | Ha), camionetas y camión; 2) máquinas en operación fuera de CYH
    (planilla en un campo + GPS fuera de CYH): Máquina | Operador | Campo
    (planilla) con marca ✓ GPS calza (está o trabajó en los últimos 3 días en
    ese campo o su equivalente) / "sin geocerca · Posiblemente X" / "Confirmar
    · GPS en …" / "sin señal hace X días" | Promedio ha/día | Ayer ha; grupos
    "Fuera de CYH y no está en la planilla" y "GPS apagado hace más de 30 días"
    (solo con la última posición fuera de CYH); avisos "Actualizar planilla";
    3) alertas; 4) trabajo por campo en la temporada (una fila por máquina y
    campo; en el correo solo los campos con trabajo en los últimos 30 días, la
    página todos; ~ = incluye trabajo sin geocerca, asignado al campo
    confirmado o al de la planilla); 5) últimos 7 días. Cada sección con
    "Más información en la página" (`docs/reporte2.html`). PDF adjunto: el
    detalle completo de siempre.
  - **Barredora 5497** (`config.json` → `maquinas_no_cyh`): "No es de CYH (por
    revisar)"; sus horas y ha no se suman a nuestro trabajo ni a los totales.
  - Página `docs/reporte2.html` (versión nueva; la actual `reporte.html` sigue
    igual): buscador por máquina o campo; "Máquinas en operación" con filtros
    Todas / Trabajaron ayer / No calzan / Sin geocerca / GPS apagado; "Trabajo
    por campo": al tocar una fila, detalle por día y cuartel (horas y ha).
  - **Confirmar en la página (opción B, decidido por el usuario 22-oct-2026)**:
    en las "Confirmar": "Está en CYH" / "Está en el campo (GPS con falla)" (o al
    revés si la planilla dice Taller); en las "sin geocerca": "Confirmar: es
    <campo>" (mismo mecanismo de `lugares_confirmados`: aprende el lugar).
    Lo confirmado queda en `config.json` → `maquinas_confirmadas` (acciones
    `maquina` / `deshacer_maquina` de `confirmar.yml`) y genera "Actualizar
    planilla: <máquina> → <valor>" en la página y el correo hasta que la
    planilla cambie (la confirmación deja de aplicar sola cuando cambia el
    valor de la planilla). Activo desde el 22-oct-2026 (Worker nuevo y
    `url_confirmaciones`).
  - **Cambios del 22-oct-2026 (revisión del usuario)**: en "Máquinas en
    operación" siempre "Planilla: X · GPS: …" (`texto_gps`: "detenido sin
    geocerca en <comuna>, desde hace X h", "en movimiento en <campo>", "sin
    señal desde el …"), con mapa; también corto en el correo. Todas las "sin
    geocerca" tienen botones (lugar = último trabajo sin geocerca de 7 días o,
    si no hay, la posición GPS actual). Elegir campo con lista desplegable con
    buscador (campos de Wialon y sus equivalentes; la misma en Equivalencias).
    Sin ventanas emergentes: los avisos salen junto al botón. Equivalencias:
    lista completa (nombre en planilla, campo en Wialon, fecha del último
    cambio; "carga inicial 22-10-2026" si no tiene registro) y botón
    "Descargar Excel".
  - **Lista "Buscar campo" con nombres limpios** (22-oct-2026):
    `campos.json` → `nombres_lista` ({nombre interno: nombre para mostrar},
    `rh.nombre_lista_campo`): sin "Cuartel", "C", "Campo" ni números al final,
    sin "(id …" ("Nueva geocerca …690"), minúsculas con mayúscula inicial, y
    fuera de la lista los nombres basura ("Ag. nnnn", letras repetidas) y las
    geocercas de prueba "Maquina …" / "Cliente …" (`CAMPOS_FUERA_DE_LISTA`).
    Lo que se guarda sigue siendo el nombre interno (reglas y equivalencias
    no cambian). Con sus equivalentes: "Aurora (= Siracusa)".
  - **Después de cada confirmación se rearma `reporte_diario.json` → `v2`**
    (22-oct-2026; `reporte_v2.rearmar_pagina`, al final de `confirmar.py`):
    con lo ya publicado (flota.json, historial, sin_geocerca.json,
    config.json y la planilla del Drive), sin bajar GPS de Wialon; las
    comunas se toman de lo publicado y "Máquinas que trabajaron ayer" no
    cambia; si la planilla no se puede leer no toca nada. Lleva
    `actualizado` (fecha y hora). El cambio se ve en 2–3 minutos.
  - Un lugar confirmado (`lugares_confirmados`, a menos de 600 m del último
    trabajo sin geocerca de 7 días o de la posición GPS) deja la fila de
    "Máquinas en operación" en "confirmado: <campo> (sin geocerca)".
  - Al confirmar, la página dice "Confirmado, se verá en unos minutos" y
    bloquea los botones de esa fila; al recargar sigue así (en ese
    navegador, hasta 15 min) mientras los datos sean anteriores a la
    confirmación.
  - **Nunca una equivalencia del mismo nombre** ("Puerto Lampa = Puerto
    Lampa", sin importar mayúsculas, tildes, espacios ni signos;
    `planilla.mismo_nombre`): ni al confirmar, ni con "Guardar", ni con "Es el
    mismo campo" (la página no lo envía y `confirmar.py` lo rechaza). La de
    Puerto Lampa (creada el 22-oct a las 17:03) se borró desde la página.
  - Quitar el último campo de una equivalencia borra el nombre (antes quedaba
    como "sin geocerca por ahora"). Probado de verdad desde la página
    publicada el 22-oct-2026 (equivalencia "Prueba Claude" → Aurora, guardar y
    quitar).
  - **Actualizar desde la planilla (22-oct-2026)**: `planilla.yml` +
    `planilla_revisar.py` leen la planilla (solo lectura) y, SOLO si cambió
    (huella sha256 de máquina/operador/campo/destino en `v2.planilla_huella`;
    la planilla no se guarda), rearman `reporte_diario.json` → `v2` sin Wialon
    (`reporte_v2.rearmar_pagina(solo_si_cambio=True)`) y hacen commit; si no
    cambió, no suben nada. `v2.planilla_leida` = hora de la lectura. Lanzan:
    el Worker cada 30 min de 07:00 a 21:00 de Chile (Cron `*/30 * * * *`,
    `CRON_PLANILLA`, origen `cron`) y el botón "Actualizar desde la planilla"
    de la página (POST `/planilla` del Worker, origen `boton`;
    `/probar?hora=planilla` para probar). Choques: con `cron` se salta la
    revisión (la corrida se cancela sola) si está corriendo `diario.yml`,
    `correo.yml` o `confirmar.yml` en main; con `boton` espera hasta 20 min a
    `diario.yml` y `confirmar.yml`. Grupo propio `revisar-planilla`. No usa
    Wialon ni toca la rama `dia-chile`. Probado el 22-oct (botón: rearmó y
    subió; cron: "no cambió", sin commit). Cuando la planilla queda como pedía
    el aviso "Actualizar planilla", la confirmación se da por cumplida y el
    aviso desaparece. **Pendiente**: que el usuario pegue el Worker nuevo y
    agregue el Cron (después del 23-oct 08:00, pedido del usuario).
  - **Página nueva de reporte2 (publicada en main el 22-oct-2026 a pedido del
    usuario: reporte2.html sigue siendo de prueba y el correo diario enlaza a
    reporte.html; copia en la rama `reporte2-nueva`)**: "Trabajo
    por campo" con "Ver por: Campo | Máquina" y buscador (todo cerrado de
    entrada; por campo encuentra por equivalencias, ej. Siracusa → Aurora;
    por máquina, los números calzan enteros: "10" abre Barredora 10, SBS 10,
    Tractor 10 y Shacker de Suelo 10); botón y "Planilla leída a las HH:MM"
    (la hora sale también de la última corrida bien terminada de
    `planilla.yml`, API pública de GitHub); "Datos de …" y aviso sin
    conexión; tablas como tarjetas en pantallas de menos de 600 px; app para
    el celular (PWA "Flota C&H": `manifest.webmanifest`, `sw.js`, íconos
    `icono-192/512.png`, `icono-maskable-512.png`, `apple-touch-icon.png`;
    guarda la página y los últimos datos y se actualiza sola al volver la
    señal y cada 5 min). Probada publicada el 22-oct a 390 px de ancho (sin
    mover hacia el lado) y sin conexión.
  - **Pestaña "Operadores" (22-oct-2026, EN PRUEBA hasta que el usuario la
    apruebe; publicada en reporte2.html)**: `operadores.py`. Historial en
    `docs/datos/operadores.json` (nombres autorizados en el repositorio por el
    usuario el 22-10-2026): en cada lectura de la planilla se guarda el
    operador de cada máquina ese día (exacto desde el 22-oct-2026). Antes:
    "≈ aproximado" = el operador actual durante la estadía actual de la
    máquina en el campo (hacia atrás hasta que terminó un día en CYH o trabajó
    en otro campo; solo los 30 días del tablero). Por operador: hoy (máquina +
    implemento, campo, estado trabajó ayer / no trabajó ayer / en CYH / sin
    señal) y promedios por labor y temporada (días, horas, ha, ha/día, ha/hora)
    frente al promedio de todos en esa labor y temporada (▲▼ con ±5 %), más
    sus últimos 15 días. Horas del tablero (30 días); ha del historial
    (hoy en main con día UTC: hay días con ha y 0 h). Equivalencias de
    operadores: `config.json` → `equivalencias_operadores` ({nombre: [otros
    nombres]}); "no es el mismo": `operadores_distintos`. Van por el mismo
    camino que las de campos, sin cambiar el Worker: acción `equivalencia` /
    `borrar_equivalencia` con PLANILLA "operador: <otro nombre>" (o
    "operador-distinto: …") y CAMPO = nombre que queda. Aviso de nombres
    parecidos (mismo primer nombre e inicial del apellido, o difflib ≥ 0,78).
    "Sin operador en la planilla": máquina fuera de CYH que trabajó ayer sin
    operador anotado (en Máquinas en operación y en Operadores); ese trabajo
    queda en la máquina. Probado el 22-oct desde la página publicada
    (guardar y quitar "Prueba Op" = Pirincho).
  - **Recálculo de la rama `dia-chile` TERMINADO el 22-oct-2026** (último
    tramo 16 al 21-oct, sin fallas). Comparación con main hasta el 21-oct
    mostrada al usuario (script en el scratchpad, `comparar3.py`): casos de
    calibración iguales o a menos de 1 punto, salvo GS 7 (ahora recolección
    con tractor, 43,5 % en vez de 78 %); total 8.371 → 8.701 ha (+330, casi
    todo por geocercas que main no tenía calculadas); recolección con tractor
    371,8 ha (abril 259 ha; con las reglas de la recolección da menos que
    como picado, ej. Pomaire 7 3,31 → 1,03 ha); raleo 18,4 ha en 10
    cuarteles; 52 repasos (97,7 ha); 0 "Revisar labor".
  - **Respuestas del usuario (26-oct-2026), aplicadas en la rama y
    recalculando de nuevo (1-ene al 25-oct, lanzado el 26-oct)**:
    - Tractores de PODA (2, 9, 10, 11, 13 y 15): siempre Poda, nunca
      recolección. Tractores de PICADO (1, 3, 4, 7, 8, 14, 16 y 17):
      "Recolección (tractor con recogedora)" cuando trabajan en un campo
      después de que pasó un Shacker de Suelo o el Shaker Orchard Rite
      (remecido) en esa temporada (ene–may, también abril y mayo). Si solo
      pasó un Shacker SBS (cosecha con recibidor) sigue siendo Picado
      (`LABORES_SHAKER = ("Remecido de suelo",)`).
    - Remecido de suelo: los repasos son reales (Achurra 3 7-abr, N3 22–25-abr,
      N2 16, 17 y 21-abr).
    - Poda y Picado: NUNCA repaso (`LABORES_SIN_REPASO`); volver al cuartel es
      terminar lo que faltaba: no suma hectáreas ni alarma (Longaví 4 y 5 en
      junio, Flor Oriente 17-jun, Aurora 2 25-sep).
    - Recolección (recogedoras y tractor con recogedora): repaso real si antes
      hubo un repaso de remecido en ese cuartel después de completar la
      recolección (`fecha_ultimo_repaso` del remecido en el avance), o con la
      regla de siempre (≥ 3 pasadas del día por hileras ya pasadas esa
      temporada).
    **Falta el OK del usuario para pasar a main.**
  - **Datos de reporte2 en archivo aparte (26-oct-2026)**: el correo diario
    (versión anterior) reescribe `docs/datos/reporte_diario.json` cada mañana
    sin el bloque `v2`, y del 23 al 26-oct `reporte2.html` quedó vacía. Desde
    el 26-oct todo lo de la versión nueva va en `docs/datos/reporte_v2.json`
    (lo del correo + `v2`), que el correo no toca; lo leen `reporte2.html`, la
    app (`sw.js`, cachés `flota-*-v2`), Operadores, la revisión de la planilla
    y las confirmaciones (`reporte_v2.RUTA_V2`, `rearmar_pagina`). **Paso de
    la mañana**: `.github/workflows/v2.yml` + `v2_manana.py`, al terminar cada
    corrida de `correo.yml` (`workflow_run`) y de respaldo a las 08:17, 09:37
    y 11:13 de Chile: si el correo de hoy ya salió (`correo_enviado.json`) y
    reporte2 no está armado con ese día, lo arma desde el `reporte_diario.json`
    nuevo ("Máquinas que trabajaron ayer" sale de ahí, sin Wialon; Wialon solo
    para las comunas, lectura) y sube `reporte_v2.json` y `operadores.json`.
    Corre aparte del correo (no toca `correo.yml`, `diario.yml` ni
    `reporte_correo.py`); si falla, `v2_aviso.py` avisa solo a `CORREO_PRUEBA`.
    `planilla.yml`, `v2.yml` y `confirmar.yml` suben sobre lo último de main
    (si otro sube antes, se rehace). Historial de operadores: solo hubo
    lectura el 22 y el 26-oct; los días entre dos lecturas con el mismo
    operador en la máquina quedan "≈ aproximado" (23 al 25-oct recuperados).
  - **Hasta el 23-oct-2026 08:00 no tocar nada del envío diario**
    (`correo.yml`, `diario.yml`, `reporte_correo.py`, corrida de la noche,
    Worker) — pedido del usuario.
  - Prueba v2 enviada el 22-oct-2026 a `CORREO_PRUEBA` con la planilla leída
    (13 máquinas en operación, sin alerta grande).
  - **Tarea futura (opción A)**: que al confirmar se actualice solo el Drive:
    pasar la planilla a Google Sheets, una cuenta de servicio de Google con
    permiso de editor (credencial como secreto de GitHub) y una columna de
    registro de cambios.
  - Tractor 8 Kubota 108, 15-10, 0,26 ha con 0 h (revisado 22-oct): son dos
    pasadas cortas en Avoamerica 37 y 38 (3 y 0 hileras regulares). Las horas
    no aparecen porque el historial de main usa el día UTC (21:00 a 21:00 de
    Chile) y el tablero el día de Chile, y porque visitas de menos de 6 min
    (0,1 h) no suman horas en geocercas. Las ha con 0 hileras salen del avance
    de la labor recalculado (unión de todas las máquinas con el patrón del
    campo) y se le acreditan a la máquina que tocó el cuartel ese día; con el
    día de Chile (rama `dia-chile`) los días calzan.
- **Temporadas (antecedente)**: el avance de una labor no debería acumularse de una
  temporada a otra. Hoy el avance de cada geocerca + labor se acumula todo el
  año y nunca baja. Ej. EL PRINCIPIO 12 – Cosecha con recibidor: 92,4 %
  publicado = 2,11 ha del Shacker SBS 7 (12 y 13-feb) + 2,35 ha del Shacker
  SBS 10 (19-oct, confirmado en terreno junto con EP 13); lo de octubre solo
  es ~49 %. EP 13 al 19-oct: 2,37 de 2,57 ha (92,2 %, en proceso).
- **Correo de prueba enviado el 20-oct-2026** (datos del 19-oct, a
  `CORREO_PRUEBA`). Los intentos anteriores fallaban con "Connection
  unexpectedly closed" al iniciar sesión en Gmail: el usuario confirmó el
  acceso en los avisos de seguridad de la cuenta y volvió a cargar
  `CORREO_USUARIO` y `CORREO_CLAVE`. Falta que apruebe la prueba y cargue
  `CORREO_DESTINATARIOS` para activar el envío diario, y que configure
  Cloudflare.

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
