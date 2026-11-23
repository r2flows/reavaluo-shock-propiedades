# Perfil de datos (Fase 0, en curso)

Actualizado: 22-11-2026. Archivos en `data/raw/` (inmutables, fuera de git).

## F2890: transferencias (`data/raw/f2890/F2890_30-10-2026.zip`)
- 1 txt, 416 MB, `;`, latin1, con encabezado: `COMUNA;MANZANA;PREDIO;FECHA_INSCRIPCION;FECHA_ESCRITURA;MONTO_PESOS;MONTO_UF`.
- 9.219.581 filas. Monto en pesos: 4.431.865; en UF: 3.899.521; el resto, sin monto.
- Monto 0: ~18% en 2010 → ~4% en 2025. Hay fechas de escritura imposibles (años >2026, 2099) que se descartan.
- Escrituras por año: entre 335 mil y 470 mil (2010–2025).
- Comuna por **nombre** sin tildes (`NUNOA`, `PROVIDENCIA`, `MAIPU`): 307.592 / 277.135 / 154.763 filas.
- No trae tipo de escritura, partes ni destino.

## Detalle catastral histórico 2022-1S (`data/raw/catastro/BRORGA2441_NAC_2022_1.zip`)
- 182 MB zip → 1,8 GB. 4 archivos: A, AL (agrícola), N, NL (no agrícola). `|`, sin encabezado, campos de ancho fijo con ceros a la izquierda.
- `N`: 7.621.720 roles nacionales, **15 campos** (la estructura del PDF trae 19: el histórico no trae ubicación ni rol padre).
- `NL`: 10 campos (sin número de pisos).
- Comuna por **código SII** (15105 Ñuñoa, 15103 Providencia, 14109 Maipú).

| Comuna | Roles | Habitacionales | Habitacionales con contribución 0 |
| --- | --- | --- | --- |
| Ñuñoa (15105) | 214.054 | 105.705 | 33.979 (32%) |
| Providencia (15103) | 206.583 | 72.018 | 17.265 (24%) |
| Maipú (14109) | 168.701 | 159.098 | 118.224 (74%) |

- Avalúo exento modal de los habitacionales: **$47.360.490** (≈ monto exento del 1S-2022; por confirmar con la resolución del SII).
- La alta proporción de roles con contribución 0 en Maipú lo convierte en el mejor laboratorio para estudiar quién cruza de exento a afecto.

## Detalle catastral histórico 2021-2S (`data/raw/catastro/BRORGA2441_NAC_2021_2.zip`)
- 180 MB zip; misma estructura que 2022-1S (15 campos en el archivo `N`). 7.529.096 roles.
- Avalúo exento modal de los habitacionales: **$36.845.717** → $47.360.490 en 2022-1S (**+28,5%**).

## Shock del reavalúo 2022 (roles habitacionales pareados 2021-2S → 2022-1S)
| Comuna | Pareados | Exento → paga | Paga → exento | Pagan en ambos | De esos, contribución sube >50% | De esos, contribución **baja** | Avalúo promedio 2022/2021 | Roles nuevos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Providencia | 71.709 | 41 | 4.255 | 54.425 | 73 | 26.959 (50%) | 1,14 | 309 |
| Ñuñoa | 104.338 | 1.818 | 4.441 | 68.760 | 312 | 40.175 (58%) | 1,24 | 1.367 |
| Maipú | 158.847 | **12.106** | 818 | 28.764 | **3.248** | 1.967 | **1,45** | 251 |

Lectura:
- El monto exento subió más que el avalúo en las comunas de mayor valor, así que en **Providencia y Ñuñoa la contribución bajó para la mitad de los que pagan**.
- **Maipú concentra el shock positivo:** su avalúo subió 45% en promedio y 12 mil viviendas pasaron a pagar.
- Hay shocks de ambos signos dentro del piloto, lo que sirve para identificar el efecto (las propiedades donde bajó funcionan como contraste simétrico).
- Contribución observada incluye aseo y rebajas: falta comparar con la contribución teórica.

## Pendiente
- Catastro vigente de las 3 comunas (trae rol padre).
- Confirmar si el campo 8 es el monto exento o min(avalúo, monto exento).
- Tasa de match de roles F2890 ↔ catastro.

