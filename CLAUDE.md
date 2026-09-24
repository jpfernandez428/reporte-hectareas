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
- Calibración de terreno (septiembre 2026): Aurora 3 y Aurora 7 terminados;
  Aurora 1, 2 y 6 casi terminados. Cualquier cambio de fórmula debe mantener
  eso.
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
- Con estas reglas: Solfrut 8 – Picado 13,5 %, Solfrut 10 – Picado 9,1 %;
  Aurora sigue calibrado (3: 98,2 %, 7: 98,8 %, 1: 91,8 %, 2: 86,5 %,
  6: 91,1 %).

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
  dos juntas). Cuando entre todas cubren el 95 % de la geocerca, esa es la
  pasada 1. Lo que siguen haciendo sin una pausa de 2 h o más, o por zona
  que esa pasada no tenía, sigue siendo la pasada 1. Si después vuelven a
  pasar por la misma geocerca, empieza la pasada 2 desde cero, y así
  sucesivamente.
- El resumen muestra cuántas pasadas completas lleva cada cuartel y el % de
  la pasada en curso. **No** usar la mediana de días por hilera.
- Las hectáreas de barrido del historial suman todas las pasadas (pueden
  superar el área del cuartel).

## Mapas

- No guardar KML por máquina en el repositorio (hacía crecer mucho el
  historial de git). La web los genera desde `docs/datos/geometria/`.
- El KML generado debe ser XML válido (escapar `&`, `<`, `>` y comillas en
  nombres).

## Pendientes

- Detectar geocercas nuevas en Wialon y calcularlas con los últimos 30 días.
- Avisar cuando una máquina trabaje fuera de cualquier geocerca (salvo el
  patio C&H Maquinaria), distinguiendo trabajo de traslados.
