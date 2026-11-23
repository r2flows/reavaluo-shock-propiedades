# Fase 6: resultados de P2 (descuentos)

Fecha: 23-11-2026. Especificación: `docs/analysis_plan.md` v1.0 §4 (sin desviaciones).
Código: `uv run python -m src.models.estimar_p2`. Resultados: `data/staging/_reportes/resultados_p2.json`.

## H2.1: ¿venden con descuento los roles con huella del beneficio de adulto mayor?
| Versión | Descuento vs. su microbarrio×semestre | IC95 | p | N (AM) |
| --- | --- | --- | --- | --- |
| **Registrada** (ventas 2018–2025, rebaja en 2021 o 2022) | **−12,3%** | [−14,5%; −10,0%] | < 0,001 | 63.508 (3.172) |
| Exploratoria: ventas 2022–2025 de roles con rebaja en 2021 (vendedor ≈ beneficiario) | −11,9% | [−14,6%; −9,1%] | < 0,001 | 28.976 (1.702) |

**Chequeos exploratorios (no registrados):**
| Muestra | Descuento AM | p |
| --- | --- | --- |
| Sin ventas extremas (\|residuo\| < 0,5) | −1,7% | 0,007 |
| Sin ventas extremas (\|residuo\| < 0,3) | +0,9% | 0,08 |
- El 16,1% de las ventas AM se hacen a menos de la mitad del precio esperado (residuo < −0,7), frente al 9,6% del resto.
- Mediana del residuo: AM −5,3%; resto +0,4%.

**Lectura:**
- El descuento registrado (−12%) **lo explica sobre todo la cola** de ventas a precios muy bajos, no un descuento generalizado.
- Esa cola es compatible con **transferencias entre familiares** (padres a hijos a precio simbólico) o con ventas en apuros. Sin el tipo de escritura ni las partes no se pueden separar.
- En las ventas de rango "normal" el descuento es de ~0–2%, bajo el 4% del criterio (b).
- También puede reflejar peor estado de conservación (viviendas de dueños mayores con menos remodelación), que el catastro no observa.

## H2.2: ¿las compras con descuento ganan al revender?
| Grupo de compra | Reventas en ≤ 4 años | Residuo medio en la compra | Exceso de retorno medio vs. índice SPAR del barrio |
| --- | --- | --- | --- |
| Descuento (< p10 de su celda, residuo sin la propia venta) | 425 (10,3%) | −0,94 (≈ 39% del precio esperado) | +63% |
| Medio (p40–p60) | 1.184 (8,9%) | −0,07 | +4% |
Diferencia: **+81,6%** (IC95 70–94%), p < 0,001. Neta de costos: +78–80%.

**Lectura:** el resultado es estadísticamente significativo, pero **no es evidencia de oportunidad**.
- Una "compra" al 39% del precio esperado casi nunca es una venta de mercado. Lo más probable es una cesión de derechos, una venta parcial, una transferencia familiar o un error de monto.
- La "reventa" posterior a precio de mercado produce el exceso de retorno por pura **regresión a la media**, un sesgo que el pre-registro ya advertía.
- Para que H2.2 sea informativa hace falta excluir las transacciones que no son de mercado. Eso requiere el tipo de escritura (que el F2890 público no trae) o un filtro por rango de precio definido ex ante.

## Conclusión frente al §6
- **H2.1: se confirma estadísticamente** y nominalmente supera el 4% del criterio (b). Pero el descuento está concentrado en ventas que probablemente no son de mercado. **El criterio (a) de P3 ya falló**, así que la decisión de producto no cambia: se abandona "vendedor forzado".
- **H2.2: significativa pero no interpretable** como oportunidad (artefacto de regresión a la media y de transacciones fuera de mercado).
- **Hallazgo útil para el producto de valoración:** las transacciones de roles con dueño mayor tienen una probabilidad 1,7 veces mayor de cerrarse a menos de la mitad del valor esperado. Es una señal de riesgo y calidad de datos que debe filtrarse antes de construir comparables o índices.
