"""Carpeta de la propiedad para corredores y brokers (MVP): todo lo que hay que saber de un rol en un documento imprimible.

Secciones:
  1. Resumen: semáforo de riesgos (src.producto.diligencia) y datos clave.
  2. Identificación: ficha de terreno (src.producto.terreno).
  3. Antifraude: si se suben certificados del Conservador y el RUT del vendedor (src.producto.antifraude y
     src.titulos.certificados), procesados SOLO EN MEMORIA.
  4. Historia de transferencias (F2890).
  5. Valor: comparables depurados y evolución del índice de precios del barrio (solo viviendas del Gran Santiago).
  6. Riesgos y documentos (src.producto.diligencia).
  7. Trámites por organismo, con casillas de estado para imprimir.
Se imprime o guarda como PDF desde el navegador (Ctrl+P); el CSS de impresión oculta los formularios.
"""

from __future__ import annotations

import datetime as dt
import html
import math

import polars as pl

from src.etl.common import REF
from src.producto import antifraude as af
from src.producto import comparables as cp
from src.producto import diligencia as dil
from src.producto import terreno as ter
from src.titulos import preinforme as pi

# (id, organismo, documento, para qué sirve, dónde, condición: None = siempre, o la regla de diligencia que lo activa)
TRAMITES = [
    ("dominio", "Conservador de Bienes Raíces", "Copia de inscripción de dominio con vigencia", "Quién es el dueño hoy y por qué título", "Sitio del Conservador de la comuna", None),
    ("gp", "Conservador de Bienes Raíces", "Certificado de hipotecas, gravámenes, interdicciones y prohibiciones (30 años)", "Hipotecas, embargos, prohibiciones, litigios, usufructos", "Sitio del Conservador de la comuna", None),
    ("tgr", "Tesorería General de la República", "Certificado de deuda de contribuciones", "Que no haya deuda de contribuciones", "tgr.cl (gratis)", None),
    ("sii", "Servicio de Impuestos Internos", "Certificado de avalúo fiscal detallado", "Superficie y construcciones registradas, avalúo y exenciones", "sii.cl (gratis)", None),
    ("cip", "Municipalidad (Dirección de Obras)", "Certificado de Informaciones Previas", "Zonificación, uso de suelo permitido, afectaciones de utilidad pública", "Dirección de Obras de la municipalidad", None),
    ("numero", "Municipalidad (Dirección de Obras)", "Certificado de número", "Dirección oficial del predio", "Dirección de Obras de la municipalidad", None),
    ("expro", "Municipalidad y SERVIU", "Certificados de no expropiación", "Que el predio no esté afectado por una expropiación", "Municipalidad y SERVIU Metropolitano", None),
    ("pe", "Registro Civil", "Posesión efectiva", "Quiénes son los herederos, si hubo herencia", "registrocivil.cl", "herencia_probable"),
    ("ieh", "Conservador de Bienes Raíces", "Inscripción especial de herencia", "Que los herederos sean dueños inscritos", "Sitio del Conservador de la comuna", "herencia_probable"),
    ("cuotas", "Conservador de Bienes Raíces", "Inscripciones de cada cuota y su dueño actual", "Que vendan todos los comuneros o el dueño del 100%", "Sitio del Conservador de la comuna", "cuotas_mismo_dia"),
    ("sag", "Servicio Agrícola y Ganadero", "Certificado de subdivisión de predio rústico", "Que la subdivisión cumpla el DL 3.516", "sag.gob.cl", "subdivision_rural"),
    ("plano", "Municipalidad (Dirección de Obras)", "Plano de subdivisión o loteo aprobado", "Que el rol nuevo venga de una subdivisión aprobada", "Dirección de Obras de la municipalidad", "rol_nuevo"),
    ("agua", "Conservador de Bienes Raíces (Registro de Aguas)", "Inscripción de los derechos de agua", "Que el suelo de riego tenga agua", "Conservador de la comuna", "suelo_riego"),
    ("dga", "Dirección General de Aguas", "Consulta en el Catastro Público de Aguas", "Derechos de agua registrados", "dga.mop.gob.cl", "suelo_riego"),
    ("recepcion", "Municipalidad (Dirección de Obras)", "Permiso de edificación y certificado de recepción final", "Que las construcciones estén regularizadas", "Dirección de Obras de la municipalidad", "superficie_aumento"),
    ("gc", "Administración del condominio", "Certificado de gastos comunes al día y reglamento de copropiedad", "Deudas y reglas del condominio", "Administración del edificio o condominio", "copropiedad"),
]


