# Fase 6: chequeos previos (23-11-2026)

Ejecutados según `docs/analysis_plan.md` v1.0 (commit c9211bc). **No se estimó ningún efecto del período post.**
Comandos: `uv run python -m src.models.panel` y luego `uv run python -m src.models.prechequeos`.
Resultados completos: `data/staging/_reportes/prechequeos.json` y `prechequeos_d1_pre.csv`.

## Panel
- Muestra base P3: 308.698 roles habitacionales. Se descartaron 26.126 con exención especial y 70 con cambio de superficie.
- D1: G_0 = 112.346 y G_AM = 13.778 roles, × 32 trimestres (4,04 MM filas).
- El 92,5% de G_AM mantiene la rebaja del 100% en 2022.
- Tasa trimestral de venta pre: G_0 0,73%; G_AM 0,36%.

## D1 (triple diferencia): ❌ no cumple el criterio de tendencias previas
- Prueba conjunta de los 15 coeficientes pre de `shock × paga`: F = 2,00, **p = 0,023**. El criterio registrado era p > 0,10.
- Patrón: los coeficientes son positivos y decrecientes, de +0,32–0,41 pp en 2018–2019 a ≈ 0 en 2021 (referencia 2021-T4). Es una **tendencia relativa a la baja** antes del reavalúo, no un salto puntual.
- Explicación candidata, a verificar: el período pre de 2022 es el período post del **reavalúo 2018**, que también tuvo shock y gradualidad, probablemente sobre roles parecidos.
- Según el pre-registro (§8): **D1 se reporta como no identificado en su especificación registrada.**

## D2 (kink en +25% de gradualidad): primera etapa ✅, densidad ✅, covariables ❌
- Primera etapa con el pago observado: kink = −1,006 (teórico −1), F = 6.506. h = 0,28; N efectivo = 35.933.
- Densidad (rddensity): p = 0,099, sin quiebre al 5%.
- Covariables con kink significativo: log avalúo 2021 (F = 55), superficie (F = 17) y año de construcción (F = 19). Se usaron anchos de banda propios, mucho más estrechos (h ≈ 0,07).
- La variable de asignación (alza % teórica) depende de la composición terreno/construcción y del nivel del avalúo, así que las covariables no son suaves en el kink. Eso amenaza la validez del RKD.

## D3 (kink en $9.415 por cuota): primera etapa ✅, densidad ✅ (al límite), covariables ❌ parcial
- Primera etapa: kink = −1,109, F = 422; N efectivo = 1.861.
- Densidad: p = 0,054.
- Covariables: superficie con kink significativo (F = 44); log avalúo F = 6,3 (p ≈ 0,01); año de construcción sin problema (F = 1,8).
- Muestra chica: el N efectivo limita la potencia.

## Decisión pendiente (requiere registrar una desviación antes de mirar el período post)
Ver la conversación del 23-11-2026: las opciones se registran en §9 de `analysis_plan.md`.
