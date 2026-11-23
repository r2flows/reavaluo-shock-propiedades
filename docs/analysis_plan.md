# Plan de análisis pre-registrado

**Versión:** 1.0, 23-11-2026. **Estado:** registrado antes de estimar cualquier efecto sobre ventas o retornos.
Todo cambio posterior se anota en la sección "Registro de desviaciones", con fecha y motivo, y los resultados que dependan de él se reportan como **exploratorios**.

Insumos (generados por el pipeline de `docs/data_profile.md`):
- `data/marts/shock_2022.parquet`: tratamiento por rol.
- `data/marts/fct_venta.parquet`: ventas, precios, ratio precio/avalúo y residuo.
- `data/marts/indice_spar_barrio.parquet`, `indice_comuna.parquet` y `brecha_barrio.parquet`.
- `data/staging/contribucion_*.parquet` y `avaluo_componentes_*.parquet`.

---

## 0. Qué se miró antes de este registro (transparencia)

Se revisaron solo descriptivos del tratamiento y de los datos, **nunca el resultado de ventas cruzado con el tratamiento**:
- Distribución del shock 2022 por comuna (pasan a afecto, alzas, bajas, gradualidad, rebajas).
- Composición del alza del avalúo (terreno vs. construcción) y su variación dentro de cada manzana.
- Ratio precio/avalúo mediano por comuna y año, y métricas IAAO.
- **Excepción, para P1:** se calcularon tres correlaciones entre barrios con el retorno 2022 → 2025 (sección "Primera mirada a P1" de `data_profile.md`). La correlación válida con la brecha relativa de 2021 dio −0,03. Por eso **P1 se registra como confirmatoria solo para ventanas que no incluyan 2022 → 2025 como objetivo**, y esa ventana se reporta aparte como exploratoria.
- Probabilidad base de venta anual (2,6%) y efectos mínimos detectables (sección 5), calculados sin separar por tratamiento.

---

## 1. Preguntas e hipótesis

| Id | Pregunta | Hipótesis (dirección) | Tipo |
| --- | --- | --- | --- |
| **P3** | ¿El aumento de contribuciones que **se paga** por el reavalúo 2022 aumenta la probabilidad de venta? | H3.1: sí, más venta cuando sube el pago (+). H3.2: el efecto es mayor en viviendas con alzas grandes respecto de su cuota previa (+). | **Confirmatoria (principal)** |
| **P2** | ¿Las ventas de dueños con señales de restricción de liquidez se cierran con descuento? | H2.1: las ventas de roles con rebaja de adulto mayor (100% o 50%) tienen `residuo_prop` menor que las de su microbarrio y semestre (−). H2.2: las ventas con descuento (`residuo_prop` en el decil inferior de su microbarrio) tienen un retorno en exceso positivo en la reventa (+). | Confirmatoria |
| **P1** | ¿La brecha precio/avalúo del barrio predice su retorno futuro mejor que el momentum? | H1.1: la brecha relativa (barrio − comuna) en t predice el retorno t+1 → t+4 (signo no pre-especificado; prueba bilateral). H1.2: un modelo con brecha supera a la línea base de momentum fuera de muestra. | Confirmatoria con baja potencia (≈ 98 barrios); ventana 2022 → 2025 exploratoria |

---

## 2. Definiciones

### 2.1 Unidad, muestra y período (P3)
- **Unidad:** rol habitacional (`destino` H en 2021-2S y 2022-1S) **sin cambio de superficie** entre semestres. Hay 334.824 roles en las 3 comunas piloto.
- **Exclusiones:**
  - roles con exención especial (avalúo exento distinto del general: DFL2, etc.);
  - roles creados después de 2021-2S;
  - escrituras de obra nueva (`primera_venta_obra_nueva`);
  - outliers de precio.
- **Panel:** rol × trimestre, desde 2018-T1 hasta 2025-T4. Período pre: 2018-T1 → 2021-T4. Período post: 2022-T1 → 2025-T4.
  - 2026 queda fuera: año parcial y fin de la gradualidad.
  - Los trimestres pre se usan para tendencias previas. Las tablas del reavalúo se publicaron antes de entrar en vigencia, así que se espera anticipación en 2021-T3/T4.