def tramites(alertas: list[dil.Alerta], copropiedad: bool) -> list[tuple]:
    activas = {a.regla for a in alertas} | ({"copropiedad"} if copropiedad else set())
    return [t for t in TRAMITES if t[5] is None or t[5] in activas]


def cbr_de(cod_comuna: int) -> str:
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";").filter(pl.col("cod_comuna") == cod_comuna)
    if not cuts.height:
        return "Conservador de la comuna"
    c = pl.read_csv(REF / "cbr_por_comuna.csv", separator=";").filter(pl.col("cut") == int(cuts["cut"][0]))
    return f"CBR de {c['cbr_probable'][0]}" + ("" if c["estado"][0] == "verificado" else " (probable)") if c.height else "Conservador de la comuna"


def indice_barrio(barrio_id: str | None) -> dict | None:
    f = pi.MARTS / "indice_spar_barrio.parquet"
    if not barrio_id or not f.exists():
        return None
    s = pl.scan_parquet(f).filter(pl.col("barrio_id") == barrio_id).collect().sort("anio")
    s = s.filter(pl.col("n") >= 10)
    if s.height < 4:
        return None
    ult = s.row(-1, named=True)
    def var(anios: int, col: str) -> float | None:
        p = s.filter(pl.col("anio") == ult["anio"] - anios)
        return math.exp(ult[col] - p[col][0]) - 1 if p.height else None
    return {"anio": ult["anio"], "b3": var(3, "spar_log"), "c3": var(3, "spar_log_comuna"), "b8": var(8, "spar_log"), "c8": var(8, "spar_log_comuna")}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.0f}%".replace("+", "+").replace("-", "−")


