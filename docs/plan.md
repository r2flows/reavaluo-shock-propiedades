# Plan v2: la brecha avalúo–mercado como motor de oportunidades

Piloto: Gran Santiago (Ñuñoa, Providencia, Maipú; se amplía si falta poder estadístico). Ventana: precios desde 2010 (F2890) y avalúos desde 2018-1S (catastro histórico), por semestre, más una prueba fuera de muestra con el reavalúo 2027.
Antecedentes: plan original en la raíz del repo y su crítica en `docs/evaluacion_critica.md`.

## Objetivo
Medir si la brecha entre el valor de mercado y el avalúo fiscal (y su evolución) **predice retornos futuros** por barrio y por propiedad, y si el cierre de esa brecha en los reavalúos (shock de contribuciones) genera vendedores forzados. A partir de eso, construir un sistema que detecte oportunidades accionables.

## Disponibilidad de datos (revisado 22-11-2026)
Regla: cada elemento del plan usa solo datos que existen y se pueden obtener. Si un elemento depende de un dato no disponible, queda en pausa (⏸) hasta encontrar una fuente.

| Fuente | Estado | Qué trae / limitación |
| --- | --- | --- |
| **F2890 SII** (`F2890_30-10-2026.zip`, público, sin login) | ✅ **Verificado** | 9,22 MM filas, `;`, latin1. Columnas: `COMUNA;MANZANA;PREDIO;FECHA_INSCRIPCION;FECHA_ESCRITURA;MONTO_PESOS;MONTO_UF`. **Trae precio**: 4,43 MM filas en pesos y 3,90 MM en UF. Monto 0 en ~18% (2010) y ~4% (2025). Escrituras ~335–470 mil por año entre 2010 y 2025; 2026 parcial. Hay fechas erróneas (años >2026 y 2099) que se descartan. **No trae tipo de escritura ni partes.** Comunas piloto: NUNOA 307.592, PROVIDENCIA 277.135, MAIPU 154.763 filas |
| Detalle catastral y rol de cobro (SII) | 🔐 Requiere RUT + clave. Vigente por comuna; histórico **nacional por semestre desde 2018-1S** (verificado en el portal) | Por rol: avalúo total, **avalúo exento**, **contribución semestral (con aseo)**, destino, superficie de terreno, roles de bien común (copropiedad) y, **solo en la estructura vigente**, rol padre (linaje). ⚠️ El histórico 2022-1S trae **15 campos** en el archivo de roles (sin ubicación ni rol padre) y 10 en el de líneas (sin pisos): el linaje histórico hay que reconstruirlo cruzando semestres. Por línea de construcción: material, calidad (1–5), año, m², destino, condición especial y pisos. **No trae el avalúo separado en terreno y construcción**, y no trae datos del dueño |
| Estructura del detalle catastral (PDF SII) | ✅ En `docs/estructura_detalle_catastral.pdf` | 4 archivos: `BRTMPCATASN_*` (roles no agrícolas, 19 campos), `BRTMPCATASNL_*` (líneas de construcción, 11 campos) y sus equivalentes agrícolas. Separador `\|`, sin encabezado. El catastro usa el código de comuna del SII (ej. 15105) y el F2890 usa el nombre (`NUNOA`): mapear con la tabla de comunas del PDF |
| Cartografía digital SII (mapas) | ✅ Público (visor) | Ubicación de manzanas y AHV; falta ver si permite descarga masiva |
| UF diaria (Banco Central / CMF) | ✅ Público | Normalización a UF |
| Permisos de edificación (INE), Censo 2024 (INE), delincuencia (CEAD), trazados de Metro, PRC | ✅ Públicos | Variables y filtros |
| Tablas de valores, monto exento y tasas (resoluciones del SII) | ✅ Públicas | Contribución teórica |
| Tipo de escritura (compraventa / herencia / remate) | ❌ No está en el F2890 público | Proxy: monto 0 ≈ transferencia sin precio (herencia, aporte, etc.). El riesgo competitivo explícito y el pipeline de sucesiones quedan ⏸ |
| Avisos de portales, remates consolidados, arriendos | ❌ No hay fuente abierta masiva | ⏸: requieren un proveedor o un acuerdo con términos de uso compatibles |
| Datainmobiliaria.cl | Opcional | Ya no es necesaria para P1/P2, porque el F2890 trae precio |

