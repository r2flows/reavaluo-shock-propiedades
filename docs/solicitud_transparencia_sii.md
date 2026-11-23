# Borrador: solicitud de acceso a información pública al SII (Ley 20.285)

**Canal:** Portal de Transparencia del Estado → Servicio de Impuestos Internos → "Solicitud de acceso a la información" (https://www.portaltransparencia.cl). La envía el solicitante; completar sus datos en el formulario del portal, no en este archivo.

**Organismo:** Servicio de Impuestos Internos (SII).

---

**Información solicitada:**

Solicito copia, en formato digital geoespacial (shapefile, GeoPackage o GeoJSON, en el sistema de referencia que el Servicio utilice), de las siguientes capas cartográficas que el SII ya publica como imágenes en su visor "Cartografía Digital SII Mapas" (https://www4.sii.cl/mapasui/internet/), para las comunas de la Provincia de Santiago, Puente Alto y San Bernardo (Región Metropolitana):

1. **Manzanas** (capa publicada como `BR_CART_MANZANAS`), con los atributos de código de comuna SII y número de manzana, a la fecha más reciente disponible.
2. **Áreas Homogéneas** de los procesos de reavalúo no agrícola 2018 y 2022 (capas "Áreas Homogéneas RAV 2018" y "RAV NA 2022"), con su código de área homogénea y, si existe en la capa, el valor unitario de terreno asociado.

No solicito información de contribuyentes, roles individuales, propietarios ni datos protegidos por secreto tributario (artículo 35 del Código Tributario). Las capas pedidas son polígonos territoriales que el Servicio ya pone a disposición del público en su visor, y la solicitud solo pide entregarlas en un formato reutilizable.

**Finalidad (opcional):** investigación sobre la aplicación del impuesto territorial y la evolución de los avalúos fiscales en el Gran Santiago. Los resultados se publicarán agregados por barrio, citando la fuente como "www.sii.cl, Cartografía Digital SII Mapas", según indican las condiciones de uso del visor.

**Forma de entrega preferida:** archivo digital por correo electrónico o enlace de descarga.

---

## Notas internas (no incluir en la solicitud)
- Plazo legal: 20 días hábiles, prorrogables por 10 (art. 14, Ley 20.285). Si se deniega o no hay respuesta, procede el amparo ante el Consejo para la Transparencia (15 días hábiles).
- Precedente relevante: en 2019 la Corte Suprema confirmó el secreto tributario sobre datos de transferencias individuales. Por eso la solicitud se limita a la cartografía, que el SII ya publica, y excluye expresamente roles y contribuyentes.
- Cuando llegue la geometría:
  1. cargar `data/raw/geo/` (manzanas SII);
  2. disolver por `microbarrio_id`/`barrio_id` (`data/staging/map_barrio.parquet`);
  3. validar la contigüidad de los barrios inferidos;
  4. activar en el atlas el segundo nivel de zoom.
- Las Áreas Homogéneas permitirían reemplazar la aproximación por microbarrio con las unidades reales de valoración del SII.