def armar(rid: str, comuna: str, corredora: str = "", lecturas: list | None = None, rut_vendedor: str | None = None) -> str | None:
    e = html.escape
    d = ter.ficha(rid)
    if d is None:
        return None
    x = dil.cargar(d)
    alertas = dil.evaluar(x)
    r = d["rol"]
    copro = (r.get("bc1_predio") or 0) > 0
    hoy = dt.date.today()

    # Valor (solo viviendas y comercio del Gran Santiago, serie no agrícola vigente)
    valor = "<p>Sin comparables para este tipo de predio: por ahora solo se calculan para viviendas del Gran Santiago (los terrenos, parcelas y predios agrícolas no tienen suficientes ventas parecidas).</p>"
    if d["serie"] == "No agrícola" and d["semestre"] == "2026-2S" and r.get("destino") == "H":
        from src.producto import expediente as exp

        ex = exp.leer([rid])
        if ex is not None:
            c, cc = ex["comparables"], ex["comparables_conteo"]
            comp = ex["comp"].row(0, named=True) if ex["comp"].height else {}
            av_uf = (r.get("avaluo_total") or 0) / ex["uf_avaluo"] if ex.get("uf_avaluo") else None
            rs = cp.resumen(c, av_uf, comp.get("sup_construida_total")) if c.height else {"n": 0}
            partes = []
            if rs.get("precio_tipico_uf"):
                partes.append(f"<p><b>Referencia de precio: {pi.uf(rs['precio_tipico_uf'])}</b> (UF/m² mediano de viviendas parecidas de su {e(cc.get('ambito', 'zona'))} × la superficie construida de este rol)"
                              + (f". La mitad central de los comparables se vendió entre {pi.uf(rs['rango_uf'][0])} y {pi.uf(rs['rango_uf'][1])}" if rs.get("rango_uf") else "") + ". "
                              + (f"El avalúo fiscal equivale al {rs['avaluo_sobre_precio'] * 100:.0f}% de ese precio." if rs.get("avaluo_sobre_precio") else "") + "</p>")
            if c.height:
                filas = "".join(f"<tr><td>{x['fecha_escritura']:%m-%Y}</td><td>{e(x['rol_principal'])}</td><td class=n>{x['sup_construida_total'] or '—'}</td><td class=n>{pi.uf(x['monto_uf'])}</td><td class=n>{pi.dec(x['uf_m2']) if x['uf_m2'] else '—'}</td></tr>" for x in c.iter_rows(named=True))
                partes.append(f"<table><thead><tr><th>Fecha</th><th>Rol</th><th class=n>m²</th><th class=n>Precio</th><th class=n>UF/m²</th></tr></thead><tbody>{filas}</tbody></table>"
                              "<p class=nota>Ventas de los últimos 3 años del mismo tipo y tamaño parecido, sin obra nueva ni ventas fuera de mercado. No es una tasación.</p>")
            ib = indice_barrio(ex.get("barrio_id"))
            if ib:
                partes.append(f"<p>Índice de precios de ventas repetidas, hasta {ib['anio']}: el barrio varió <b>{pct(ib['b3'])}</b> en 3 años y {pct(ib['b8'])} en 8 años, en UF "
                              f"(la comuna: {pct(ib['c3'])} y {pct(ib['c8'])}).</p>")
            valor = "".join(partes) or valor

    # Transferencias
    t = x.get("transf")
    bloque = set(x.get("fechas_en_bloque") or ())
    if t is not None and t.height:
        filas_t = "".join(
            "<tr><td>{}</td><td>{}</td><td class=n>{}</td><td>{}</td></tr>".format(
                f"{f['fecha_escritura']:%d-%m-%Y}", f"{f['fecha_inscripcion']:%d-%m-%Y}" if f["fecha_inscripcion"] else "—",
                pi.uf(f["monto_uf_norm"]) if (f["monto_uf_norm"] or 0) > 0 else "sin monto",
                "venta en bloque (depto + anexos)" if f["fecha_escritura"] in bloque else "")
            for f in t.sort("fecha_escritura", descending=True).filter(pl.col("fecha_escritura") <= hoy).head(15).iter_rows(named=True)
        )
        transf = (f"<table><thead><tr><th>Escritura</th><th>Inscripción</th><th class=n>Monto</th><th>Nota</th></tr></thead><tbody>{filas_t}</tbody></table>"
                  "<p class=nota>Enajenaciones informadas al SII por notarios y conservadores (Formulario 2890). Antes de 2010 casi ningún registro trae monto.</p>")
    else:
        transf = "<p>Sin transferencias registradas en el F2890 para este rol.</p>"

    # Antifraude
    if lecturas or rut_vendedor:
        from src.titulos import certificados as cert

        ctrl = af.controles(lecturas or [], rut_vendedor)
        col = {"alta": "#b42318", "media": "#b54708", "ok": "#067647", "info": "#175cd3"}
        anti = "<ul class=al>" + "".join(f"<li><span class='niv' style='background:{col[n]}'>{'atención' if n == 'alta' else 'revisar' if n == 'media' else n}</span> {e(tx)}</li>" for n, tx in ctrl) + "</ul>"
        if lecturas:
            anti += cert.seccion_html(lecturas, cert.cruzar(lecturas, rid, t if t is not None else pl.DataFrame({"fecha_inscripcion": [], "monto_uf_norm": []})))
    else:
        anti = ("<p>Suba la copia de dominio vigente y el certificado de gravámenes, e ingrese el RUT del vendedor, para verificar que quien vende sea el dueño inscrito, "
                "la vigencia de los certificados y su código de verificación. Se procesan en memoria y no se guardan.</p>")

    # Trámites
    cbr = cbr_de(int(rid.split("-")[0]))
    filas_tr = "".join(
        f"<tr><td>☐ pedido<br>☐ recibido</td><td><b>{e(doc)}</b><br><span class=nota>{e(para)}</span></td><td>{e(org)}</td><td>{e(cbr if 'Conservador' in org and 'Conservador' in donde else donde)}</td></tr>"
        for _, org, doc, para, donde, _c in tramites(alertas, copro)
    )
    sem = "".join(f"<tr><td>{e(n)}</td><td><span class='niv' style='background:{ {'alerta': '#b42318', 'revisar': '#b54708', 'sin alertas': '#067647', 'no verificado': '#475467'}[s] }'>{e(s)}</span></td></tr>" for n, s, _ in dil.semaforo(alertas))
    cod, mz, pr = rid.split("-")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carpeta de la propiedad · rol {e(rid)}</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#eaecf0;--bg:#fff;--soft:#f9fafb}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:920px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.5rem;margin:.2em 0}} h2{{font-size:1.1rem;margin:1.8em 0 .5em;border-bottom:1px solid var(--rule);padding-bottom:4px}}