---

# Estado de las Fases 1 y 2 (23-11-2026)

Comandos (desde la raíz, con `UV_PROJECT_ENVIRONMENT=.venv`):
```
uv run python -m src.etl.uf 1990 2026
uv run python -m src.etl.f2890
uv run python -m src.etl.catastro 2021_2 2022_1
uv run python -m src.etl.escrituras
uv run pytest            # 13 tests
```
Reportes de filas por paso: `data/staging/_reportes/*.json`.

## Fase 1: ingesta
| Paso | Entrada | Salida | Descartes |
| --- | --- | --- | --- |
| UF (SII) | 8.379 días | 8.379 | — (cubre 2004-01-01 → 2026-12-09; antes de 2004 el HTML del SII cambia y no se parsea) |
| F2890 | 9.219.581 | 9.210.545 | fecha de escritura inválida 7.519; fuera de rango 906 (ej. 2099 por 1999); rol inválido 611; duplicados exactos 0 |
| Catastro roles 2021-2S | 7.529.096 | 584.730 (piloto) | resto: otras comunas |
| Catastro roles 2022-1S | 7.621.720 | 589.338 (piloto) | resto: otras comunas |
| Catastro líneas 2021-2S / 2022-1S | 9,96 MM / 10,04 MM | 710.655 / 715.411 | 0 líneas sin ficha de rol |

- Unidad de origen del monto F2890: pesos 3,98 MM; UF 3,37 MM; sin monto (0 o vacío) 1,86 MM.
- 674 mil transferencias en pesos anteriores a 2004 quedan sin UF del día (fuera de la ventana de análisis).
- **Criterio ±1% contra estadísticas del SII: pendiente.** La página de estadísticas no agrícolas por comuna del SII da 404; hay que conseguir la cifra oficial de roles por comuna para 2021-2S/2022-1S.

## Fase 2: cruce, escrituras y linaje
- 738.950 transferencias de las 3 comunas → **422.534 escrituras**.
  - Por tipo de grupo: simple 194.102; con anexos (depto + bodega/estacionamiento) 125.276; sin habitacional 75.566; múltiples habitacionales 27.590.
  - 21.645 anexos no se pueden asignar (grupos con varios departamentos el mismo día).
- Monto de la escritura: único 237.893; sin monto 125.207; sumado 57.613; repetido 1.821.
- Primera venta de obra nueva (≤ 2 años desde la construcción): 144.424 escrituras, que se excluyen de los análisis de vendedores.
- Mediana UF de ventas habitacionales con precio (sin obra nueva): Maipú 1.020 (2012) → 1.835 (2025); Ñuñoa 2.333 → 3.949.
- **Tasa de match de ventas con precio contra el catálogo del catastro:**
  - 2010–2020: **97–99,9%** en las 3 comunas → **cumple el criterio >95%**.
  - 2021 en adelante cae (Ñuñoa: 48% en 2022, 27% en 2024), por los roles de edificios nuevos creados después de 2022-1S. Se corrige agregando un catastro posterior (vigente 2026).
  - Detalle por comuna y año: `data/staging/_reportes/fase2_tasa_match_por_anio.csv`.
- Linaje entre 2021-2S y 2022-1S: 4.982 altas y 374 bajas de roles; 1.813 de ellos en manzanas con altas y bajas a la vez (candidatas a subdivisión o fusión).

## Actualización: catastro vigente 2S-2026 y conciliación oficial

**Catastro vigente** (`data/raw/catastro_vigente/BRTMPCATAS_2026_2_{14109,15103,15105}.zip`):
- Estructura completa: 19 campos en N (con ubicación y rol padre) y 11 en NL (con pisos), más un separador al final de la línea.
- 654.965 roles (Maipú 172.594; Providencia 219.101; Ñuñoa 263.270) y 787.032 líneas de construcción.
- Solo 334 roles traen rol padre.

