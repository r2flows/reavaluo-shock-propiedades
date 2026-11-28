# Benchmark internacional y producto para dueños (Fase 9-bis)

Fecha: 28-11-2026. Es un producto: no cambia `docs/analysis_plan.md` ni las pruebas confirmatorias.

## 1. Qué está consolidado afuera y qué tenemos en Chile
| Modelo consolidado | Qué vende | Lo que ya tenemos | Brecha |
|---|---|---|---|
| **Apelación de avalúo** (Ownwell en EE.UU.: contingencia de 25–35% del ahorro del primer año; AppealDesk: evidencia por US$49 fijos) | Detecta sobreavalúo y arma el expediente | Contribución 2027 por rol, separación terreno/construcción, regresividad (COD/PRD), comparables | **Hecho:** auditor por rol y expediente |
| **AVM con rango** (DVF + Meilleurs Agents en Francia; PriceHubble para los notarios de París) | Valor con intervalo y comparables cercanos | F2890 con precio, SPAR por barrio, filtro de ventas fuera de mercado (P2) | Modelo por rol con intervalo conformal; validación contra tasaciones reales |
| **Títulos instantáneos** (Doma; First American Clear2Go) | Semáforo "limpio / revisar" en minutos | `preinforme-titulos`, cadena del F2890, lector de certificados | Reglas de riesgo y semáforo |
| **Ratio studies públicos** (estándar IAAO; COD ≤ 15 en vivienda) | Transparencia de la equidad del avalúo | COD 35–53 y PRD 1,1–1,2 por comuna | Reporte público periódico en el atlas (solo agregados) |

En Chile ya hay estimadores de valor de mercado (TocToc, HousePricing, Calcular.cl), pero **no encontramos un servicio de revisión de avalúo fiscal por rol**.

## 2. Diferencia clave: en Chile se reclama por errores técnicos, no por valor de mercado
- En EE.UU., la apelación típica argumenta que el avalúo supera el valor de mercado o que no es parejo con el de casas parecidas.
- En Chile, el reclamo del avalúo no agrícola se funda en las causales del **art. 149 del Código Tributario**:
  1. superficie errónea;
  2. aplicación errónea de las tablas de clasificación de las construcciones o de los coeficientes;
  3. errores de transcripción, copia o cálculo.
- La **Ley 21.713** derogó el procedimiento especial de reclamo de avalúos: hoy rige el procedimiento general. Las vías son una revisión administrativa ante el SII o un reclamo ante el TTA, y los plazos se cuentan desde el término de la exhibición de los roles. **[verificar con un abogado tributario las causales y los plazos para 2027]**.

Por eso el producto busca **errores técnicos por rol**. Es justo lo que permite la reconstrucción del avalúo línea a línea con las tablas del SII (Fase 4). El valor de mercado (comparables) se muestra solo como antecedente.

## 3. Lo construido (`src/producto/`)
| Módulo | Qué hace |
|---|---|
| `auditoria_rol.py` | Señales por rol en 2026-2S (ver §4). Salida: `data/marts/auditoria_roles_2026_2.parquet` y el reporte `auditoria_roles.json` |
| `comparables.py` | Ventas parecidas del microbarrio (o del barrio si quedan menos de 5) de los últimos 3 años. Excluye la obra nueva, los outliers y las ventas fuera de mercado (precio ÷ avalúo < ½ de la mediana local). Cada descarte se cuenta por motivo |
| `estimador2027.py` | Contribución 2027 en los escenarios S0, S2 y S1, con la cuota del 1S-2027 y alza gradual (misma regla que la Fase 4, con un test de equivalencia) |
| `expediente.py` | Expediente HTML por rol: resumen, 2027, datos registrados línea a línea con su valor según las tablas, indicios, comparables, equidad por quintil de precio, cómo reclamar y lo que no cubre |
| `src/titulos/app.py` | Ruta privada `/reclamo` con login, en el mismo servicio de Railway |

Uso local: `.venv/bin/python -m src.producto.expediente --comuna "Ñuñoa" <manzana-predio>` genera `privado/expedientes/<rol>.html`.

## 4. Señales y backtest 2022 (criterio de aceptación)
**Método del backtest:**
- Se calculan las señales con el catastro 2022-1S.
- El resultado es que el SII haya bajado el avalúo en 2026-2S más de 2% por debajo del reajuste común (×1,303), **sin cambio físico**: mismas líneas de construcción y misma superficie de terreno.
- Universo: 1,99 MM viviendas del Gran Santiago sin cambio físico. Tasa base de baja: **0,32%**.

| Señal (2022-1S) | Roles | Bajados después | Precisión | × tasa base | p (binomial) |
|---|---|---|---|---|---|
| **Avalúo/m² sobre el de unidades iguales del edificio, fuerte (≥ 5%)** | 1.324 | 23 | 1,74% | **5,4** | 2·10⁻¹⁰ |
| **Terreno/m² sobre el de la manzana, fuerte (≥ 20%)** | 875 | 12 | 1,37% | **4,2** | 4·10⁻⁵ |
| Avalúo/m² sobre el edificio, revisar (2–5%) | 686 | 3 | 0,44% | 1,3 | 0,38 |
| Calidad mejor que la del edificio | 894 | 3 | 0,34% | 1,0 | 0,55 |
| Terreno/m² sobre la manzana, revisar (10–20%) | 1.241 | 1 | 0,08% | 0,2 | 0,98 |