.eye{{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--rule);vertical-align:top}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:.9rem}} dt{{color:var(--ink2)}}
.niv{{display:inline-block;color:#fff;font-size:.7rem;text-transform:uppercase;padding:1px 6px;border-radius:4px;margin-right:4px;white-space:nowrap}}
ul.al li{{margin:.4em 0}} .nota{{font-size:.82rem;color:var(--ink2)}} .no-print{{margin:0 0 1em}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}} @media (max-width:700px){{.cols{{grid-template-columns:1fr}}}}
@media print{{.no-print{{display:none}} body{{max-width:none;padding:0;font-size:11pt}} h2{{break-after:avoid}} table,ul{{break-inside:auto}} tr{{break-inside:avoid}}
:root{{--ink:#000;--ink2:#444;--rule:#ccc;--bg:#fff}} .niv{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<p class="no-print nota"><a href="carpeta">← Otra propiedad</a> · Para guardar como PDF use Imprimir (Ctrl+P) → Guardar como PDF.</p>
<span class="eye">Carpeta de la propiedad · {hoy:%d-%m-%Y}{(' · preparado por ' + e(corredora)) if corredora else ''}</span>
<h1>Rol {e(f"{mz}-{pr}")} · {e(comuna)}</h1>
<p>{e(r.get('direccion') or '')}</p>
<div class=cols><div><h2>Resumen de riesgos</h2><table><tbody>{sem}</tbody></table></div>
<div><h2>Datos clave</h2><dl><dt>Rol SII</dt><dd>{e(rid)}</dd><dt>Avalúo fiscal</dt><dd>{pi.clp(r.get('avaluo_total'))}</dd>
<dt>Ubicación SII</dt><dd>{e(ter.ubicacion(r.get('cod_ubicacion'))[0])}</dd><dt>Conservador</dt><dd>{e(cbr)}</dd><dt>Fuente</dt><dd>Catastro {e(d['semestre'])}, serie {e(d['serie']).lower()}</dd></dl></div></div>
<h2>1. Identificación</h2>{ter.html_ficha(d, comuna).split('</h1>', 1)[1]}
<h2>2. Antifraude</h2>{anti}
<h2>3. Historia de transferencias</h2>{transf}
<h2>4. Valor</h2>{valor}
{dil.html_seccion(alertas).replace('<h2>Riesgos que el vendedor podría omitir</h2>', '<h2>5. Riesgos que el vendedor podría omitir</h2>').replace('<h2>Documentos que conviene exigir al vendedor</h2>', '<h2>6. Documentos que conviene exigir</h2>')}
<h2>7. Trámites por organismo</h2>
<table><thead><tr><th>Estado</th><th>Documento</th><th>Organismo</th><th>Dónde</th></tr></thead><tbody>{filas_tr}</tbody></table>
<p class="nota">Fuentes: detalle catastral del SII (2026-2S o 2022-1S), Formulario 2890, índices y modelos del proyecto. Es una herramienta de apoyo para el corredor: no reemplaza el estudio de títulos de un abogado ni una tasación. No es un documento del SII ni del Conservador. Los certificados y el RUT ingresados se procesaron en memoria y no se guardaron.</p>
</body></html>"""