### 2.2 Resultados
- **Y1 (principal):** el rol es el rol principal de una escritura de compraventa con monto > 0 en el trimestre (1/0). Tras la primera venta post, el rol sale del panel de riesgo (modelo de duración en tiempo discreto). En la versión lineal se mantiene y se agrega un control de venta reciente.
- **Y2 (secundario):** transferencia **sin monto** (monto 0 o vacío) en el trimestre: proxy de herencia, aporte o adjudicación. No se espera efecto; funciona como contraste.
- **Y3 (P2):** `residuo_prop` = log(precio/avalúo) − log(brecha del microbarrio en el semestre).
- **Y4 (P1):** retorno log del índice SPAR del barrio entre t+1 y t+4. Las ventas del año t no entran al objetivo.

### 2.3 Tratamientos (P3)
- **T_pago:** alza **pagada** teórica de la contribución neta semestral en 2022-1S, con gradualidad (`delta_contrib_pagada_teo`), en miles de $ del 1S-2022. Es el tratamiento principal.
- **T_teo:** alza teórica sin gradualidad (`delta_contrib_teo`).
- **Grupo de rebaja (G_AM):** `rebaja_21 == "100%"`, es decir, roles que en 2021-2S pagaban 0 teniendo contribución teórica positiva (huella del beneficio de adulto mayor del 100%).
  - Reciben el mismo shock de avalúo pero **no pagan**, así que `T_pago` efectivo es ≈ 0.
  - Se asume que el beneficio se mantiene en 2022. Se verifica: en 2022-1S debe ser `rebaja_22 == "100%"`.
- **Grupo sin rebaja (G_0):** `rebaja_21 == "ninguna"`.
- Los roles con rebaja del 50% se analizan solo en heterogeneidad.

### 2.4 Controles y efectos fijos
- **Efectos fijos de rol.**
- **Barrio × trimestre:** absorbe la plusvalía y la tendencia de mercado de cada barrio. Es la principal defensa frente a que el shock de terreno sea endógeno.
- **Grupo (G_AM / G_0) × trimestre:** absorbe diferencias de propensión a vender por edad del dueño.
- **Covariables pre-tratamiento**, interactuadas con post: avalúo 2021 (deciles), superficie construida, año de construcción, copropiedad y clase/calidad principal.

---

## 3. Diseños de identificación (P3)

### D1 (principal): triple diferencia con el grupo de rebaja como placebo del canal de pago
```
Y_it = α_i + γ_{b(i),t} + δ_{g(i),t} + β · Post_t · Shock_i · Paga_i + θ · Post_t · Shock_i + X_i'·Post_t·λ + ε_it
```
- `Shock_i` = `T_teo` estandarizado (mismo shock de avalúo para ambos grupos).
- `Paga_i` = 1 si el rol está en G_0 y 0 si está en G_AM.
- **β es el parámetro de interés:** el efecto del pago, neto del efecto del alza de avalúo (riqueza o plusvalía), que θ captura en ambos grupos.
- **Supuesto clave:** sin el pago, el efecto del shock de avalúo sobre la venta sería el mismo en G_AM y G_0, condicional en los efectos fijos.
- **Prueba del supuesto:** estudio de eventos con coeficientes trimestrales de `Shock × Paga × 1[t = k]` para k pre (deben ser conjuntamente nulos, p > 0,10).
- Estimación: MCO lineal (LPM) con `pyfixest`, como principal; logit en tiempo discreto como robustez.