Consecuencias:
- **P1 y P2 son factibles con datos públicos.**
- **P3** depende de que el detalle catastral histórico cubra 2018–2023.
- Los elementos que necesitan tipo de escritura, avisos o arriendos se hacen solo si aparece una fuente.

## Preguntas
- **P1 (barrio):** ¿la brecha de una AHV o manzana, y su variación, predicen el retorno de precio a 2–3 años mejor que un índice con momentum?
- **P2 (propiedad):** ¿las ventas con precio/avalúo bajo respecto de su manzana corresponden a vendedores en apuros (herencia, adulto mayor, remate)? ¿Se revenden con ganancia?
- **P3 (shock):** ¿la brecha de hoy predice el alza de contribuciones de 2027? Y, con 2022 (más la réplica 2018), ¿el shock eleva la probabilidad de venta de los dueños con patrimonio inmobiliario y bajos ingresos?

## Definiciones
| Variable | Definición |
| --- | --- |
| `ratio_ia` | precio_UF / avalúo_UF de la transacción (ratio de los estudios de tasación masiva de la IAAO) |
| `brecha_barrio_t` | Mediana de `ratio_ia` por AHV/manzana y semestre, con shrinkage bayesiano por n |
| `retorno_barrio_{t→t+h}` | Variación del índice de ventas repetidas (fallback hedónico), h = 4 y 6 semestres |
| `residuo_prop` | log(ratio_ia) − log(brecha_barrio): descuento relativo de cada venta |
| `shock` | Δ contribución teórica = Δ terreno (AHV, de mercado) + Δ construcción (tablas nacionales, mecánico) + gradualidad, si existe |
| `benef_am` | Contribución observada < teórica: proxy de beneficiario adulto mayor, sin RUT |

## Fases
Ninguna fase avanza sin cumplir su criterio de aceptación.

0. **Reconocimiento.** Perfil del F2890 y del detalle catastral → `docs/data_profile.md`. Responder:
   - ¿hay monto de enajenación?
   - ¿qué tipos de escritura hay (compraventa / herencia / adjudicación por remate)?
   - ¿qué profundidad histórica hay?
   - ¿el avalúo se puede separar en terreno y construcción?
   - ¿el exento funciona como deducción o como notch? ¿hay gradualidad del alza? ¿cuál es el tope de avalúo del beneficio AM?
   - **Criterio:** go/no-go por pregunta (P1, P2, P3), con números.
1. **Servilleta económica (Fase 0.5).** Con agregados del SII: dispersión de `ratio_ia` entre barrios, ventas por AHV y semestre, y universo con un shock relevante versus el ingreso plausible.
   - **Criterio:** n mínimo por celda y un efecto mínimo detectable bajo el efecto económicamente relevante; si no se cumple, se suman comunas.
2. **Ingesta y normalización.** Parsers con esquema explícito, tests con fixtures y Parquet por semestre.
   - **Criterio:** el conteo de roles por comuna concilia con los agregados del SII dentro de ±1%.
3. **Linaje de roles y transacciones.** Subdivisiones y fusiones, agrupación por escritura (unidad + bodega + estacionamiento), filtro por tipo de escritura, exclusión de la primera venta de una inmobiliaria y réplica de los descartes del SII.
   - **Criterio:** >95% de las compraventas hacen match con el catálogo.
4. **Avalúo y contribución teóricos.** Fórmula por semestre (exento y tasas vigentes; restar la tarifa de aseo de la contribución observada), gradualidad e inferencia de `benef_am`. **Separación terreno/construcción por reconstrucción:** avalúo de construcción = Σ líneas (m² × valor de la tabla por material y calidad × depreciación por año) con las tablas públicas del SII; terreno = total − construcción. Linaje con el **rol padre**.
   - **Criterio:** error mediano <1% contra la contribución observada en roles sin rebaja.
