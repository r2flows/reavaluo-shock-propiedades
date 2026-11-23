# Prototipo: reavalúo fiscal y vendedores forzados — plan para Claude Code

Nov 22, 2026 · @Arturo Gómez Mellado

## Objetivo y alcance

El prototipo responde una sola pregunta con datos reales: ¿el aumento de contribuciones que provocó el reavalúo habitacional 2022 elevó la probabilidad de venta de las propiedades afectadas? Si el efecto existe y supera los costos de transacción, hay base para un producto. Si no, se detiene antes de pagar por datos.

- **Geografía:** Gran Santiago, empezando con Ñuñoa, Providencia y Maipú (nivel socioeconómico mixto) y ampliando después.
- **Ventana:** 2020 a 2025 por semestre, centrada en el reavalúo 2022.
- **Fuera de alcance en esta fase:** precios de lista de portales, modelos de valoración, otros países e interfaz.
- **Por qué ahora:** el reavalúo general no agrícola se postergó hasta 2027 ([SII](https://www.sii.cl/noticias/2026/060226noti01pcr.htm)). Lo que se calibre con 2022 se prueba fuera de muestra con 2027.

## Hipótesis y diseño de identificación

El diseño principal es una regresión discontinua en el umbral de exención, porque compara propiedades casi idénticas con y sin shock de contribuciones.

**Hipótesis**

1. **H1:** las propiedades que pasan de exentas a afectas tras el reavalúo tienen más probabilidad de transferirse en los 6 a 24 meses siguientes.
2. **H2:** si hay precio, esas ventas se cierran con descuento respecto del valor hedónico predicho.
3. **H3:** el efecto es mayor donde la liquidez es baja (tenencia larga, nivel socioeconómico bajo de la manzana, shock alto respecto del ingreso).

**Diseños**

1. **Regresión discontinua.** La variable de corte es el avalúo nuevo menos el monto exento vigente en el primer semestre post reavalúo. El tratamiento es pasar a pagar. Es *fuzzy*, porque la rebaja para adultos mayores hace que algunos tratados no paguen.
2. **Event study con intensidad continua.** El shock es el Δ de contribución calculado dividido por la contribución previa, con efectos fijos de rol y de comuna por trimestre:

```latex
y_{it} = \alpha_i + \gamma_{c(i),t} + \sum_{k \neq -1} \beta_k \, \mathrm{Shock}_i \, \mathbf{1}[t - t_0 = k] + \varepsilon_{it}
```

3. **Placebos:** las propiedades exentas antes y después (sin shock), umbrales falsos a ±10% del real y el ciclo 2018.

La variable de resultado base es la indicación de transferencia por compraventa en el trimestre, a nivel rol. Con precio, se suma el precio en UF dividido por el valor hedónico.

## Fuentes de datos y estado de acceso

El tratamiento ya está cubierto con datos del SII. El único bloqueo es si el archivo público de transferencias trae el precio.

| Fuente | Qué aporta | Acceso | Estado |
| --- | --- | --- | --- |
| [Detalle catastral y rol de cobro (SII)](https://www.sii.cl/destacados/transparencia/index.html) | Avalúo total, exento, contribución semestral y destino por rol; vigente e histórico | Descarga por comuna con RUT y clave tributaria | Existe; falta confirmar cuántos semestres atrás llega |
| [Estructura del detalle catastral](https://www.sii.cl/bbrr/descargas/estructura_detalle_catastral.pdf) | Diccionario de columnas (los archivos vienen sin encabezado, separados por "\|") | PDF público | Disponible; guardar en docs/ |
| [Transferencias F2890 (SII)](https://www.sii.cl/destacados/transparencia/index.html) | Rol, fecha, tipo de escritura y quizás el monto | Zip público (versión del 30-10-2026) | **Por inspeccionar**: campos desconocidos |
| [Datainmobiliaria.cl](https://g5noticias.cl/2026/04/15/data-inmobiliaria-la-plataforma-gratuita-que-democratiza-el-acceso-a-la-inteligencia-inmobiliaria-en-chile/) | Transacciones consolidadas de SII, Conservadores y Tesorería | Plataforma; preguntar por API o base completa | Por contactar si el F2890 no trae precio |
| Permisos de edificación (INE, geodatos abiertos) | Nueva oferta por zona, como control | Descarga pública, georreferenciados desde 2011 | Disponible |
| Censo (INE) | Nivel socioeconómico por manzana o zona | Descarga pública | Verificar la granularidad publicada del 2024 |
| Resoluciones de tablas de valores, monto exento y tasas (SII) | Reconstruir la contribución teórica | Públicas | Disponible |

Si el F2890 viene sin precio, se corre solo H1. Pedir los datos por Ley de Transparencia tiene un precedente en contra: en 2019 la [Corte Suprema](https://www.sii.cl/noticias/2019/100919noti01aav.htm) confirmó el secreto tributario sobre estos datos.

## Arquitectura ETL y esquema de datos

El volumen es de unos millones de filas, así que DuckDB sobre Parquet alcanza. PostGIS solo hace falta para los cruces espaciales, y no se necesita orquestador.

&#91;embedded content: flujo ETL · 3 fuentes, 4 capas\]

Las tres fuentes se unen por rol en staging. El panel de marts es el único insumo del análisis.

| Tabla | Grano | Columnas clave |
| --- | --- | --- |
| dim\_rol | Un rol | rol\_id (comuna-manzana-predio), comuna, destino, superficie de terreno y construida, año de construcción, indicador de copropiedad |
| fct\_avaluo\_semestre | Rol × semestre | aval\_total, aval\_exento, aval\_afecto, contrib\_semestral observada |
| fct\_transferencia | Rol × escritura | escritura\_id, fecha\_escritura, tipo de escritura, monto\_uf |
| map\_rol\_linaje | Cambio de rol | rol\_origen, rol\_destino, fecha, tipo (subdivisión o fusión) |
| mart\_panel | Rol × trimestre | shock\_teorico, dist\_umbral, venta, precio\_uf, controles de manzana |

## Plan de trabajo por fases para Claude Code

Cada fase termina en un entregable verificable. Claude Code no pasa a la siguiente sin cumplir el criterio de aceptación. Los umbrales numéricos son propuestas para ajustar.

1. **Fase 0: Reconocimiento (Arturo + Claude Code).** Arturo descarga el zip F2890 y el detalle catastral de las comunas piloto en data/raw/. Claude Code perfila sin transformar.
   - Entregable: docs/data\_profile.md con columnas, tipos, nulos, rango de fechas, si existe el monto y su cobertura, y tasa de match de roles entre ambas fuentes.
   - Criterio: decisión go/no-go sobre H2 (precio) y sobre la profundidad histórica disponible.
2. **Fase 1: Ingesta y normalización.** Parsers con esquema explícito, tests con fixtures y salida en Parquet particionado por semestre.
   - Criterio: el conteo de roles por comuna concilia con las estadísticas agregadas del SII dentro de ±1%.
3. **Fase 2: Linaje de roles y transacciones.** Tabla de cambios de rol (subdivisiones y fusiones), agrupación por escritura y filtro por tipo de escritura.
   - Criterio: más del 95% de las compraventas hacen match con un rol del catálogo.
4. **Fase 3: Shock teórico.** Implementar la fórmula de contribuciones con el monto exento y las tasas de cada semestre.
   - Criterio: error mediano menor a 1% contra la contribución observada en roles sin rebaja.
5. **Fase 4: Panel y descriptivos.** Panel rol por trimestre, tasa de venta alrededor del umbral, distribución del shock y cálculo de poder estadístico.
   - Criterio: efecto mínimo detectable calculado antes de estimar.
6. **Fase 5: Estimación.** Regresión discontinua, event study y placebos según docs/analysis\_plan.md.
   - Entregable: reporte reproducible con un solo comando.
7. **Fase 6 (condicional): Modelo predictivo.** Solo si la fase 5 muestra efecto. Clasificador de probabilidad de venta para el ciclo 2027, con validación espacial y temporal.

## Trampas conocidas de los datos

La mayoría de los errores silenciosos vendrá de cómo se identifica una propiedad a lo largo del tiempo, no del modelo.

- **Linaje de roles:** las subdivisiones, fusiones y edificios nuevos crean roles sin historia. Sin una tabla de linaje, se pierden ventas o se inventan.
- **Copropiedad:** un departamento se vende junto con su bodega y estacionamiento, que tienen roles separados. Hay que agrupar por escritura y asignar la venta al rol habitacional.
- **Tipo de escritura:** separar compraventa, herencia y otros. Las herencias no son ventas, pero sirven como proxy de propietarios mayores.
- **Duplicados del F2890:** el SII descarta registros que coinciden en comuna, manzana, predio, fecha, tipo de escritura y monto ([criterios de descarte](https://www.sii.cl/destacados/reavaluo/2025/criterios_de_descarte.pdf)). Hay que replicar esa limpieza.
- **Parámetros que cambian cada semestre:** el monto exento y los tramos de tasa se reajustan por IPC. Usar los de cada semestre, nunca los actuales.
- **Rebaja para adultos mayores:** contamina la contribución observada. El tratamiento se calcula con la fórmula teórica.
- **Primera venta de proyectos nuevos:** cuando vende una inmobiliaria no hay vendedor forzado. Excluir la primera transferencia de roles nuevos.
- **Anticipación:** las tablas de valores se publican antes de entrar en vigencia, así que la gente puede vender antes. El event study debe mirar los trimestres previos.
- **Unidades:** los montos vienen en pesos o en UF. Normalizar a UF a la fecha de la escritura.
- **Privacidad:** se trabaja a nivel rol. Nunca guardar RUT ni nombres.

## Validación y criterio de corte

El criterio de corte se fija y se registra en docs/analysis\_plan.md antes de mirar cualquier resultado.

- **Pre-registro:** hipótesis, especificaciones, ancho de banda y variables de resultado escritas en el repositorio antes de la fase 5. Todo cambio posterior queda registrado como exploratorio.
- **Supuestos de la regresión discontinua:** test de densidad de McCrary en el umbral, balance de covariables (superficie, antigüedad, comuna) a ambos lados y sensibilidad al ancho de banda.
- **Supuestos del event study:** coeficientes previos al reavalúo estadísticamente nulos.
- **Placebos:** umbrales falsos, propiedades siempre exentas y ciclo 2018.
- **Modelo predictivo (fase 6):** validación cruzada por bloques espaciales y prueba fuera de tiempo (calibrar con 2022, evaluar con 2027).
- **Criterio económico:** para que haya oportunidad, el descuento debe superar los costos de transacción. Como estimación, esos costos rondan el 2 a 4% entre impuestos, corretaje y notaría, pero hay que confirmarlos.
- **Criterio estadístico:** si el efecto mínimo detectable de la fase 4 supera el efecto económicamente relevante, se amplían las comunas antes de estimar.

## CLAUDE.md y prompt inicial para Claude Code

Copia este CLAUDE.md en la raíz del repositorio y después lanza el prompt de la fase 0.

```markdown
# Proyecto: reavalúo fiscal y vendedores forzados

## Objetivo
Medir si el shock de contribuciones del reavalúo habitacional 2022
aumentó la probabilidad de venta (y el descuento) a nivel de rol del SII.
Plan completo: docs/plan.md. Especificaciones: docs/analysis_plan.md.

## Reglas
- data/raw/ es inmutable: nunca editar, mover ni borrar.
- La clave de una propiedad es el rol: comuna-manzana-predio.
- Nunca guardar RUT, nombres ni otros datos personales.
- Cada parser tiene un esquema explícito y un test con un fixture de unas 50 filas.
- Los archivos del detalle catastral vienen sin encabezado y separados por "|":
  mapear columnas según docs/estructura_detalle_catastral.pdf.
- Montos en UF a la fecha de la escritura.
- Monto exento y tasas: los vigentes en cada semestre, nunca los actuales.
- Cada paso reporta filas de entrada, descartes por motivo y filas de salida.
- No cambiar especificaciones de docs/analysis_plan.md sin registrar el cambio.
- No avanzar de fase sin cumplir su criterio de aceptación en docs/plan.md.

## Estructura
data/raw | data/staging | data/marts
src/etl | src/features | src/models | tests | docs

## Stack
Python 3.12, uv, DuckDB, Polars, Parquet, pyfixest, rdrobust, pytest.

## Comandos
uv run pytest
uv run python -m src.etl.<paso>
```

**Prompt de la fase 0**

```markdown
Lee CLAUDE.md y docs/plan.md. En data/raw/ están el zip F2890 del SII y los
archivos de detalle catastral de las comunas piloto. Perfila ambas fuentes sin
modificarlas ni construir el pipeline todavía.

Entrega docs/data_profile.md con:
1. Estructura detectada de cada archivo: columnas, tipos y separador.
2. Conteos, nulos y rangos (fechas, montos, avalúos).
3. Si el F2890 trae monto de enajenación, en qué unidad y con qué cobertura.
4. Semestres históricos disponibles en el detalle catastral.
5. Tasa de match de roles entre ambas fuentes por comuna.
6. Una recomendación go/no-go para H1 y H2, con los números que la sustentan.
```

## Riesgos y preguntas abiertas

El riesgo más alto es regulatorio: una exención total para adultos mayores anularía el mecanismo justo donde debería ser más fuerte.

- [ ] ¿El F2890 público trae monto de enajenación? Si no, solo H1.
- [ ] ¿El detalle catastral histórico cubre 2021 y 2022 para las comunas piloto?
- [ ] ¿Cuántos roles quedan cerca del umbral con un shock relevante, descontando exentos y beneficiarios de la rebaja? (poder estadístico)
- [ ] La megarreforma en discusión contempla una exención total de contribuciones para la primera vivienda de adultos mayores desde los 65 años ([Pauta](https://www.pauta.cl/dato-en-pauta/2026/08/04/beneficio-de-rebaja-de-contribuciones-para-adultos-mayores-revisa-si-cumples-los-requisitos.html)). Hay que seguir su tramitación.
- [ ] El reavalúo de 2027 podría volver a postergarse, y con eso se retrasa la prueba fuera de muestra.
- [ ] Revisar los términos de uso de cualquier proveedor comercial antes de automatizar la descarga.

## Fuentes

- [SII: postergación del reavalúo no agrícola a 2027](https://www.sii.cl/noticias/2026/060226noti01pcr.htm)
- [SII: portal de transparencia (detalle catastral, F2890)](https://www.sii.cl/destacados/transparencia/index.html)
- [SII: estructura del detalle catastral](https://www.sii.cl/bbrr/descargas/estructura_detalle_catastral.pdf)
- [SII: criterios de descarte de muestras](https://www.sii.cl/destacados/reavaluo/2025/criterios_de_descarte.pdf)
- [SII: Corte Suprema y secreto tributario de transferencias](https://www.sii.cl/noticias/2019/100919noti01aav.htm)
- [SII: beneficio adulto mayor](https://www.sii.cl/destacados/avaluaciones/bam)