### D2: regresión kink en el tope de gradualidad (+25%)
- **Variable de asignación:** aumento porcentual teórico de la cuota, `(cuota 2022 sin gradualidad / (cuota 2021 × 1,051)) − 1`.
- **Kink:** en 25% el alza pagada deja de crecer con el alza teórica. La pendiente de la primera etapa cambia de ≈ 1 a 0.
- **Muestra:** G_0 afectos en 2021 y 2022, con cuota 2022 > $9.415.
- **Estimación:** `rdrobust` con `deriv=1` (fuzzy RKD), ancho de banda óptimo MSE, polinomio local lineal y kernel triangular.
- **Requisitos previos, revisados antes de mirar Y:**
  - cambio de pendiente de la primera etapa significativo (F > 10);
  - densidad de la variable de asignación sin quiebre en el kink (prueba de McCrary sobre la derivada);
  - covariables suaves en el kink.
- Si la primera etapa no cumple, D2 **se abandona** y se reporta así.
- **Resultado:** Y1 en el horizonte 2022-T1 → 2023-T4, mientras la gradualidad muerde.

### D3: tope de $9.415 para quienes pasan de exentos a afectos
- **Muestra:** roles exentos en 2021-2S (contribución teórica 0) que pasan a afectos en 2022-1S.
- **Variable de asignación:** cuota teórica 2022.
- **Kink:** en $9.415 por cuota. Bajo el tope se paga todo; sobre él, la cuota pagada queda plana en $9.415.
- Mismo procedimiento y requisitos que D2.

### D4 (condicional a ampliar datos): salto del factor comunal de Maipú (0,80 → 0,90)
- Requiere procesar comunas vecinas comparables, cuyo factor comunal no cambió entre 2018 y 2022 (por verificar en las Res. 28/2018 y 143/2021), desde los archivos históricos nacionales ya descargados.
- **Diseño:** diferencias en diferencias Maipú vs. vecinas, con tratamiento igual al componente mecánico de construcción.
- **No se estima en v1.0.** Si se agrega, se registra como desviación antes de mirar resultados.

### Diseño descartado
- **IV con el componente mecánico de construcción dentro de la manzana:** su desviación intra-manzana es de 0,7 pp (`data_profile.md`) y el instrumento sería débil. Si se reporta, es exploratorio y solo si su F de primera etapa supera 10.

---

## 4. Diseños P2 y P1

### P2
- **H2.1:** `residuo_prop_j = μ_{micro(j), sem(j)} + β · AM_j + X_j'λ + ε_j`.
  - Ventas de segunda mano 2018–2025 con `ratio_ia` válido.
  - `AM_j` = el rol principal tiene `rebaja_21` o `rebaja_22` en {100%, 50%}.
  - Esperado β < 0.
- **H2.2:**
  - Ventas con `residuo_prop` bajo el p10 de su microbarrio y semestre ("descuento") que se revenden dentro de 4 años.
  - Exceso de retorno = log(p_reventa / p_compra) − (SPAR_barrio,t1 − SPAR_barrio,t0).
  - Se compara con el exceso de retorno de reventas que partieron del rango p40–p60.
  - Esperado: mayor exceso. Se reporta junto con el **sesgo de regresión a la media**: un precio bajo medido con ruido "rebota" aunque no haya oportunidad.
  - **Corrección registrada:** el residuo de la compra se calcula con la brecha del microbarrio **excluyendo la propia venta**. La comparación económica se hace neta de 2–4% de costos de transacción.

### P1
- **Panel:** barrio × año t ∈ {2018, 2019, 2020, 2021}, con objetivo Y4 = SPAR(t+4) − SPAR(t+1).
  - Para t = 2021 el objetivo es 2022 → 2025, que ya fue mirado → **exploratorio**.
  - La parte confirmatoria usa t ∈ {2018, 2019, 2020}.
- **Predictor:** brecha relativa del barrio en t = log(brecha_barrio) − log(brecha_comuna), con ventas del año t.
- **Controles / línea base:** momentum = SPAR(t) − SPAR(t−3), calculado con ventas hasta t (sin solapar el objetivo, que parte en t+1).
- **Prueba principal:** coeficiente de la brecha relativa en una regresión con efectos fijos comuna × año, errores agrupados por barrio. Bilateral, α = 0,05. Inferencia por permutación de la brecha entre barrios dentro de cada comuna-año (2.000 réplicas).
- **H1.2:** el modelo predictivo (LightGBM, con las variables de `docs/plan.md` Fase 6) se evalúa como confirmatorio **solo cuando existan objetivos posteriores a 2025** (el reavalúo 2027 o datos de 2026 en adelante). Hasta entonces, todo resultado de ML es exploratorio.

