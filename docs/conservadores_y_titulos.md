# Conservadores de Bienes Raíces y estudio de títulos: situación de datos y opciones

Fecha: 24-11-2026. Es una herramienta separada del estudio académico; no cambia `docs/analysis_plan.md`.

## 1. Situación (lo verificado)

**Marco legal: Ley 21.772**, que reforma el sistema registral y notarial.
- Fue publicada el 1-10-2025 y entró en vigencia general el 2-4-2026 (según Cuatrecasas).
- El texto consolidado de la Ley del Registro Conservatorio se leyó en el reporte de la Academia Judicial (nov. 2025).
- Art. 5 bis: los conservadores deben tener medios electrónicos para:
  - emitir copias y certificados electrónicos;
  - intercambiar información con otros organismos;
  - dar acceso remoto a un **repositorio digital** con copias electrónicas de las inscripciones. Sus características técnicas las fijará un reglamento de los ministerios de Justicia y de Hacienda.
- Art. 5 bis N°5: en su sitio web, los usuarios deben poder **consultar gratis los índices de sus registros y las inscripciones practicadas**, y solicitar nuevas inscripciones.
- Plazos: según Cuatrecasas, las obligaciones electrónicas rigen **6 meses después de publicado el reglamento**. No encontramos la fecha de ese reglamento.
- Art. 78: la inscripción de dominio debe indicar el **rol de avalúo fiscal**, la dirección y la superficie, y además la cédula de identidad del adquirente. El rol pasa a ser la llave común con el catastro del SII, pero cada inscripción contiene datos personales.
- Art. 5 ter: los conservadores responden en 30 días los requerimientos de información de **órganos del Estado**, no de particulares.
- Art. 3: cada conservador debe exhibir un cuadro con las comunas de su jurisdicción.

**Oferta actual del CBR de Santiago** (fichas de ChileAtiende):
- Certificados en línea, con cuenta y pago: dominio vigente e hipotecas y gravámenes (GP). El de dominio vigente llega en unas 2 horas hábiles.
- Una **"carpeta de estudio de títulos de hasta 10 años"**, en unos 5 días hábiles. Los bancos suelen pedir certificados con menos de 30 días.
- Para algunos registros antiguos, el Archivo Nacional entrega copias con ClaveÚnica.

**Lo que no existe** (o no encontramos):
- API pública ni datos masivos de ningún Conservador.
- Términos de uso publicados que autoricen la extracción automatizada.
- Un proveedor chileno que haga estudios de títulos automatizados vía API.

**Jurisdicción por comuna** (`src/etl/ref/cbr_por_comuna.csv`):
- **Verificado** con el mapa de jurisdicción de cbrsanmiguel.cl: el CBR de San Miguel atiende San Miguel, La Cisterna, La Granja, El Bosque, San Ramón, San Joaquín, Lo Espejo y La Pintana.
- Pedro Aguirre Cerda queda fuera de ese mapa; el sitio de San Miguel anuncia un nuevo Conservador de Pedro Aguirre Cerda.
- La Florida no pertenece a San Miguel; falta confirmar si es Santiago o Puente Alto.
- El resto sigue `por_verificar`: los sitios de Puente Alto y San Bernardo no resolvieron por DNS y conservadores.cl tenía el certificado vencido.

## 2. Opciones

| # | Opción | Qué permite | Estado / requisito | Recomendación |
|---|---|---|---|---|
| A | **Pre-informe por rol + certificados que compra el abogado** | Saber qué pedir, a qué CBR y de qué años; alertas antes de leer los títulos | **Hecho**: `src/titulos/preinforme.py`, privado y sin datos personales | Usar ya |
| B | Consulta gratuita de índices e inscripciones (art. 5 bis N°5) | Ubicar fojas, número y año de una inscripción sin pagar | Depende de que cada CBR la implemente. Solo consulta individual, hecha por el profesional. **No** extraer en masa: datos personales (Ley 21.719) y sin términos que lo autoricen | Monitorear los sitios de los CBR de la RM |
| C | Repositorio digital del reglamento (art. 5 bis N°3 c) | Posible acceso remoto estandarizado e interoperabilidad | Reglamento pendiente; vigencia 6 meses después | Seguir su publicación en el Diario Oficial |
| D | Convenio con un CBR o un proveedor tecnológico | Integración B2B (por ejemplo, pedir certificados desde el pre-informe) | Requiere una persona jurídica, un contrato y una evaluación de protección de datos | Evaluar si el producto B2B tiene demanda |
| E | Lector de certificados que sube el abogado (PDF procesado en memoria) | Cruzar la cadena de inscripciones con el F2890: años sin inscripción, montos o rol distintos | **Contradice la regla de CLAUDE.md** de no vincular rol y dueño, aunque no se guarde nada | Solo con una decisión explícita y un cambio registrado de la regla |
| F | Ley de Transparencia ante el CBR | — | Los CBR son auxiliares de la administración de justicia; la aplicabilidad de la Ley 20.285 está por confirmar | No prioritario |

## 3. Pre-informe: qué hace hoy