**Fase 2 rehecha con 3 semestres (2021-2S, 2022-1S, 2026-2S):**
- Tasa de match de ventas con precio en 2020–2023: **99,86%** (Ñuñoa 99,85%; Maipú 99,79%; Providencia 99,95%). Por año: >96% en 2010–2025 en todas las comunas, salvo Providencia 2011–2013 (96,5–97%). **Cumple >95%.**
- 2026 baja (Providencia 79%), por roles creados después de la foto del catastro.
- 427.954 escrituras, de las cuales 170.363 son primera venta de obra nueva. 27.604 anexos sin asignar.
- Linaje: 71.420 altas y 1.185 bajas de roles (sobre todo edificios nuevos de Ñuñoa).

**Conciliación con cifras oficiales del SII** (`src/etl/ref/sii_predios_oficiales.csv`; PDF en `data/raw/sii_estadisticas/`):

| Comuna | Semestre | Roles nuestros | Oficial reavalúo 2022 | Dif. | Habitacionales afectos nuestros | Oficial (antes/después) | Dif. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Maipú | 2021-2S | 168.459 | 168.025 | +0,26% | 29.598 | 29.570 | +0,09% |
| Maipú | 2022-1S | 168.701 | 168.025 | +0,40% | 40.874 | 42.092 | **−2,89%** |
| Providencia | 2021-2S | 205.731 | 202.917 | **+1,39%** | 58.729 | 58.655 | +0,13% |
| Providencia | 2022-1S | 206.583 | 202.917 | **+1,81%** | 54.753 | 54.672 | +0,15% |
| Ñuñoa | 2021-2S | 210.540 | 208.636 | +0,91% | 73.250 | 73.161 | +0,12% |
| Ñuñoa | 2022-1S | 214.054 | 208.636 | **+2,60%** | 71.726 | 71.080 | +0,91% |

Vigente 2S-2026 vs. estadística oficial 2S-2025 (no agrícolas, un año de desfase): Maipú +0,47%; Ñuñoa +2,48%; Providencia +2,19%.

Lectura:
- **Los afectos habitacionales cuadran dentro de ±1%** en 5 de 6 casos; es la población clave para el shock.
- El total de roles cuadra en Maipú y en Ñuñoa 2021-2S. En Providencia y en Ñuñoa 2022-1S el catastro trae 1,4–2,6% más roles. Lo más probable es que la base del reavalúo tenga una fecha de corte anterior y no incluya los roles nuevos de edificios en construcción; falta confirmarlo.
- Maipú 2022-1S trae 2,9% menos afectos habitacionales que el oficial. Puede ser por la definición de afecto ("total o parcialmente") versus nuestra regla (contribución > 0), o por la gradualidad. Revisar en la Fase 4.
- **Estado del criterio ±1%: cumplido para afectos habitacionales, parcial para el total de roles.**

---

# Fase: avalúo y contribución teóricos (punto 4 de docs/plan.md), 23-11-2026

Comando: `uv run python -m src.features.contribucion` → `data/staging/contribucion_{sem}.parquet` y `data/marts/shock_2022.parquet`.
Parámetros: `src/etl/ref/parametros_impuesto.csv`. Normativa descargada en `data/raw/sii_normativa/`.

## Parámetros por semestre
| Semestre | Exento hab. | Cambio de tasa | Tasa 1 | Tasa 2 / no hab. | Fuente |
| --- | --- | --- | --- | --- | --- |
| 2021-2S | $36.845.717 | $131.591.831 | 0,933% | 1,088% | Res. SII 28/2018 reajustada por IPC; DS 458/2018. Las tasas se verificaron con los datos |
| 2022-1S | $47.360.490 | $169.144.585 | 0,893% | 1,042% | Res. SII 11/2022; DS 437/2022 |
| 2026-2S | $61.711.570 | $220.398.435 | 0,893% | 1,042% | Exento modal del catastro vigente; cambio de tasa reajustado en la misma proporción |
| Todos | | | | Sobretasa fiscal 0,025% sobre el tramo 2 (hab.) o sobre todo el afecto (no hab.) | Ley 17.235 |

**Verificado:**
- El exento habitacional **se descuenta** del avalúo (es un kink, no un notch).
- **Hay alza gradual** en el reavalúo 2022: +25% el 1S-2022 sobre la cuota base 2S-2021 reajustada por IPC (×1,051), con un tope de $9.415 por cuota para quienes pasan de exentos a afectos, y +10% semestral hasta el 2S-2025.

