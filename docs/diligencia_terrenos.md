# Debida diligencia de terrenos: qué puede omitir el vendedor y cuánto cubrimos

Fecha: 28-11-2026. Es un producto: no cambia `docs/analysis_plan.md`.
Código: `src/producto/diligencia.py`, que se muestra en la ficha de terreno (`/terreno`). Tests: `tests/test_diligencia.py`.

## 1. Cobertura por riesgo
Puntaje: 0 = no cubierto; 1 = indicio con datos públicos; 2 = verificado con un documento.

| Riesgo que el vendedor puede omitir | Antes | Hoy | Cómo | Qué falta para llegar a 2 |
|---|---|---|---|---|
| Herencia o comunidad sin resolver | 0 | 1 | Última transferencia sin monto (desde 2015 y no en bloque); varias enajenaciones el mismo día | Posesión efectiva e inscripción especial de herencia (subidas por el abogado) |
| Venta de cuotas o "derechos" | 1 | 1 | Enajenaciones del mismo día; precio menor que la mitad del avalúo; rotación alta | Inscripciones de cada cuota |
| Hipotecas, prohibiciones, embargos, litigios, usufructo | 1 | 1 | Lector del certificado GP en el pre-informe (con clave) | Integrar ese lector a la ficha de terreno (etapa 2) |
| Deuda de contribuciones | 0 | 0 | — (se pide el certificado de la TGR) | Leer el certificado TGR subido (etapa 2) |
| Urbano/rural y zonificación | 1 | 1 | Código U/R/E del SII; alerta para E | Capas del PRMS/PRC (etapa 3) y lectura del CIP (etapa 2) |
| Subdivisión irregular (DL 3.516) | 0 | 1 | Ubicación R/E con menos de 5.000 m²; rol nuevo o con rol padre | Certificado del SAG y plano aprobado |
| Afectación de utilidad pública o expropiación | 0 | 0 | — (se piden los certificados) | Capas del PRMS/PRC y los certificados |
| Riesgos naturales | 0 | 0 | — | Capas de riesgo del PRMS, SERNAGEOMIN y CONAF (etapa 3) |
| Derechos de agua | 0 | 1 | Suelo de riego 1R–4R → exigir derechos inscritos | Consulta en la DGA y certificado del CBR de aguas |
| Protección ambiental o patrimonial | 0 | 0 | — | Capas del MMA, SNASPE y CMN (etapa 3) |
| Ocupación (tomas, campamentos) | 0 | 0 | — | Catastro de campamentos del MINVU (etapa 3) |
| Construcciones sin permiso | 1 | 1 | Aumento de superficie desde 2022 → pedir recepción final | Certificado de recepción |
| Contribuciones 2027 | 1 | 1 | Rango del estimador en la ficha | Valores oficiales del SII 2027 |
| **Total (sobre 26)** | **5** | **9** | | |

Lo que **no se puede detectar con datos públicos por rol**, y la ficha lo dice:
- **Dueño fallecido sin posesión efectiva inscrita.** No aparece ninguna transferencia: el catastro y el F2890 siguen igual hasta que alguien inscribe.
- **Juicios y deudas personales del vendedor.** Se buscan por nombre o RUT y son datos personales: los revisa el abogado.
- **Arriendos y ocupantes.**

## 2. Calibración de la señal de herencia (F2890)
La falta de monto es una señal débil y por eso queda en nivel "revisar":
- Antes de 2010, casi ningún registro trae monto.
- En Ñuñoa, Maipú y Pirque, la última transferencia viene sin monto en:
  - el 26% de las ventas en bloque desde 2015 (depto + bodega + estacionamiento: el monto va en otro rol);
  - el 2,1% de las ventas individuales desde 2015.
- La regla usa solo ese 2,1%: transferencias individuales desde 2015.

En una muestra de 1.500 roles del Gran Santiago:

| Señal | Roles |
|---|---|
| Rol nuevo o con rol padre | 159 |
| Precio menor que la mitad del avalúo | 11 |
| Aumento de superficie | 10 |
| Probable extensión urbana | 9 |
| Enajenaciones del mismo día | 8 |
| Rotación alta | 4 |
| Última transferencia sin monto | 2 |

## 3. Protocolo de evaluación (pendiente de casos)
1. Christian o un estudio jurídico aporta **20–30 operaciones de terrenos cerradas o caídas**, anonimizadas: el rol, la comuna y qué problema apareció en el estudio de títulos o después de la compra.
2. Se corre la ficha **sin ver el resultado** y se mide, por categoría:
   - detección;
   - falsas alarmas;
   - casos con problema que quedaron "sin alertas".
3. **Criterios:**
   - advertir al menos el 70% de los problemas que se pueden ver con datos públicos o con certificados subidos;
   - 0 problemas críticos (herencia, embargo, afectación) en categorías que la ficha muestre "sin alertas" sin aclarar lo que no cubre. Por eso "gravámenes" y "riesgos" aparecen como "no verificado" y nunca como "sin alertas".
4. **Prueba de uso:** 5 compradores o corredores en compras reales. Se mide el tiempo ahorrado y qué documentos pidieron gracias a la ficha.
5. Los resultados se registran en esta sección y la matriz se recalcula.

## 4. Próximas etapas
2. **Certificados subidos en la ficha** (con clave, en memoria): GP, deuda TGR, CIP y no expropiación. Así el semáforo pasa de "indicio" a "verificado".
3. **Capas geográficas públicas:** zonificación y límite urbano del PRMS, áreas de riesgo, humedales urbanos, áreas protegidas, zonas típicas y campamentos. Antes de descargar hay que revisar los términos de uso. Necesita ubicar cada rol en el mapa: microbarrios aproximados, la cartografía del SII o la geocodificación del predio rural.
4. **Con socios o normativa:** el repositorio digital de los CBR (reglamento de la Ley 21.772) y un convenio con la TGR.