5. **Índices y brecha.** Índice por AHV, `brecha_barrio_t` y `residuo_prop`. Descriptivos: regresividad del avalúo por nivel de valor y evolución de la brecha entre reavalúos.
   - **Criterio:** índice con IC aceptable en la mayoría de las AHV piloto (umbral definido en la Fase 0.5).
6. **Estimación causal (P3).** Pre-registro en `docs/analysis_plan.md` antes de mirar resultados.
   - Modelo de duración en tiempo discreto. Evento: venta con monto > 0. Riesgos competitivos (compraventa / herencia / remate) ⏸ hasta tener tipo de escritura; mientras tanto, monto 0 como evento alternativo.
   - Diseño principal: notch del beneficio AM y la IV con el shock mecánico dentro de la manzana (FE manzana×trimestre).
   - Secundarios: RKD en el exento y réplica 2018.
   - Errores agrupados por AHV.
   - Supuestos: densidad, balance y tendencias previas nulas.
7. **ML predictivo (P1/P2), no condicionado a P3.**
   - Objetivo: `retorno_barrio_{t→t+h}`; clasificador secundario: "venta con descuento seguida de reventa con ganancia".
   - Variables (calculadas solo con información disponible en t): brecha, Δbrecha, años desde el reavalúo, mezcla terreno/construcción, regresividad, permisos INE, infraestructura anunciada, constructibilidad sin usar, tasa de herencias, % `benef_am`, censo, delincuencia y riesgo natural.
   - Modelos: línea base de momentum → LightGBM → SHAP. Intervalos con conformal prediction.
   - Validación: hacia adelante en el tiempo (entrenar ≤2021, probar 2022–2025) + bloques espaciales.
   - **Criterio:** superar la línea base de momentum fuera de muestra, neto de costos de transacción del 2–4%.
8. **Predictor del reavalúo 2027.** Metodología del SII calibrada en 2022 → avalúo proyectado por rol y ranking de exposición al shock.
9. **Captura de oportunidades** (§ siguiente).
9-bis. **Producto para dueños: revisión de avalúo y contribuciones 2027** (`src/producto/`, servicio privado `/reclamo`). Replica la apelación de avalúo de EE.UU. (Ownwell, AppealDesk) adaptada a las causales técnicas del art. 149 del Código Tributario. Ver `docs/benchmark_internacional.md`.
   - Auditor por rol: terreno/m² aislado sobre el de la manzana y avalúo/m² aislado sobre el de unidades iguales del edificio (fuertes); calidad y aumento de superficie (datos a verificar).
   - Expediente: estimación 2027 con gradualidad, líneas de construcción valoradas, comparables depurados, equidad por quintil y pasos para reclamar.
   - **Criterio:** backtest 2022 con precisión de las señales fuertes ≥ 3 veces la tasa base de bajas del SII sin cambio físico (**cumplido:** 5,4× y 4,2×); error mediano del estimador < 1% (**cumplido:** 0,025%); revisión legal de 10 expedientes (**pendiente**).