## Aseo municipal (incluido en la contribución del catastro; estimado como moda del residuo)
| Comuna | 2021-2S | 2022-1S | 2026-2S |
| --- | --- | --- | --- |
| Ñuñoa | $34.200 | $24.100 | $41.900 |
| Providencia | $43.900 | $45.500 | $60.900 |
| Maipú | $18.500 | $18.200 | $27.900 |

## Validación (viviendas afectas con exención general; observado sin aseo vs. teórico)
| Semestre | n | Error mediano | Dentro de ±1% | Paga >1% menos (rebajas) |
| --- | --- | --- | --- | --- |
| 2021-2S | 151.507 | 0,05% | 74,8% | 25,2% |
| 2022-1S sin gradualidad | 165.656 | 0,06% | 64,4% | 35,1% |
| **2022-1S con gradualidad** | 165.656 | **0,04%** | **87,2%** | 12,2% |
| 2026-2S | 188.528 | 0,02% | 73,6% | 26,4% |

**Criterio "error mediano < 1%": cumplido en todos los semestres.** Los roles que pagan menos que lo teórico son la señal esperada de rebajas (beneficio de adulto mayor u otras).
- En 2021-2S y 2026-2S ese 25% puede incluir además alzas graduales remanentes de reavalúos anteriores (2018 y 2022). Hay que modelarlas antes de usar esa diferencia como proxy de adulto mayor.

## Shock del reavalúo 2022 (viviendas presentes en ambos semestres)
| Comuna | Viviendas | Avalúo ×(mediana) | Pasan a afecto | Pasan a exento | Alza >50% | Contribución baja | Con alza gradual | Posible rebaja 2021 | Alza anual mediana (las que suben) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Maipú | 158.847 | 1,46 | 12.437 | 964 | 21.417 | 3.610 | 28.996 | 12.904 | $60.509 |
| Providencia | 71.709 | 1,14 | 0 | 4.661 | 204 | 37.220 | 825 | 10.672 | $32.919 |
| Ñuñoa | 104.338 | 1,18 | 1.787 | 4.832 | 8.714 | 35.853 | 15.792 | 14.601 | $47.525 |

Lectura económica:
- El alza anual mediana es de $33–61 mil, chica frente al valor de una vivienda. Confirma la crítica 1.3: el efecto de "vendedor forzado" solo es plausible en hogares con poco ingreso o en la cola de alzas grandes.
- El tratamiento queda bien definido y tiene variación en los dos sentidos.

## Separación del avalúo en terreno y construcción (`src/features/avaluo_construccion.py`)
Fórmula del SII: `construcción = Σ VUC(clase, calidad) · m² · CE · DP · FC · factor IPC`; terreno = total − construcción.
- 2022-1S y 2026-2S usan la Res. SII 143/2021 (Anexos 3 y 5, $ del 2S-2021); el factor IPC es 1,051 para 2022-1S y 1,369 para 2026-2S.
- 2021-2S usa la Res. SII 28/2018 (Anexos 03 y 05, $ del 1-7-2017); el factor IPC es 1,114, con la UF como aproximación.
- Factor comunal: Ñuñoa y Providencia 1,00 en ambos reavalúos; **Maipú 0,80 en 2018 → 0,90 en 2022** (un +12,5% mecánico en toda su construcción).
- Tablas de valores unitarios: `src/etl/ref/vuc_2018.csv` y `vuc_2022.csv`.

**Validación:** el SII valora el terreno por área homogénea, así que en casas el terreno/m² debería ser constante dentro de la manzana.
| Semestre | Manzanas (≥ 5 casas) | Desviación mediana del terreno/m² dentro de la manzana | Manzanas con desviación < 10% | Viviendas con terreno negativo |
| --- | --- | --- | --- | --- |
| 2021-2S | 5.664 | 0,02% | 98,8% | 0,06% |
| 2022-1S | 5.667 | 0,03% | 99,2% | 2,7% |
| 2026-2S | 5.673 | 0,03% | 99,2% | 1,5% |

→ La fórmula reproduce la valoración del SII casi exactamente. El terreno negativo en 2022-1S y 2026-2S se concentra en casos puntuales; hay condiciones especiales sin factor publicado (SC, PC, TM), que se tratan como 1.

