# Evaluación crítica del plan "Reavalúo fiscal y vendedores forzados"

Documento evaluado: `Prototipo reavalúo fiscal y vendedores forzados — plan para Claude Code.md` (raíz del repo, 22-11-2026). El plan vigente que resulta de esta evaluación está en `docs/plan.md`.

Las afirmaciones marcadas **[verificar]** dependen de normativa o datos que se confirman en la Fase 0.

## 1. Fallas críticas

### 1.1 La regresión discontinua en el umbral de exención mide casi nada
*Afecta a: "Hipótesis y diseño de identificación", diseño 1.*

- El monto exento habitacional **se descuenta** del avalúo (avalúo afecto = total − exento) [verificar en la Ley 17.235 y en las resoluciones del semestre]. Cruzar el umbral no produce un salto en el impuesto: es un **quiebre de pendiente (kink)**, no un notch.
- En el umbral el impuesto vale ≈ 0. Ejemplo: avalúo 10% por sobre el exento → tasa × 0,1 × exento ≈ 0,9% × 0,1 × ~$55 MM ≈ **$50 mil al año**.
- Consecuencia: la RD casi seguro dará un efecto nulo y puede llevar a un **"no-go" falso** sobre toda la tesis. Lo único que mediría es el efecto de prominencia de "empezar a pagar".
- **Arreglo:** RKD en el exento como diseño secundario; la identificación principal pasa a los diseños de §2.

### 1.2 El shock es endógeno a la plusvalía local
*Afecta a: diseño 2 (event study).*

- El SII reavalúa con precios de mercado: el Δ de contribución es mayor donde más subieron los precios, y esa plusvalía también mueve la tasa de venta. Los FE comuna×trimestre no resuelven el problema, porque la variación ocurre dentro de la comuna.
- **Arreglo:** separar el shock en un componente de terreno (AHV, de mercado) y uno de construcción (tablas nacionales por clase y calidad, **mecánico**) [verificar], y usar el componente mecánico como instrumento con FE manzana×trimestre.

### 1.3 La aritmética económica no está al inicio
*Afecta a: "Validación y criterio de corte", criterio económico.*

- Las contribuciones rondan ~1% del avalúo, y el avalúo es menor que el valor comercial. Un alza del 20–30% equivale a ~0,1–0,2% del valor por año. La mayor parte se capitaliza en el precio de **todas** las ventas, no en un descuento para vendedores forzados.
- La tesis solo funciona en un subgrupo: dueños con patrimonio inmobiliario y bajos ingresos (adultos mayores, sucesiones). Ese subgrupo debe ser el foco desde el inicio, no una heterogeneidad (H3).
- **Arreglo:** una Fase 0.5 de "servilleta económica" antes del ETL.

### 1.4 Gradualidad del alza [verificar]
*Afecta a: Fase 3 y la definición de t₀.*

Si existe un tope o una gradualidad semestral del alza, el tratamiento se reparte en varios semestres y la primera etapa se debilita. Hay que reconstruirla. Si existe, además aporta variación exógena adicional (roles topeados vs. no topeados).

## 2. Mejores diseños de identificación

1. **Notch del beneficio de adulto mayor [verificar el monto].** La rebaja exige un avalúo bajo un límite. Si el reavalúo empuja una propiedad por sobre ese límite, pierde toda la rebaja (50% o 100%): un salto discreto en la población "forzada". Los beneficiarios se infieren **sin RUT**: contribución observada < teórica. La "contaminación" del plan original pasa a ser la señal.
2. **IV con el shock mecánico dentro de la manzana** (tablas de construcción × clase, calidad y antigüedad).
3. **Experimento de signo opuesto:** si se aprueba la exención de contribuciones para la primera vivienda de mayores de 65, el mismo grupo debería reducir su probabilidad de venta.
4. **El ciclo 2018 es una réplica, no un placebo** (también tuvo tratamiento). Con 2027 como prueba fuera de muestra quedan tres ciclos.

## 3. Problemas menores que importan

- **Poder estadístico:** la tasa de venta es ~1% por trimestre. Conviene un modelo de duración en tiempo discreto con riesgos competitivos (compraventa / herencia / remate) en vez de un binario rol×trimestre.
- **Inferencia:** el shock de terreno se asigna por AHV, así que los errores se agrupan por AHV.
- **Hedónico sin precio de lista:** usar precio/avalúo relativo a la mediana de la manzana (el avalúo ya es el hedónico del SII).
- **Rezagos:** la ventana de 6–24 meses se mide desde la **notificación** del avalúo, no desde su vigencia; hay que considerar el desfase escritura → inscripción.
- **Departamentos vs. casas:** el peso del terreno difiere, así que conviene estimar por separado.

## 4. Riesgos subestimados

- **Ley 21.719 de protección de datos personales** (vigencia prevista para diciembre de 2026) [verificar]. El análisis a nivel rol es seguro; pasar de rol a contacto con el dueño no lo es.
- **Riesgo reputacional** de un producto que "caza" adultos mayores con contribuciones altas. Alternativa: ofrecer liquidez (compra de nuda propiedad con usufructo vitalicio, sale-leaseback o financiamiento de contribuciones).
- **Riesgo político simétrico:** eliminar las contribuciones de la primera vivienda anula el mecanismo, pero crea la oportunidad de capitalización contraria.

## 5. Reencuadre adoptado

El plan original es un caso particular de una idea más general: **la brecha entre avalúo fiscal y valor de mercado, y su dinámica, como predictor de oportunidades**. El reavalúo es el momento en que el Estado cierra administrativamente esa brecha. El plan vigente (`docs/plan.md`) fusiona ambas ideas, con piloto en Gran Santiago.
