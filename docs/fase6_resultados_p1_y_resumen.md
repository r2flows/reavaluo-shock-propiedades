# Fase 6: resultados de P1 y resumen de las pruebas confirmatorias

Fecha: 23-11-2026. Código: `uv run python -m src.models.estimar_p1`. Resultados: `data/staging/_reportes/resultados_p1.json`.

## P1 (H1.1): ¿la brecha precio/avalúo del barrio predice su retorno futuro?
Regresión barrio × año: `Y4 = SPAR(t+4) − SPAR(t+1)` sobre la brecha relativa del barrio en t (vs. su comuna) y el momentum `SPAR(t) − SPAR(t−3)`, con efectos fijos comuna × año.
| Muestra | β brecha_rel | se (barrio) | p (cluster) | **p (permutación, principal)** | Efecto de +10% de brecha relativa | N |
| --- | --- | --- | --- | --- | --- | --- |
| **Confirmatoria t = 2018–2020** | **−0,123** | 0,054 | 0,024 | **0,0015** | **−1,2 pp** de retorno a 3 años | 294 |
| Exploratoria t = 2021 (objetivo ya mirado) | 0,003 | 0,079 | 0,97 | 0,97 | 0,0 pp | 98 |

**Lectura:**
- En 2018–2020, los barrios cuyo precio estaba **alto respecto de su avalúo** (vs. el resto de la comuna) **rindieron menos** en los 3 años siguientes. Es **reversión a la media** de la brecha, no momentum. El momentum no aporta (β = 0,04).
- **Magnitud modesta:** +10% de brecha relativa equivale a −1,2 pp de retorno en 3 años. La dispersión entre barrios del retorno a 3 años es de ~10 pp, con un 43% de señal.
- **No se replica para t = 2021** (2022 → 2025). Ese período incluye el reavalúo y el cambio de ciclo de tasas: la relación puede depender del régimen o ser frágil.
- Con 98 barrios y solo 3 cortes, la evidencia es **sugerente, no concluyente**. H1.2 (el modelo predictivo fuera de muestra) queda pendiente hasta tener objetivos posteriores a 2025.

## Resumen confirmatorio con corrección de Holm (familia de 4, α = 0,05)
| Hipótesis | p | p ajustado (Holm) | Resultado |
| --- | --- | --- | --- |
| H2.1: descuento AM | < 0,0001 | < 0,001 | ✅ significativa (efecto −12%, concentrado en ventas que probablemente no son de mercado) |
| H2.2: exceso de retorno de compras con descuento | < 0,0001 | < 0,001 | ✅ significativa pero **no interpretable** (regresión a la media y transacciones fuera de mercado) |
| H1.1: brecha → retorno futuro | 0,0015 | 0,003 | ✅ significativa (reversión: −1,2 pp por +10% de brecha) |
| H3.1: alza pagada → venta (D1) | 0,84 | 0,84 | ❌ nula, y la especificación registrada no está identificada |

## Decisiones (criterios del §6 de `analysis_plan.md`)
1. **Producto "vendedor forzado por contribuciones": se abandona.** El criterio (a) falla: no hay efecto relevante sobre las ventas.
2. **Producto de valoración / brecha (P1): sigue**, con reservas. Hay una señal de reversión de la brecha en el corte confirmatorio, de tamaño modesto y que no se replica en 2021. Requiere:
   - validar con más años (catastros 2018–2021 semestrales, más comunas) y con la prueba fuera de muestra posterior a 2025;
   - mejorar los barrios (cartografía);
   - **filtrar transacciones fuera de mercado** antes de usar precios como comparables (hallazgo de P2: las ventas a < 50% del valor esperado son el 10–16% del total).
3. **P2 como insumo de calidad de datos:** la huella del beneficio de adulto mayor predice transacciones a precio muy bajo. Sirve para depurar comparables, no como fuente de oportunidades de compra.