**Composición del alza del avalúo 2021-2S → 2022-1S (viviendas sin cambio de superficie, en $ del 1S-2022):**
| Comuna | Tipo | Viviendas | Alza total (MM$) | Construcción, mecánica (MM$) | Terreno (MM$) | Alza mediana construcción | Alza mediana terreno |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Maipú | casas | 134.910 | 1.561 | 241 | 1.321 | +3,9% | +34,1% |
| Maipú | deptos | 23.907 | 231 | 70 | 161 | +8,4% | +27,0% |
| Providencia | casas | 6.555 | 171 | 10 | 162 | +0,9% | +13,4% |
| Providencia | deptos | 65.130 | 383 | 103 | 281 | +2,2% | +5,9% |
| Ñuñoa | casas | 26.241 | 545 | 11 | 534 | −1,0% | +29,6% |
| Ñuñoa | deptos | 78.081 | 595 | 121 | 474 | +2,0% | +9,0% |

Hallazgo importante para la estrategia causal:
- **El 75–95% del alza del avalúo viene del terreno**, que sigue los precios del barrio y es endógeno.
- La parte mecánica (construcción) es chica. Además varía poco **dentro de una misma manzana**: su desviación estándar mediana es 0,7 pp, frente a 3,4 pp en total.
- → El instrumento "shock mecánico dentro de la manzana" de `docs/plan.md` sería **débil**. Las fuentes de variación exógena más prometedoras son:
  1. El **salto del factor comunal de Maipú (0,8 → 0,9)**, una discontinuidad en el límite comunal con comunas vecinas que no cambiaron.
  2. La **alza gradual**: roles con el mismo shock teórico que pagan distinto según su cuota base.
  3. El **cruce del monto exento** con el tope de $9.415 por cuota.

## Huella del beneficio de adulto mayor (`rebaja_obs` en `contribucion_*.parquet`)
Razón pagado sin aseo / teórico, en viviendas afectas con exención general:
| Semestre | Sin rebaja (99–101%) | Rebaja 100% (paga 0) | Rebaja 50% | Otra |
| --- | --- | --- | --- | --- |
| 2021-2S | 113.292 | 13.825 | 5.337 | 19.053 |
| 2022-1S (con gradualidad) | 144.495 | 13.610 | 1.769 | 5.782 |
| 2026-2S | 138.800 | 18.360 | 8.834 | 22.534 |
- Los grupos 100% y 50% calzan con los dos niveles del beneficio de adulto mayor. "Otra" son diferencias de 1–10%, sobre todo $3–8 mil por semestre: alzas graduales remanentes, aseo distinto o redondeo.
- En 2022-1S el 50% cae porque la rebaja se aplica sobre la cuota con gradualidad, que modelamos de forma aproximada. Para el proxy conviene usar **2021-2S o 2026-2S**.
- La consistencia de las rebajas de 100% y 50% entre 2021-2S y 2022-1S es del 74%.

## Mart `data/marts/shock_2022.parquet` (`src/features/shock.py`)
584.356 roles presentes en ambos semestres. Incluye:
- `delta_contrib_teo` y `delta_contrib_pagada_teo` (con gradualidad), `shock_pct_teo`;
- `pasa_a_afecto` y `pasa_a_exento`;
- `delta_construccion_mecanico`, `delta_terreno` y `share_alza_mecanica`;
- `rebaja_21`, `rebaja_22`, `copropiedad` y `cambio_superficie`.

---

# Fase 5: índices y brecha (23-11-2026)

Comandos, en orden:
```
uv run python -m src.features.barrios      # data/staging/map_barrio.parquet
uv run python -m src.features.ventas       # data/marts/fct_venta.parquet
uv run python -m src.features.indices      # índices, brecha y regresividad
```

## Barrios sin coordenadas (`src/features/barrios.py`)
- Tramos de manzanas consecutivas (el SII numera por sectores) que se cortan cuando el valor del suelo/m² salta más de 15%; los tramos con pocas ventas se fusionan.
- **Dos escalas:**
  - **Microbarrio:** 299 unidades (Maipú 145, Providencia 74, Ñuñoa 80), con ≥ 300 ventas en 2010–2026 y una dispersión del valor de suelo interna de 0,2%. Sirve para la brecha y las variables.
  - **Barrio:** 98 unidades (Maipú 40, Providencia 25, Ñuñoa 33), con ≥ 1.800 ventas y dispersión del suelo interna de 3,9%. Sirve para índices y retornos.