---

## 5. Potencia (calculada antes de estimar)
- Probabilidad base de venta de segunda mano: **2,6% anual** (roles H del panel, 2018–2021).
- **Efecto mínimo detectable** (α = 0,05, potencia 0,8, efecto de diseño 1,5, 4 años pre y 4 post):
  - G_AM (13.821) vs. G_0 (113.161): **≈ 0,35 pp anuales** (≈ 13% relativo);
  - pasan a afecto (14.212) vs. siguen exentos: **≈ 0,35 pp anuales**.
- Para D2 y D3 la potencia se calcula con el ancho de banda óptimo, **antes** de mirar Y, y se reporta junto con la primera etapa.
- **P1:** con ~98 barrios × 3 años y un 43% de varianza señal, la potencia es baja. Un resultado nulo no descarta efectos moderados.

---

## 6. Criterios de decisión (fijados ahora)
- **Efecto económicamente relevante (P3):** un aumento ≥ **15% relativo** en la probabilidad anual de venta por cada +$100.000 de alza anual pagada. Equivale a ≥ 0,4 pp sobre la base de 2,6%.
- **Oportunidad de producto ("vendedor forzado"):** se requieren a la vez:
  - (a) β de D1 significativo y ≥ al umbral anterior;
  - (b) H2.1 con un descuento promedio ≥ **4%** (por sobre los costos de transacción de 2–4%).
  
  Si falla (a) o (b), se abandona el producto de vendedores forzados y se prioriza P1/P2 como producto de valoración.
- **P1 (valor predictivo):** brecha significativa en la prueba principal **y** mejora fuera de muestra sobre el momentum en el retorno del decil superior, neta de costos.
- **Múltiples pruebas:** las hipótesis confirmatorias son H3.1 (D1), H2.1, H2.2 y H1.1. Se corrigen con Holm-Bonferroni (familia de 4). D2, D3 y las heterogeneidades se reportan sin corrección y como secundarias.

---

## 7. Inferencia y robustez
- **Errores agrupados por barrio** (98 conglomerados). Robustez con wild cluster bootstrap (Webb, 999 réplicas) y agrupación por microbarrio.
- **Robustez de D1:**
  - (i) logit en tiempo discreto;
  - (ii) excluir 2021-T3/T4 (anticipación);
  - (iii) `T_pago` en lugar de `T_teo × Paga`;
  - (iv) solo casas o solo departamentos;
  - (v) placebo con Y2 (transferencias sin monto);
  - (vi) placebo temporal, con 2019 como falso año de reavalúo.
- **Datos:**
  - repetir sin las escrituras con `regla_monto == "sumado"`;
  - repetir sin los roles con rebaja "otra";
  - repetir con el umbral de la clasificación de rebajas cambiado ±5 pp.

---

## 8. Amenazas conocidas
- **G_AM no es aleatorio:** son dueños mayores con menor ingreso. Lo absorben los efectos fijos grupo × trimestre. Si las tendencias previas fallan, D1 se reporta como no identificado.
- **Mortalidad diferencial:** en G_AM, la muerte del dueño genera herencias (Y2) y luego ventas. Se controla con la robustez (v) y reportando Y1 y Y2 por separado.
- **Pérdida del beneficio en 2022:** si `rebaja_22` difiere de `rebaja_21`, el rol se excluye de G_AM en la versión estricta.
- **Barrios inferidos sin coordenadas:** los efectos fijos de barrio × trimestre son aproximados. La robustez usa microbarrio × semestre.
- **Gradualidad modelada aproximadamente:** 87% de ajuste al peso en 2022-1S. Los errores de clasificación de `T_pago` atenúan D2.

---

## 9. Registro de desviaciones
| Fecha | Cambio | Motivo | Resultados afectados |
| --- | --- | --- | --- |
| — | — | — | — |
