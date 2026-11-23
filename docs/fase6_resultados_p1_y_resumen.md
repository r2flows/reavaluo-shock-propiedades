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

---

## R1: réplica de H1.1 fuera de muestra en el Gran Santiago (registrada en §9 antes de procesar los datos)
Pipeline completo sobre 36 códigos de comuna: 3,0–3,4 MM roles por semestre, 1,5 MM ventas habitacionales con precio y ~600 barrios. El cruce F2890–catastro con precio en 2020–2023 es de 99,9%, y ninguna comuna queda bajo 95%. Los barrios piloto no cambian (el algoritmo es por comuna) y el β piloto se reproduce exactamente.

| Muestra | β brecha_rel | p (cluster) | p (permutación) | +10% de brecha → retorno 3 años | N barrio×año |
| --- | --- | --- | --- | --- | --- |
| Piloto t = 2018–2020 (confirmatoria original) | −0,123 | 0,024 | < 0,002 | −1,2 pp | 294 |
| **R1: 33 comunas nuevas, t = 2018–2020 (confirmatoria)** | **−0,031** | 0,34 | **0,21** | **−0,3 pp** | 1.507 |
| R1 exploratoria t = 2021, comunas nuevas | +0,015 | 0,76 | 0,78 | +0,1 pp | 505 |
| Exploratorio: Gran Santiago completo, t = 2018–2020 | −0,046 | 0,11 | 0,029 | −0,4 pp | 1.801 |

**Conclusión: la réplica no confirma H1.1.**
- El signo se mantiene (reversión), pero el efecto en las comunas nuevas es **4 veces menor** y no significativo.
- Lo más probable es que el piloto **sobrestimara** el efecto: es la "maldición del ganador" de una muestra chica, con 98 barrios.
- La mejor estimación conjunta (−0,4 pp de retorno a 3 años por +10% de brecha relativa) es **económicamente irrelevante** frente a costos de transacción de 2–4% y a una dispersión de retornos entre barrios de ~10 pp.

## Implicancias para el producto
- **La brecha precio/avalúo del barrio, por sí sola, no es un predictor útil de plusvalía.** El producto de "valoración por brecha" pierde su fundamento principal.
- Lo que sí queda validado y tiene valor como infraestructura de datos:
  1. **Pipeline reproducible** del Gran Santiago (F2890 + catastro + UF), con un cruce del 99,9%.
  2. **Contribución teórica** con gradualidad: calza al peso en el 86% de las viviendas.
  3. **Separación terreno/construcción** que reproduce la valoración del SII (error de 0,1% dentro de la manzana).
  4. **Huella del beneficio de adulto mayor** y detección de transacciones fuera de mercado (P2).
  5. **Índices SPAR por barrio** (±10% en nivel) y medición de la **regresividad del avalúo** (COD 35–53; PRD 1,1–1,2).
- Las posibles líneas de valor pasan de "predecir oportunidades de compra" a:
  - **(a)** un estimador de contribuciones y un asistente de reclamo de avalúo para dueños, apoyado en la regresividad documentada;
  - **(b)** un servicio de comparables depurados (filtrando transacciones fuera de mercado);
  - **(c)** el predictor del reavalúo 2027 (Fase 7), con un método ya validado contra el SII.

## Memoria
El pipeline del Gran Santiago se corre con `scripts/correr.sh [--mem 5G] <módulo>`, que pone un tope de memoria por cgroup y limita los hilos de Polars. Las escrituras se procesan por comuna (pico de 0,9 GB). El paso más pesado es la separación terreno/construcción (pico de 4,4 GB).
