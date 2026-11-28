# Proyecto: brecha avalúo–mercado y oportunidades inmobiliarias

## Objetivo
Medir si la brecha entre el valor de mercado y el avalúo fiscal del SII predice retornos
por barrio y por propiedad, y si el shock de contribuciones de los reavalúos (2018, 2022, 2027)
genera vendedores forzados. Piloto: Gran Santiago.
Plan vigente: docs/plan.md. Crítica del plan original: docs/evaluacion_critica.md.
Especificaciones pre-registradas: docs/analysis_plan.md.

## Reglas
- data/raw/ es inmutable: nunca editar, mover ni borrar.
- La clave de una propiedad es el rol: comuna-manzana-predio.
- Nunca guardar RUT, nombres ni otros datos personales en el repo, en data/ ni en ningún archivo o base persistente.
- Vincular un rol con su dueño solo se permite en el servicio de títulos (src/titulos/; abierto sin clave desde el 28-11-2026,
  a pedido del usuario, con límite de consultas por IP), a partir de
  certificados del Conservador que el propio usuario sube para un encargo concreto: se procesan en memoria, se muestran
  en pantalla y se descartan. Prohibido: guardarlos, registrarlos en logs, publicarlos o armar índices masivos rol→dueño.
  Cambio de regla del 24-11-2026, a pedido del usuario: ver docs/conservadores_y_titulos.md §5.
- Cada parser tiene un esquema explícito y un test con un fixture de unas 50 filas.
- Los archivos del detalle catastral vienen sin encabezado y separados por "|":
  mapear columnas según docs/estructura_detalle_catastral.pdf.
- Montos en UF a la fecha de la escritura.
- Monto exento y tasas: los vigentes en cada semestre, nunca los actuales.
- Las variables para ML usan solo información disponible en t (sin filtración temporal).
- Validación de modelos: hacia adelante en el tiempo + bloques espaciales; siempre contra una línea base de momentum.
- Cada paso reporta filas de entrada, descartes por motivo y filas de salida.
- No cambiar especificaciones de docs/analysis_plan.md sin registrar el cambio.
- No avanzar de fase sin cumplir su criterio de aceptación en docs/plan.md.
- Revisar los términos de uso antes de automatizar cualquier descarga de un proveedor o portal.

## Estructura
data/raw | data/staging | data/marts
src/etl | src/features | src/models | tests | docs

## Stack
Python 3.12, uv, DuckDB, Polars, Parquet, pyfixest, rdrobust, lightgbm, shap, scikit-learn, pytest.

## Comandos
uv run pytest
uv run python -m src.etl.<paso>