## Captura de oportunidades
| Bloque | Elemento | Fase |
| --- | --- | --- |
| Flujo en tiempo real | ⏸ Avisos de portales (precio de lista, días publicados, rebajas) vía un proveedor o con acuerdo, revisando los términos de uso | 9 |
| Flujo en tiempo real | ⏸ Remates (judiciales, bancarios, TGR) con valoración → puja máxima recomendada | 9 |
| Valoración para ofertar | Conformal prediction: oportunidad solo si el límite inferior > precio + costos | 7 |
| Valoración para ofertar | ⏸ Rentabilidad total = yield de arriendo + plusvalía esperada | 7 |
| Variables adelantadas | Planes reguladores en tramitación + constructibilidad sin usar → ensamble de lotes | 7 |
| Variables adelantadas | Infraestructura anunciada vs. inaugurada (Metro L7/L8/L9, corredores, parques) | 7 |
| Variables adelantadas | Pipeline de sucesiones: curva de reventa post herencia (⏸ sin tipo de escritura; versión aproximada con transferencias de monto 0) | 7 |
| Variables adelantadas | Imágenes satelitales abiertas: ampliaciones no registradas (subavalúo → shock futuro), deterioro | 10 |
| Filtros de riesgo | Delincuencia (CEAD), inundación o remoción en masa, campamentos, ruido, edificios con salidas en cascada | 7 |
| Ejecución | Backtest como estrategia: costos, capacidad, plazo de venta, régimen de tasas/UF; TIR neta vs. índice comunal | 7 |
| Ejecución | Registro de negocios evaluados, ofertados y cerrados para reentrenar | 10 |
| Ejecución | Alertas semanales con ficha del negocio (valor, intervalo, comparables, riesgos) | 10 |

## Productos posibles (no se construyen en esta fase)
- Estimador de contribuciones 2027 con asistente de reclamo de avalúo (para dueños).
- Ranking de barrios y alertas de negocios (para inversionistas).
- Radar de ensamble de lotes (B2B para inmobiliarias).
- Riesgo de morosidad territorial (municipios y bancos).
- Liquidez para adultos mayores: nuda propiedad o sale-leaseback (alternativa ética a comprar con descuento).

## Esquema de datos
| Tabla | Grano | Columnas clave |
| --- | --- | --- |
| dim_rol | Rol | rol_id, comuna, AHV, destino, superficies, año, clase y calidad, copropiedad |
| fct_avaluo_semestre | Rol × semestre | aval_total, aval_terreno, aval_construccion, aval_exento, contrib_observada, contrib_teorica |
| fct_transferencia | Rol × escritura | escritura_id, fecha, tipo, monto_uf |
| fct_ratio_transaccion | Escritura × rol | precio_uf, avaluo_uf, ratio_ia, tipo |
| map_rol_linaje | Cambio de rol | rol_origen, rol_destino, fecha, tipo |
| mart_indice_barrio | AHV × semestre | indice, brecha, n |
| mart_features_barrio | AHV × semestre | variables ML (información disponible en t) |
| mart_panel | Rol × trimestre | shock, shock_mecanico, benef_am, evento (compraventa/herencia/remate), controles |

## Escalamiento multipaís (solo diseño)
Esquema común: `ratio_ia`, ciclo de reavalúo y nivel legal de tasación. Candidatos con datos abiertos: Francia (DVF + valeur locative), EE.UU. (Cook County, NYC), Colombia (catastro multipropósito). El avalúo significa cosas distintas en cada país, así que las variables deben medirse relativas al propio ciclo.

