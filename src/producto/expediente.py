"""Expediente de revisión de avalúo por rol (para dueños): cuánto pagará en 2027 y si hay indicios de error técnico.

Herramienta PRIVADA: la salida va a privado/expedientes/ (en .gitignore) o se muestra en el servicio con clave.
No usa datos personales: catastro, F2890 y modelos del proyecto.

Contenido:
  1. Resumen: indicios fuertes de error técnico y ahorro anual estimado si se corrigen.
  2. Contribuciones 2027 en tres escenarios, con la cuota del 1S-2027 con alza gradual (src.producto.estimador2027).
  3. Lo que el SII tiene registrado: terreno y cada línea de construcción, con su valor según las tablas del SII.
  4. Indicios (src.producto.auditoria_rol). Solo se destacan las señales "fuertes" de terreno y edificio, que en
     el backtest 2022 anticiparon bajas del SII 4 a 5 veces más que la tasa base. Las de calidad y superficie
     se muestran como datos a verificar por el dueño. Las de nivel "revisar" de terreno y edificio no se muestran
     (en el backtest no predijeron correcciones).
  5. Comparables depurados (src.producto.comparables) y avalúo ÷ precio típico.
  6. Equidad del avalúo en la comuna: avalúo ÷ precio por quintil de precio (regresividad).
  7. Cómo revisar y reclamar, y lo que el expediente no cubre.

Uso:
  .venv/bin/python -m src.producto.expediente 13101-152-779
  .venv/bin/python -m src.producto.expediente --comuna "Santiago" 152-779
  .venv/bin/python -m src.producto.expediente --lote roles.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import html

import polars as pl

from src.etl.common import REF, ROOT
from src.features.avaluo_construccion import valorar_lineas
from src.producto import comparables as cp
from src.producto import estimador2027 as est
from src.producto.auditoria_rol import CAUSAL
from src.titulos import preinforme as pi

SALIDA = ROOT / "privado" / "expedientes"
FECHA_UF_AVALUO = dt.date(2026, 7, 1)  # avalúo en pesos del 2S-2026
MATERIAL = {"A": "acero", "B": "hormigón armado", "C": "albañilería (ladrillo)", "E": "madera", "F": "adobe", "G": "perfiles metálicos", "K": "prefabricado", "L": "madera laminada", "M": "metalcon", "W": "obra complementaria"}
CALIDAD = {"1": "superior", "2": "media superior", "3": "media", "4": "media inferior", "5": "inferior"}
COND = {"CI": "construcción interior", "AL": "altillo", "CA": "construcción abierta", "MS": "mansarda", "PZ": "posi-zócalo", "SB": "subterráneo"}
TEXTO = {
    "terreno_sobre_manzana": (
        "El valor de su terreno por m² es {d:.0%} más alto que el de las demás casas de su manzana",
        "El SII valora el suelo por área homogénea, así que dentro de una manzana el terreno por m² suele ser casi igual. "
        "Descontando sus construcciones (valoradas con las tablas del SII), su terreno resulta en {vr} por m², contra {vp} "
        "en la mediana de {n} casas de la manzana, y ninguna otra casa tiene un valor parecido. Puede haber un error en "
        "la superficie de terreno, en un coeficiente o en el cálculo.",
        "Pida el certificado de avalúo fiscal detallado y compare la superficie del terreno con su escritura o plano. "
        "Pregunte qué área homogénea y qué coeficientes se le aplicaron.",
    ),
    "avaluo_m2_sobre_edificio": (
        "Su avalúo por m² es {d:.0%} más alto que el de unidades iguales de su edificio",
        "Las unidades del mismo edificio, con la misma clase, calidad y año, casi siempre tienen el mismo avalúo por m² "
        "(la diferencia típica es menor que 1%). El suyo es {vr} por m², contra {vp} en la mediana de {n} unidades "
        "iguales, y ninguna otra tiene un valor parecido. Puede haber un error en la superficie, en la clasificación "
        "o en el prorrateo.",
        "Compare los m² de su certificado de avalúo detallado con los de su escritura y el plano de copropiedad. "
        "Pregunte a vecinos con unidades iguales cuánto es su avalúo.",
    ),
    "calidad_sobre_edificio": (
        "Su construcción está clasificada con mejor calidad que las demás de su edificio",
        "Su unidad figura con calidad {cr} y la mayoría de las {n} unidades de la misma clase y año en su edificio "
        "figura con calidad {cp}. Una calidad mejor tiene un valor por m² más alto en las tablas del SII.",
        "Verifique si su unidad tiene terminaciones distintas a las del resto. Si no las tiene, puede pedir que se "
        "corrija la clasificación.",
    ),
    "superficie_aumento": (
        "Su superficie construida registrada subió de {vp:.0f} m² a {vr:.0f} m² desde 2022",
        "El SII agregó o modificó líneas de construcción desde el catastro 2022-1S.",
        "Verifique que la ampliación exista y que los m² registrados coincidan con los reales (permiso de edificación, "
        "recepción final o una medición).",
    ),
}


def leer(cands: list[str]) -> dict | None:
    d = pi.leer(cands)
    if d is None:
        return None
    rid = d["rol_id"]
    cod, mz = (int(x) for x in rid.split("-")[:2])
    d["aud"] = pl.scan_parquet(pi.MARTS / "auditoria_roles_2026_2.parquet").filter(pl.col("rol_id") == rid).collect()
    d["lineas"] = pl.scan_parquet(pi.STAGING / "catastro" / "lineas_2026_2.parquet").filter(pl.col("rol_id") == rid).collect().sort("linea")
    mb = pl.scan_parquet(pi.STAGING / "map_barrio.parquet").filter((pl.col("cod_comuna") == cod) & (pl.col("manzana") == mz)).collect()
    d["barrio_id"] = mb["barrio_id"][0] if mb.height else None
    uf = pl.scan_parquet(pi.STAGING / "uf.parquet").filter(pl.col("fecha") == FECHA_UF_AVALUO).collect()
    d["uf_avaluo"] = float(uf["uf"][0]) if uf.height else None
    ambito = [x for x in (d.get("microbarrio_id"), d["barrio_id"]) if x]
    v = pl.scan_parquet(pi.MARTS / "fct_venta.parquet").filter(pl.col("barrio_id").is_in(ambito) | pl.col("microbarrio_id").is_in(ambito)).select(cp.COLS).collect() if ambito else None
    comp = d["comp"].row(0, named=True) if d["comp"].height else {}
    obj = {"rol_id": rid, "microbarrio_id": d.get("microbarrio_id"), "barrio_id": d["barrio_id"], "copropiedad": comp.get("copropiedad"), "sup_construida_total": comp.get("sup_construida_total")}
    d["comparables"], d["comparables_conteo"] = cp.seleccionar(v, obj) if v is not None else (pl.DataFrame(), {})
    hoy = dt.date.today()
    d["equidad"] = (
        pl.scan_parquet(pi.MARTS / "fct_venta.parquet")
        .filter((pl.col("cod_comuna") == cod) & (pl.col("anio") >= hoy.year - 3) & pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva") & (pl.col("destino_principal") == "H")
                & (pl.col("residuo_prop").is_null() | (pl.col("residuo_prop") >= cp.FUERA_MERCADO)))
        .select("monto_uf", "ratio_ia").collect()
    )
    return d


def equidad(v: pl.DataFrame) -> pl.DataFrame:
    """Avalúo ÷ precio mediano por quintil de precio (IAAO). Si baja con el precio, el avalúo es regresivo."""
    if v.height < 100:
        return pl.DataFrame()
    return (
        v.with_columns((1 / pl.col("ratio_ia")).alias("a_p"), (pl.col("monto_uf").rank("ordinal") * 5 / pl.len()).ceil().clip(1, 5).cast(pl.Int8).alias("q"))
        .group_by("q").agg(pl.len().alias("n"), pl.col("monto_uf").min().alias("desde"), pl.col("monto_uf").max().alias("hasta"), pl.col("a_p").median().alias("a_p"))
        .sort("q")
    )


def valorar(lineas: pl.DataFrame, exento_h: float | None) -> pl.DataFrame:
    if not lineas.height or not exento_h:
        return lineas
    fipc = 1.051 * exento_h / est.EXENTO_2022  # mismo factor que src.features.avaluo_construccion.factor_ipc("2026_2")
    return valorar_lineas(lineas, "2022", fipc)


def pct(x: float) -> str:
    return f"{x * 100:.0f}%".replace(".", ",")


def informe(d: dict) -> str:
    e = html.escape
    rid, cat = d["rol_id"], d["cat"]
    ult = cat.get("2026_2") or list(cat.values())[-1]
    cod, mz, pr = rid.split("-")
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";").filter(pl.col("cod_comuna") == int(cod))
    comuna = cuts["nombre_mapa"][0] if cuts.height else cod
    comp = d["comp"].row(0, named=True) if d["comp"].height else {}
    con = d["contrib"].row(0, named=True) if d["contrib"].height else {}
    r27 = d["r27"].row(0, named=True) if d["r27"].height else {}
    exento_h = con.get("exento_h_semestre")
    aud = d["aud"]
    fuertes = aud.filter((pl.col("nivel") == "fuerte") & pl.col("senal").is_in(["terreno_sobre_manzana", "avaluo_m2_sobre_edificio"]))
    verificar = aud.filter(pl.col("senal").is_in(["calidad_sobre_edificio", "superficie_aumento"]))
    ahorro = float(fuertes["ahorro_anual"].max() or 0) if fuertes.height else 0.0

    # 1. Resumen
    if fuertes.height:
        res = (f"<p class='caja fuerte'><b>Encontramos un indicio fuerte de posible error técnico en su avalúo.</b> Si se corrige, su contribución bajaría "
               f"del orden de <b>{pi.clp(ahorro)} al año</b> con las tasas actuales. Revise la sección «Indicios» y verifique los datos con su certificado de avalúo detallado antes de reclamar.</p>")
    elif verificar.height:
        res = "<p class='caja'>No encontramos indicios fuertes de error, pero hay <b>datos que conviene verificar</b> (ver «Indicios»).</p>"
    else:
        res = "<p class='caja'>No encontramos indicios de error técnico con los datos disponibles. Igual conviene revisar que la superficie y las construcciones registradas coincidan con la realidad (sección 3).</p>"

    # 2. 2027
    if r27 and exento_h:
        x = est.estimar(r27, exento_h)
        filas = "".join(
            f"<tr><td>{e(s['nombre'])}</td><td class=n>{pi.clp(s['avaluo'])}</td><td class=n>{pi.clp(s['anual'])}</td><td class=n>{'+' if s['cambio_anual'] >= 0 else '−'}{pi.clp(abs(s['cambio_anual']))}</td>"
            f"<td class=n>{pi.clp(s['cuota_trimestral_1s'])}{' *' if s['con_alza_gradual'] else ''}</td></tr>"
            for s in x["escenarios"].values()
        )
        t27 = (f"<p>Hoy, según la fórmula del SII, su contribución es de <b>{pi.clp(x['actual_anual_teo'])} al año</b> (el cobro registrado en el catastro es de {pi.clp((ult.get('contrib_semestral') or 0) * 2)} al año: incluye el aseo municipal y, si los tiene, descuenta beneficios).</p>"
               f"<table><thead><tr><th>Escenario del reavalúo</th><th class=n>Avalúo 2027</th><th class=n>Contribución anual</th><th class=n>Cambio anual</th><th class=n>Cuota trimestral 1S-2027</th></tr></thead><tbody>{filas}</tbody></table>"
               "<p class=nota>* Con alza gradual: en el primer semestre la cuota sube como máximo 25%. Montos en pesos del 2S-2026, sin aseo. El escenario lo decide el SII; se actualizará cuando publique los valores de 2027.</p>")
        if con.get("rebaja_obs") in ("100%", "50%"):
            t27 += "<p class=nota>Su cobro actual es la mitad o menos que el de la fórmula: parece tener un beneficio (por ejemplo, de adulto mayor). La estimación no lo incluye; verifique sus requisitos y el tope de avalúo para 2027.</p>"
    else:
        t27 = "<p>Sin estimación para este rol (solo se calcula para los roles del modelo del Gran Santiago).</p>"

    # 3. Datos registrados
    lv = valorar(d["lineas"], exento_h)
    if lv.height and "avaluo_linea" in lv.columns:
        filas_l = "".join(
            f"<tr><td>{r['linea']}</td><td>{e(MATERIAL.get(str(r['material']).strip(), str(r['material'])))}</td><td>{e(CALIDAD.get(str(r['calidad'] or '').strip(), '—'))}</td>"
            f"<td class=n>{r['anio_construccion'] or '—'}</td><td class=n>{r['sup_construida']}</td><td>{e(COND.get(r['condicion_especial'] or '', '—'))}</td><td class=n>{pi.clp(r['avaluo_linea'])}</td></tr>"
            for r in lv.iter_rows(named=True)
        )
        tot = float(lv["avaluo_linea"].sum() or 0)
        terreno = (ult.get("avaluo_total") or 0) - tot
        lineas_html = (f"<table><thead><tr><th>Línea</th><th>Material</th><th>Calidad</th><th class=n>Año</th><th class=n>m²</th><th>Condición</th><th class=n>Valor según tablas</th></tr></thead><tbody>{filas_l}</tbody></table>"
                       f"<p class=nota>Construcciones según las tablas del SII (Res. 143/2021, con depreciación y factor comunal): {pi.clp(tot)}. Terreno implícito (avalúo − construcciones): {pi.clp(terreno)}"
                       + (f", {pi.clp(terreno / ult['sup_terreno_m2'])} por m²." if ult.get("sup_terreno_m2") else ".") + "</p>")
    else:
        lineas_html = "<p>Sin líneas de construcción registradas.</p>"

    # 4. Indicios
    items = []
    for r in pl.concat([fuertes, verificar]).iter_rows(named=True) if (fuertes.height or verificar.height) else []:
        tit, expl, qhacer = TEXTO[r["senal"]]
        fmt = {"d": r["desvio"] or 0, "n": r["n_pares"], "vr": pi.clp(r["valor_rol"]), "vp": pi.clp(r["valor_pares"]),
               "cr": CALIDAD.get(str(int(r["valor_rol"] or 0)), "?"), "cp": CALIDAD.get(str(int(r["valor_pares"] or 0)), "?")}
        if r["senal"] == "superficie_aumento":
            fmt |= {"vr": r["valor_rol"], "vp": r["valor_pares"]}
        nivel = "fuerte" if r["senal"] in ("terreno_sobre_manzana", "avaluo_m2_sobre_edificio") else "verificar"
        ah = f" Ahorro estimado si se corrige: <b>{pi.clp(r['ahorro_anual'])} al año</b>." if (r.get("ahorro_anual") or 0) > 0 else ""
        items.append(f"<li><span class='niv {nivel}'>{'indicio fuerte' if nivel == 'fuerte' else 'verificar'}</span> <b>{e(tit.format(**fmt))}.</b> {e(expl.format(**fmt))}{ah}"
                     f"<br><span class=nota>Causal posible: {e(CAUSAL[r['senal']])}. Qué hacer: {e(qhacer)}</span></li>")
    indicios = "<ul class=al>" + "".join(items) + "</ul>" if items else "<p>Sin indicios con los datos disponibles.</p>"

    # 5. Comparables
    c, cc = d["comparables"], d["comparables_conteo"]
    av_uf = (ult.get("avaluo_total") or 0) / d["uf_avaluo"] if d.get("uf_avaluo") else None
    rs = cp.resumen(c, av_uf, comp.get("sup_construida_total")) if c.height else {"n": 0}
    if c.height:
        filas_c = "".join(
            f"<tr><td>{r['fecha_escritura']:%m-%Y}</td><td>{e(r['rol_principal'])}</td><td class=n>{r['sup_construida_total'] or '—'}</td><td class=n>{pi.uf(r['monto_uf'])}</td><td class=n>{pi.dec(r['uf_m2']) if r['uf_m2'] else '—'}</td></tr>"
            for r in c.iter_rows(named=True)
        )
        txt_c = ""
        if rs.get("avaluo_sobre_precio"):
            ap = rs["avaluo_sobre_precio"]
            txt_c = (f"<p>Su avalúo ({pi.uf(av_uf)}) equivale al <b>{pct(ap)}</b> del precio típico de viviendas parecidas de su {e(cc.get('ambito', 'zona'))} ({pi.uf(rs['precio_tipico_uf'])})."
                     + (" <b>Su avalúo supera el precio de mercado típico</b>: no es por sí solo una causal de reclamo, pero es un antecedente fuerte para pedir una revisión." if ap > 1 else
                        " Es normal que el avalúo fiscal sea menor que el precio de mercado.") + "</p>")
        descartes = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in cc.items() if k not in ("entrada", "salida", "ambito") and v)
        comp_html = (txt_c + f"<table><thead><tr><th>Fecha</th><th>Rol</th><th class=n>m²</th><th class=n>Precio</th><th class=n>UF/m²</th></tr></thead><tbody>{filas_c}</tbody></table>"
                     f"<p class=nota>Ventas de los últimos 3 años del mismo tipo y tamaño parecido (0,7× a 1,4× los m²). Se descartaron ({e(descartes)}). Precios en UF a la fecha de la escritura (F2890 del SII).</p>")
    else:
        comp_html = "<p>No hay suficientes ventas comparables recientes en su microbarrio o barrio.</p>"

    # 6. Equidad
    eq = equidad(d["equidad"])
    if eq.height:
        filas_e = "".join(f"<tr><td>{r['q']}</td><td class=n>{pi.uf(r['desde'])} – {pi.uf(r['hasta'])}</td><td class=n>{pct(r['a_p'])}</td><td class=n>{r['n']}</td></tr>" for r in eq.iter_rows(named=True))
        reg = float(eq["a_p"][0]) / float(eq["a_p"][-1])
        eq_html = (f"<table><thead><tr><th>Quintil de precio</th><th class=n>Precios</th><th class=n>Avalúo ÷ precio (mediana)</th><th class=n>Ventas</th></tr></thead><tbody>{filas_e}</tbody></table>"
                   f"<p class=nota>Ventas habitacionales de {e(comuna)} de los últimos 3 años, sin obra nueva ni ventas fuera de mercado. "
                   + (f"Las viviendas más baratas tienen un avalúo {pct(reg - 1)} más alto respecto de su precio que las más caras: el avalúo es regresivo en su comuna." if reg > 1.05 else "No se ve una diferencia grande entre tramos de precio.")
                   + " El estándar internacional (IAAO) recomienda que esta razón sea pareja entre tramos.</p>")
    else:
        eq_html = "<p>Sin ventas suficientes en la comuna.</p>"

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisión de avalúo · rol {e(rid)}</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#eaecf0;--bg:#fff;--soft:#f9fafb;--alto:#b42318;--ver:#175cd3}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26;--alto:#f97066;--ver:#84adff}}}}
body{{font:15px/1.55 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:920px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.5rem;margin:.2em 0}} h2{{font-size:1.05rem;margin:1.8em 0 .5em;border-bottom:1px solid var(--rule);padding-bottom:4px}}
.eye{{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--rule);vertical-align:top}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.caja{{background:var(--soft);border:1px solid var(--rule);border-radius:8px;padding:10px 14px}} .caja.fuerte{{border-left:4px solid var(--alto)}}
.niv{{display:inline-block;color:#fff;font-size:.7rem;text-transform:uppercase;padding:1px 6px;border-radius:4px;margin-right:4px}}
.niv.fuerte{{background:var(--alto)}} .niv.verificar{{background:var(--ver)}}
ul.al li{{margin:.6em 0}} .nota{{font-size:.82rem;color:var(--ink2)}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:.9rem}} dt{{color:var(--ink2)}}
ol li{{margin:.4em 0}} @media print{{a[href]:after{{content:""}}}}
</style></head><body>
<span class="eye">Revisión de avalúo y contribuciones · uso privado · {dt.date.today():%d-%m-%Y}</span>
<h1>Rol {e(f"{mz}-{pr}")} · {e(comuna)}</h1>
{res}
<h2>1. ¿Cuánto pagará en 2027?</h2>{t27}
<h2>2. Lo que el SII tiene registrado (catastro 2026-2S)</h2>
<dl><dt>Dirección</dt><dd>{e(ult.get('direccion') or '—')}</dd>
<dt>Destino</dt><dd>{e(pi.DESTINOS.get(ult.get('destino'), ult.get('destino') or '—'))}</dd>
<dt>Avalúo fiscal</dt><dd>{pi.clp(ult.get('avaluo_total'))} (exento {pi.clp(ult.get('avaluo_exento'))})</dd>
<dt>Superficie de terreno</dt><dd>{ult.get('sup_terreno_m2') or '—'} m²{' (copropiedad: el terreno es un derecho en el terreno común)' if comp.get('copropiedad') else ''}</dd>
<dt>Superficie construida</dt><dd>{comp.get('sup_construida_total') or '—'} m²</dd></dl>
{lineas_html}
<h2>3. Indicios de error técnico</h2>{indicios}
<p class=nota>Cómo se detectan: se compara su avalúo con el que resulta de aplicar las tablas del SII a sus propios datos y con viviendas iguales de su manzana o edificio. En una prueba con el catastro 2022, el SII bajó después el avalúo del 1,4% al 1,7% de los roles con indicio fuerte, entre 4 y 5 veces más que al resto (0,3%). Es una probabilidad baja en términos absolutos, porque pocas personas reclaman.</p>
<h2>4. Ventas comparables</h2>{comp_html}
<h2>5. Equidad del avalúo en su comuna</h2>{eq_html}
<h2>6. Cómo revisar y reclamar</h2>
<ol><li><b>Pida su certificado de avalúo fiscal detallado</b> en sii.cl (gratis). Compare los m² de terreno y de cada construcción, el material, la calidad y el año con su escritura, planos, permiso de edificación o recepción final.</li>
<li><b>Si un dato está mal</b> (superficie, material, calidad, año), pida la corrección al SII con los respaldos. Se puede hacer en cualquier momento, no solo en un reavalúo.</li>
<li><b>Si el reavalúo 2027 le asigna un avalúo con errores</b>, puede pedir una revisión administrativa al SII o presentar un reclamo ante el Tribunal Tributario y Aduanero. Las causales son técnicas (art. 149 del Código Tributario): superficie errónea, mala aplicación de las tablas de clasificación o de los coeficientes, y errores de transcripción, copia o cálculo. Los plazos se cuentan desde el término de la exhibición de los nuevos avalúos.</li>
<li><b>Verifique los plazos y el procedimiento vigentes</b> con el SII o con un abogado tributario antes de presentar: la Ley 21.713 cambió el procedimiento de reclamo.</li></ol>
<h2>Lo que este expediente no cubre</h2>
<ul><li>La visita a la propiedad: los datos reales pueden diferir del catastro en ambos sentidos.</li>
<li>El prorrateo de los bienes comunes en copropiedad y los coeficientes de terreno por forma, tamaño o ubicación.</li>
<li>Los beneficios personales (adulto mayor, DFL2) y la deuda de contribuciones (tgr.cl).</li>
<li>El avalúo oficial 2027: se conocerá cuando el SII publique los nuevos valores.</li></ul>
<p class="nota">Fuentes: detalle catastral del SII 2022-1S y 2026-2S; Formulario 2890 (enajenaciones); tablas de valores de construcción (Res. SII 143/2021); modelos del proyecto. No contiene datos personales. Es un insumo para revisar su avalúo y no constituye asesoría legal ni tributaria; no es un documento del SII.</p>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rol", nargs="?")
    ap.add_argument("--comuna")
    ap.add_argument("--lote", help="archivo con un rol por línea (cod-manzana-predio)")
    a = ap.parse_args()
    roles = [x.strip() for x in open(a.lote, encoding="utf8") if x.strip()] if a.lote else [a.rol]
    if not roles or roles == [None]:
        ap.error("falta el rol")
    SALIDA.mkdir(parents=True, exist_ok=True)
    ok = no = 0
    for r in roles:
        d = leer(pi.resolver(r, a.comuna))
        if d is None:
            print(f"[expediente] {r}: no está en el catastro del Gran Santiago")
            no += 1
            continue
        out = SALIDA / f"{d['rol_id']}.html"
        out.write_text(informe(d), encoding="utf8")
        print(f"[expediente] {r} → {out.relative_to(ROOT)} ({d['aud'].height} señales, {d['comparables'].height} comparables)")
        ok += 1
    print(f"[expediente] {ok} generados, {no} no encontrados")


if __name__ == "__main__":
    main()
