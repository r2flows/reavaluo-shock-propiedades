# Fase 6: resultados de P3 (¿el alza de contribuciones aumenta las ventas?)

Fecha: 23-11-2026. Especificaciones: `docs/analysis_plan.md` v1.0 + desviaciones DV1–DV3 (§9), registradas antes de mirar el período post.
Código: `uv run python -m src.models.estimar_p3`. Resultados: `data/staging/_reportes/resultados_p3.json`.
Unidades:
- β = cambio en la probabilidad **trimestral** de venta (pp) por 1 desviación estándar del shock teórico ($126.605 semestrales).
- La columna "por +$100k/año" convierte β a pp de probabilidad **anual** por cada +$100.000 de alza anual.
- Base: 0,73% trimestral (≈ 2,9% anual) en G_0 antes de 2022. Umbral de relevancia registrado: 0,4 pp anuales por +$100k.

## D1: triple diferencia (pago vs. grupo con rebaja de adulto mayor del 100%)
| Especificación | Estatus | β (pp trim./SD) | IC95 | p | por +$100k/año (pp anual) |
| --- | --- | --- | --- | --- | --- |
| **Registrada** | ❌ no identificada (pre-tendencias p = 0,023) | 0,012 | [−0,099; 0,122] | 0,84 | 0,02 |
| DV1: + tendencias lineales | exploratoria | 0,110 | [−0,093; 0,312] | 0,29 | 0,17 |
| DV1: pre solo 2020–2021 | exploratoria | 0,127 | [0,006; 0,247] | 0,042 | 0,20 |
| DV1: placebo y2 (transferencias sin monto) | exploratoria | −0,001 | [−0,010; 0,007] | 0,75 | 0,00 |

Estudio de eventos anual (DV3), coeficiente de `shock·paga` en pp trimestrales, referencia 2021:
| Año | Registrado | Con tendencias (ref. 2018 y 2021) |
| --- | --- | --- |
| 2018 | 0,26 (0,08) | — |
| 2019 | 0,26 (0,08) | 0,09 (0,07) |
| 2020 | 0,08 (0,07) | −0,01 (0,05) |
| 2022 | 0,13 (0,11) | 0,17 (0,13) |
| 2023 | 0,15 (0,10) | 0,25 (0,13) |
| 2024 | 0,15 (0,10) | 0,32 (0,15) |
| 2025 | 0,24 (0,11) | 0,48 (0,18) |
Tendencia `t·shock·paga`: −0,017 pp por trimestre (se 0,007).

Lectura:
- En la versión registrada, los coeficientes post (0,13–0,24) **vuelven al nivel de 2018–2019** (0,26). El patrón parece un valle en 2020–2021 (pandemia y anticipación), no un efecto del reavalúo.
- Con tendencias, el efecto post crece en el tiempo. Pero eso depende de extrapolar linealmente una tendencia negativa estimada en el pre, y es frágil.
- El placebo de transferencias sin monto da cero: no hay diferencias espurias por herencias o mortalidad.

## D2 y D3: regresión kink (fuzzy) sobre la venta en 2022–2023
| Diseño | Versión | Efecto | se robusto | p robusto | N efectivo |
| --- | --- | --- | --- | --- | --- |
| D2: tope +25% (por +100 pp de alza pagada relativa) | registrada | 0,019 | 0,107 | 0,58 | 17.665 |
| D2 | DV2 con covariables | 0,011 | 0,106 | 0,66 | 18.325 |
| D3: tope $9.415 (por +$1.000 de cuota trimestral) | registrada | 0,030 | 0,031 | 0,13 | 1.932 |
| D3 | DV2 con covariables | 0,034 | 0,038 | 0,13 | 1.838 |
Ambos son nulos e imprecisos. Las covariables no son suaves en los kinks (ver `fase6_prechequeos.md`), así que son evidencia débil.

## Conclusión frente a los criterios del §6
- **H3.1 (confirmatoria): no se puede afirmar.** La especificación registrada no está identificada, y su estimación es nula (p = 0,84).
- **Mejor caso exploratorio:** +0,17 a +0,20 pp anuales por cada +$100.000 de alza anual, es decir ~6–7% relativo. Está **por debajo del umbral registrado** (0,4 pp ≈ 15%). Solo la sensibilidad 2020–2021 es significativa (p = 0,04), y no sobreviviría una corrección por pruebas múltiples.
- Para la vivienda mediana que pasó a pagar o subió (alza de $33–61 mil al año), el efecto implícito sería de ~0,1 pp anuales. **Económicamente irrelevante.**
- **Decisión según el §6:** no se cumple la condición (a). **El producto de "vendedor forzado por contribuciones" se abandona** y se priorizan P1 y P2 (valoración y descuentos), como estaba previsto.
- Limitaciones: los barrios son inferidos (los efectos fijos de barrio × trimestre son aproximados), la gradualidad está modelada de forma aproximada y la potencia de D3 es baja.