## Riesgos y preguntas abiertas
- [x] ¿El F2890 trae monto? **Sí** (verificado 22-11-2026). No trae tipo de escritura: hay que buscar otra fuente o validar el proxy de monto 0.
- [ ] Las ventas de copropiedad (depto + bodega + estacionamiento) traen el monto en un solo rol y 0 en los otros: agrupar por fecha de escritura + manzana.
- [x] Profundidad histórica del catastro: desde 2018-1S. **Consecuencia:** el reavalúo 2018 no tiene semestre previo en el catastro, así que la réplica 2018 queda limitada (solo hay post). Para P1/P2 la brecha se puede calcular desde 2018; antes solo hay precios del F2890.
- [x] Separación terreno/construcción implementada con las tablas oficiales (Res. 143/2021 y 28/2018). Valida: terreno/m² constante dentro de la manzana en el 99% de las manzanas.
- [ ] **El shock mecánico dentro de la manzana es débil** (75–95% del alza viene del terreno). Revisar el diseño de la Fase 6: priorizar el salto del factor comunal de Maipú (0,8→0,9) en el límite comunal, la alza gradual y el tope de $9.415.
- [x] El exento habitacional es una deducción (kink), verificado con la guía del SII y los datos.
- [x] Hay alza gradual en el reavalúo 2022: +25% el 1S-2022 (base ×1,051 IPC), tope de $9.415 por cuota para quien pasa a afecto y +10% semestral hasta el 2S-2025. Implementada en `src/features/contribucion.py`.
- [ ] [verificar] Monto del tope de avalúo y requisitos del beneficio adulto mayor por semestre.
- [ ] [verificar] Vigencia de la Ley 21.719: el análisis a nivel rol está permitido; los leads de dueños requieren un análisis legal.
- [ ] Exención para mayores de 65 en tramitación: riesgo para P3, pero también experimento de signo opuesto.
- [ ] El reavalúo 2027 podría postergarse otra vez, lo que retrasaría la prueba fuera de muestra.
- [ ] Riesgo reputacional de productos dirigidos a vendedores vulnerables.
- [x] **Fase 6 (23-11-2026):** P3 nulo → se abandona el producto "vendedor forzado". P1 confirma reversión de la brecha (−1,2 pp de retorno a 3 años por +10% de brecha; p perm. 0,0015), pero no se replica en 2021. Ver `docs/fase6_resultados_p1_y_resumen.md`.
- [x] **R1 (réplica en 33 comunas nuevas del Gran Santiago): no confirma H1.1** (β −0,03; p perm. 0,21). La brecha no es un predictor útil de plusvalía. Se reorienta el producto: estimador y reclamo de contribuciones, comparables depurados y predictor del reavalúo 2027.
- [x] **Fase 7:** predictor del reavalúo 2027 por escenarios (S0 +1%, S2 +13%, S1 +26% real). Backtest 2022: error por rol de 8,9% con el nivel correcto; entre comunas el SII traspasa ~45% de la brecha. Ver `docs/fase7_reavaluo2027.md`.
- [x] **Fase 9-bis (28-11-2026):** auditor de avalúo y expediente para dueños. 20.527 roles con señal en el Gran Santiago; las señales fuertes anticiparon bajas del SII 4–5 veces más que la tasa base en el backtest 2022 (precisión absoluta 1,4–1,7%). Las señales débiles no predicen y no se muestran. Desviación registrada: el criterio del estimador "≥ 85% sin rebaja" era tautológico y se reemplaza por el error mediano. Ver `docs/benchmark_internacional.md`.
- [x] **Ficha de terreno (28-11-2026):** parser de la serie agrícola del catastro (`src/etl/catastro_agricola.py`; vigente del Gran Santiago y 2022-1S nacional), clases de suelo por rol y búsqueda de roles por dirección (`src/producto/terreno.py`, ruta privada `/terreno`). Muestra la ubicación urbana/rural según el SII.
- [ ] [verificar] Significado de los códigos de ubicación del catastro (U, R y E; E probable "extensión urbana") y de las clases de suelo 4R y 20–29 (solo Magallanes), que no figuran en el PDF del SII. Confirmar con Christian si su "categoría 1 al 9" es la clase de suelo del SII.
- [ ] Descargar el catastro vigente de las comunas periurbanas (Colina, Lampa, Buin, Pirque, Calera de Tango, Talagante, etc.): hoy la ficha usa la serie agrícola 2022-1S y no tiene la serie no agrícola (parcelas de agrado) de esas comunas.
- [ ] [verificar] Causales y plazos de reclamo del reavalúo 2027 tras la Ley 21.713, con un abogado tributario, antes de ofrecer el expediente a dueños.
- [ ] Fase 5: el índice por barrio es ruidoso (retorno a 3 años ±13%). La primera mirada no muestra que la brecha prediga retornos (corr. −0,03). En la Fase 6, evitar correlaciones mecánicas: las variables y el objetivo no pueden compartir ventas ni años extremos.
- [ ] Barrios inferidos por numeración de manzanas: validar la contigüidad con la cartografía del SII.