**Decisión:**
- Las dos señales **fuertes cumplen** el criterio (≥ 3 veces la tasa base). Son las únicas que el expediente destaca como "indicio fuerte" y para las que estima un ahorro.
- Las señales "revisar" de terreno y edificio **no lo cumplen** y no se muestran.
- La de calidad y la de aumento de superficie se muestran solo como "datos a verificar". Se basan en lo que el dueño sabe de su propiedad, no en una predicción.

**Lectura:** la precisión absoluta es baja (1,4–1,7%) porque casi nadie reclama. El backtest mide si el SII corrigió sin que necesariamente hubiera un reclamo, así que es una cota inferior de la tasa de error real.

**Filtro de áreas homogéneas:** sin él, casas de una misma manzana con otra área homogénea (por ejemplo, la otra calle) aparecían como "fuertes". Ahora la señal exige un valor **aislado**: no puede haber 2 o más pares con el mismo terreno/m² (±3%) o el mismo avalúo/m² (±1%).

## 5. Universo 2026-2S (Gran Santiago)
- Entrada: 3.376.363 roles.
- Descartes:
  - 1.191.878 no auditables (no habitacionales, con avalúo 0, sin construcción o con una línea sin tabla);
  - 2.163.958 sin señal.
- **Salida: 20.527 roles con señal** (20.674 filas rol × señal):

| Señal | Nivel | Filas |
|---|---|---|
| Avalúo/m² sobre el edificio | fuerte | 1.511 |
| Avalúo/m² sobre el edificio | revisar | 745 |
| Terreno/m² sobre la manzana | fuerte | 907 |
| Terreno/m² sobre la manzana | revisar | 1.261 |
| Calidad mejor que la del edificio | — | 1.147 |
| Aumento de superficie desde 2022 | — | 15.103 |

- Ahorro anual mediano si se corrige el exceso, con las tasas actuales: **$214.803** en las señales fuertes de terreno y **$96.686** en las de edificio.

## 6. Estimador: precisión de la base
- La contribución teórica 2026-2S tiene un error mediano de 0,025% frente a la observada (sin aseo). El 72% de las viviendas afectas con exención general queda dentro de ±1% (`contribucion_2026_2.json`).
- Casi todo el 28% restante paga menos que la fórmula por beneficios: 79 mil con rebaja de 100%, 32 mil con rebaja de 50% y 105 mil con otras rebajas.
- **Desviación del criterio del plan:** el plan pedía ≥ 85% "en viviendas sin rebaja". Con la definición de rebaja de la Fase 4, ese porcentaje es 100% por construcción, así que el criterio no discrimina. En su reemplazo se usa el error mediano (< 1%: se cumple). Además, el expediente advierte cuando el cobro actual es la mitad o menos que el de la fórmula (huella de un beneficio), porque la estimación 2027 no incluye beneficios.

## 7. Pendiente
- **Revisión legal:** que un abogado tributario revise 10 expedientes, las causales y los plazos (Ley 21.713) antes de ofrecerlo a dueños.
- **Modelo de cobro:** estimador gratis y tarifa fija por expediente. La contingencia solo con un abogado aliado.
- **Prorrateo de bienes comunes y coeficientes de terreno** (forma, tamaño, esquina): no se auditan.
- **Recalibrar** el estimador cuando el SII publique los valores de 2027, y volver a correr el auditor con el catastro 2027.
- **Siguientes segmentos:** AVM con intervalo conformal (B), semáforo de títulos (C) y un reporte público de equidad en el atlas (D).

## Fuentes
- Ownwell y AppealDesk (tarifas, según reseñas de terceros): https://www.appealdesk.com/blog/ownwell-pricing-review · https://www.moneycrashers.com/ownwell-review/
- Doma, decisión instantánea de títulos: https://doma.com/tech/technology/ · First American Clear2Go: https://www.firstam.com/agentadvantage/Clear2Go.html
- AVM de los notarios de París con PriceHubble: https://www.pricehubble.com/fr/blog/estimation-immobiliere-paris-notaires-services-avm · DVF: https://www.economie.gouv.fr/particuliers/prix-immobilier-estimation-demande-valeur-fonciere
- Estándar IAAO de ratio studies (COD, PRD): https://www.audits2.ga.gov/wp-content/uploads/2024/08/Standard_on_Ratio_Studies.pdf
- SII, vías de revisión del avalúo: https://www.sii.cl/destacados/reavaluo/2021/vias_revision.html · Fallo del TTA (art. 149 N°3, prorrateo de bienes comunes): https://www.diarioconstitucional.cl/2026/01/30/tribunal-tributario-acoge-reclamo-por-reavaluo-fiscal-y-ordena-recalcular-avaluo-de-departamento-en-pinto/
- Estimadores chilenos: https://www.theclinic.cl/2025/07/01/housepricing-startup-chilena-valora-tu-propiedad/ · https://www.calcular.cl/tasacion
