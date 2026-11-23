# Fase 7: predictor del reavalúo no agrícola 2027 (Gran Santiago)

Fecha: 23-11-2026. Código: `scripts/correr.sh --mem 5G src.models.reavaluo2027`.
Salidas:
- `data/marts/reavaluo2027_roles.parquet`: 3,38 MM roles, con avalúo y contribución 2027 en 3 escenarios.
- `data/staging/_reportes/reavaluo2027.json` y `reavaluo2027_por_comuna.csv`.

Todos los montos están en $ del 2S-2026 (sin el reajuste IPC del 1S-2027). Es una fase **predictiva**: no forma parte de las pruebas confirmatorias del pre-registro.

## 1. Qué se aprendió del reavalúo 2022 (backtest)
| Prueba | Resultado |
| --- | --- |
| Cambio real del terreno por microbarrio vs. brecha, crecimiento y nivel previos (dejando una comuna fuera) | R² = 0,12; correlación 0,34; RMSE 0,251 vs. 0,267 (solo promedio) y 0,475 (sin cambio) |
| Error por rol del avalúo 2022 predicho, con el nivel aprendido de otras comunas | **8,9% mediano** (55% de roles con error < 10%); con construcción exacta, 7,7%; solo IPC, 21,5% |
| ¿El SII cerró la brecha precio/avalúo? | Sí, y **más allá de 2018**: 2,17 (2019–21) → 1,72 (2022–23); en 2018 era 1,92. Alza real mediana +28% |
| ¿Sigue el SII al mercado entre microbarrios? | Casi nada (correlación 0,06–0,10). Usa sus propios estudios por área homogénea |
| ¿Y entre comunas? | Parcialmente: **traspasa ~45%** de las diferencias de brecha (correlación 0,32–0,48). Ninguna comuna bajó: mínimo +8% real |
| Exento y cambio de tasa | Suben lo mismo que el avalúo habitacional nacional: +22,3% vs. +22,1% |
| Tasas | Bajan para respetar el tope de +10% de recaudación (2022: ×0,957) |

**Implicancia:** lo que domina el error es el **nivel** del alza, que es una decisión del SII y no se puede aprender de un solo reavalúo. La distribución fina dentro de cada comuna no es predecible con datos de mercado. Por eso 2027 se proyecta con **escenarios de nivel** y una distribución calibrada **solo entre comunas**.

## 2. Situación del mercado 2022 → 2026
- La brecha precio/avalúo del Gran Santiago está **plana**: 1,73 (2022), 1,70 (2023), 1,69 (2024), 1,70 (2025) y 1,78 (2026, parcial).
- Los precios en UF no le han ganado a los avalúos reajustados por IPC. Movimiento mediano por comuna: +0,6%; p10 −8%; p90 +10%.

## 3. Escenarios 2027 (viviendas, Gran Santiago; 2,18 MM roles)
Nivel por comuna = max(0, mercado comunal con traspaso de 45% + f × cierre de brecha de 2022 [0,229 en log]).
| | S0: mantiene la razón de 2022 (f = 0) | S2: cierre medio (f = 0,5) | S1: repite el cierre de 2022 (f = 1) |
| --- | --- | --- | --- |
| Alza real del avalúo habitacional | +1,1% | +12,7% | +26,4% |
| Exento habitacional ($ 2S-2026) | $62,4 MM | $69,5 MM | $78,0 MM |
| Tasas t1 / t2 (tope de +10%) | 0,893% / 1,042% | 0,872% / 1,018% | 0,778% / 0,908% |
| Viviendas que pasan a pagar | 7.041 | 9.961 | 10.016 |
| Viviendas que dejan de pagar | 7.759 | 16.561 | 16.561 |
| Viviendas con alza gradual en el 1S | 15.737 | 40.406 | 40.371 |
| Alza anual mediana (entre las que suben) | $12.466 | $43.381 | $43.348 |
| Viviendas con alza > $200.000/año | 1.575 | 70.806 | 71.367 |
| Recaudación habitacional | +1,1% | +10,6% | +10,7% |

Comunas con más viviendas que pasan a pagar (S1): La Florida, San Bernardo, San Joaquín, La Cisterna, Quinta Normal, Santiago Oeste y Macul (900–1.500 cada una).

**Lectura:**
- Como el exento sube con el promedio, **pocas viviendas cambian de estado** en cualquier escenario (7–10 mil de 2,18 MM). Las que cambian están en comunas cuyo mercado subió más que el promedio.
- El impacto se concentra en **quienes ya pagan**: en S1 y S2, ~71 mil viviendas tendrían alzas de más de $200 mil al año, amortiguadas por la gradualidad.
- El tope de +10% hace que la recaudación habitacional suba lo mismo en S1 y en S2: en S1 la baja de tasas compensa el mayor avalúo.

## 4. Limitaciones
- **El nivel es un supuesto de política** (escenarios), no una predicción. Se actualiza en cuanto el SII publique las tablas de valores (planos de precios por área homogénea, previos a la vigencia).
- Dentro de cada comuna, el alza es uniforme. En el backtest, la diferenciación fina no superó al promedio de forma útil.
- Las tasas se calculan con el tope de +10% aplicado al Gran Santiago, cuando la ley lo aplica a nivel nacional.
- No incluye cambios de tablas de construcción ni de factores comunales; en 2022 fueron de segundo orden frente al terreno.
- No modela pérdidas de beneficios (adulto mayor, DFL2) ni cambios legales en discusión, como la exención para mayores de 65.

## 5. Uso como producto
- **Estimador "¿cuánto pagaré en 2027?" por rol**, con rango S0–S1 y la cuota del primer semestre con gradualidad.
- **Alertas para dueños** con alza > $200 mil al año en S1 (~71 mil viviendas), combinadas con la regresividad del avalúo (Fase 5) como insumo para reclamos.
- **Recalibración inmediata** cuando el SII publique los valores de 2027: reemplazar el nivel del escenario por el valor publicado de cada área homogénea.