`.venv/bin/python -m src.titulos.preinforme 13101-152-779`, o con `--comuna "San Joaquín" 4819-25`, o con `--lote archivo.txt`.
La salida va a `privado/preinformes/<rol>.html`, que está en `.gitignore`.

Contenido:
- identificación y avalúo;
- rol matriz y roles de bien común;
- historia del rol en 2021-2S, 2022-1S y 2026-2S;
- cadena de transferencias del F2890, con las fechas de escritura e inscripción;
- guía de qué inscripciones pedir: las de los últimos 10 años más la anterior que completa el plazo;
- contribuciones 2027 estimadas;
- lista de lo que no cubre.

Alertas:
- precio menor al 50% de lo típico del microbarrio (cuota de derechos, venta entre relacionados o lesión enorme);
- inscripción anterior a la escritura;
- venta en bloque;
- rol nuevo o dado de baja;
- cambio de destino;
- salto de avalúo;
- exención especial.

Límites:
- El F2890 no trae fojas ni número, así que la búsqueda en el CBR se hace por fecha de inscripción.
- Las fechas imposibles (año menor a 1950 o futuro) se descartan y se informa cuántas fueron.

## 4. Decisiones del usuario (24-11-2026)
El usuario aprobó el servicio privado con clave, la opción E (lector de certificados), verificar los CBR por comuna y flexibilizar la regla de CLAUDE.md.

## 5. Cambio de regla y servicio privado
**Regla anterior:** «Nunca guardar RUT, nombres ni otros datos personales. No construir nada que vincule un rol con su dueño».

**Regla nueva** (CLAUDE.md):
- Sigue prohibido **guardar** datos personales en cualquier archivo o base.
- Vincular un rol con su dueño solo se permite en el servicio privado de títulos, con certificados que el usuario sube para un encargo concreto. Se procesan en memoria, se muestran y se descartan.
- Siguen prohibidos los logs, la publicación y los índices masivos rol→dueño.

**Servicio** `preinforme-titulos` (Railway, mismo proyecto que el atlas):
- **Código:** `src/titulos/app.py` (FastAPI) y `certificados.py`, que lee el texto del PDF y extrae fojas, número, año, roles, personas con cédula, montos y cargas, y luego cruza con el F2890.
- **Datos:** `src.titulos.empaquetar` deja unos 210 MB en `privado/servicio/datos`. `src.titulos.construir_servicio` arma `privado/servicio/build`. Ambas carpetas están fuera de git.
- **Seguridad:**
  - HTTP Basic sobre HTTPS, con usuario y clave en variables de Railway; copia local en `.env`.
  - Bloqueo de 15 minutos tras 10 intentos fallidos por IP.
  - Respuestas `no-store` y `noindex`, con CSP estricta.
  - Sin registro de accesos, sin base de datos y sin escritura de archivos.
  - El servicio no parte sin una clave de al menos 16 caracteres.
- **Actualizar:** `scripts/correr.sh --mem 5G src.titulos.empaquetar && .venv/bin/python -m src.titulos.construir_servicio && cd privado/servicio/build && railway up --ci --service preinforme-titulos --project <id> --environment production`.
- **Límites:**
  - Los PDF escaneados (sin texto) no se leen, porque no hay OCR.
  - La extracción es heurística y el abogado debe verificarla.
  - El servicio tiene un único usuario compartido.

Fuentes:
- Ley 21.772 en BCN: https://www.bcn.cl/leychile/navegar?idNorma=255400
- Reporte de la Academia Judicial: https://academiajudicial.cl/wp-content/uploads/2025/11/Reporte_Actualizacion_Normativa_Ley_Sistema_Registral_vf.pdf
- Cuatrecasas: https://www.cuatrecasas.com/es/latam/publico/art/ley-21-772-reforma-sistema-registral-notarial
- ChileAtiende, carpeta de estudio de títulos: https://www.chileatiende.gob.cl/fichas/30436-carpeta-de-estudio-de-titulos-de-hasta-10-anos
- ChileAtiende, certificado GP: https://www.chileatiende.gob.cl/fichas/457-certificado-de-los-registros-de-hipotecas-gravamenes-y-prohibiciones-de-una-propiedad-gp

## 6. Acceso abierto (28-11-2026)
A pedido del usuario, el servicio quedó **sin clave** en todas sus rutas: pre-informe de títulos, lector de certificados, ficha de terreno y revisión de avalúo.
- Se mantiene la regla de fondo: los certificados que sube el usuario se procesan en memoria, se muestran y se descartan. No se guardan ni se registran.
- Límites por IP: 60 consultas cada 10 minutos y 20 lecturas de certificados cada 10 minutos.
- Riesgo asumido: cualquiera puede consultar el pre-informe de cualquier rol. El pre-informe no trae datos personales, porque el catastro y el F2890 no tienen nombres. Los nombres solo aparecen si el propio usuario sube un certificado, y solo se le muestran a él.
- Para volver a cerrar una ruta, se cambia `Depends(limitar)` por `Depends(autenticar)` en `src/titulos/app.py`.