- **Limitación:** la contigüidad es una inferencia a partir de la numeración. Falta validarla con cartografía del SII.

## Ventas (`data/marts/fct_venta.parquet`)
- 264.544 escrituras habitacionales con precio. 96.293 son obra nueva y 2.974 son outliers (<200 UF o ratio fuera de [0,3; 15]).
- `ratio_ia` = precio / avalúo a la fecha de la escritura, disponible desde 2018: 109.975 ventas.
- Ratio precio/avalúo mediano (segunda mano). **El reavalúo 2022 cierra la brecha de golpe:**

| Año | Maipú | Providencia | Ñuñoa |
| --- | --- | --- | --- |
| 2018 | 1,91 | 2,12 | 1,92 |
| 2021 | **2,39** | 2,27 | 2,15 |
| 2022 | **1,62** | 1,96 | 1,84 |
| 2025 | 1,60 | 1,98 | 1,79 |

## Regresividad del avalúo (estándar IAAO; avalúo/precio; `_reportes/regresividad.csv`)
| Comuna | Avalúo/precio mediano 2021 → 2022 | COD 2021 → 2025 | PRD 2021 → 2025 |
| --- | --- | --- | --- |
| Maipú | 0,42 → 0,62 | 53 → 41 | 1,22 → 1,15 |
| Providencia | 0,44 → 0,51 | 40 → 42 | 1,16 → 1,14 |
| Ñuñoa | 0,47 → 0,54 | 40 → 38 | 1,15 → 1,10 |

- La IAAO recomienda COD < 15 y PRD entre 0,98 y 1,03. **El avalúo del SII es muy disperso y regresivo:** las viviendas baratas se tasan relativamente más cerca de su precio, así que pagan proporcionalmente más contribuciones.
- El reavalúo reduce la regresividad, pero queda lejos del estándar.
- Parte del COD puede venir de ruido en los montos del F2890 (ventas con anexos o montos globales). Hay que acotarlo en la Fase 6.

## Índices (`src/features/indices.py`)
- **Ventas repetidas (anual, comunal):** 38.982 pares. Plusvalía nominal en UF 2010 → 2025: Maipú +76%, Providencia +89%, Ñuñoa +82%.
- Por barrio, las ventas repetidas quedan muy imprecisas: 353 pares por barrio en la mediana e IC95 del nivel 2024 de ±12,6%.
- **Índice principal por barrio: SPAR** (precio / avalúo fijo de referencia 2S-2026, mediana por barrio y año, encogida hacia la comuna). Usa todas las ventas de segunda mano: 78 por barrio y año en la mediana.
  - IC95 del nivel: **±8,3%** (mediana); del retorno a 3 años 2021 → 2024: ±12,7%. Solo el 30% de los barrios tiene el IC95 del retorno bajo ±10%.
  - Concordancia comunal con ventas repetidas en 2012 → 2025: Providencia 69% vs. 65%, Ñuñoa 70% vs. 64%, **Maipú 75% vs. 61%**. SPAR sobrestima en Maipú, posiblemente por composición (envejecimiento de viviendas fijas en el avalúo 2026).
- **Criterio de la fase ("índice estable en ≥ X% de los barrios"): parcial.** Los niveles son razonables (±8%), pero los retornos a 3 años por barrio siguen ruidosos (±13%).

## Primera mirada a P1 (exploratoria, no pre-registrada)
- Dispersión entre barrios del retorno 2022 → 2025 dentro de cada comuna: el **43% es señal** y el resto ruido de medición.
- Correlación del retorno 2022 → 2025 con la brecha relativa del barrio en **2021**: **−0,03**, sin señal.
- ⚠️ Las correlaciones con el momentum 2019 → 2022 (−0,51) y con la brecha 2022 (−0,58) son **espurias**: comparten los precios de 2022 con el retorno, así que el ruido de medición produce una correlación negativa mecánica.
- **Regla para la Fase 6:** las variables y el objetivo no pueden compartir ventas ni años extremos. Hay que dejar al menos un año de separación o dividir la muestra de ventas.
