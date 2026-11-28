"""Pre-informe de títulos por rol: prepara (no reemplaza) el estudio de títulos de un abogado.

Herramienta PRIVADA. Se corre en local; la salida va a privado/preinformes/ (en .gitignore) y nunca se publica.
No usa ni guarda datos de personas: el catastro y el F2890 del SII no traen nombres ni RUT. Los nombres de dueños
solo aparecen en los certificados del Conservador, que el abogado pide por su cuenta.

Bloques:
  1. Identificación: dirección, destino, superficie, avalúo y contribución 2026-2S, rol matriz y roles de bien común.
  2. Historia del rol en el catastro (2021-2S, 2022-1S, 2026-2S): alta, cambio de destino, saltos de avalúo.
  3. Cadena de transferencias del F2890 (fechas de escritura e inscripción, monto en UF): cuántas inscripciones
     pedir al Conservador y de qué años. Se descartan fechas imposibles (año < 1950 o futuro).
  4. Alertas: precio < 50% de lo típico del microbarrio (indicio de lesión enorme, art. 1889 CC, o venta entre
     relacionados), inscripción antes de la escritura, venta en bloque, rol nuevo, cambio de destino.
  5. Contribuciones 2027 estimadas (3 escenarios) y lista de verificación de lo que este informe NO cubre.

Uso:
  .venv/bin/python -m src.titulos.preinforme 13101-152-779
  .venv/bin/python -m src.titulos.preinforme --comuna "San Joaquín" 5433-12
  .venv/bin/python -m src.titulos.preinforme --lote roles.txt     (un rol por línea)
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import sys
import unicodedata
from pathlib import Path

import polars as pl

from src.etl.common import MARTS, REF, ROOT, STAGING

# En el servicio privado los datos vienen empaquetados (src.titulos.empaquetar) en otra carpeta
if os.environ.get("PREINFORME_DATOS"):
    STAGING = Path(os.environ["PREINFORME_DATOS"]) / "staging"
    MARTS = Path(os.environ["PREINFORME_DATOS"]) / "marts"

SALIDA = ROOT / "privado" / "preinformes"
SEMESTRES = ("2021_2", "2022_1", "2026_2")
DESTINOS = {"H": "Habitacional", "C": "Comercio", "O": "Oficina", "L": "Bodega y estacionamiento", "Z": "Estacionamiento", "I": "Industria", "E": "Educación", "S": "Salud", "W": "Sitio eriazo", "A": "Agrícola", "G": "Hotel/motel", "D": "Deporte", "Q": "Culto", "P": "Administración pública", "T": "Transporte", "V": "Otros", "M": "Minería", "F": "Forestal", "B": "Agroindustrial"}
ESC = {"S0": "Leve", "S2": "Moderado", "S1": "Fuerte"}
UBICACION = {"U": "Urbano (código U)", "R": "Rural (código R)", "E": "Probable extensión urbana (código E, por confirmar)"}
ANIO_MIN = 1950


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


def resolver(rol: str, comuna: str | None) -> list[str]:
    """Devuelve rol_id candidatos ('cod-manzana-predio'). Con --comuna, prueba todos los códigos SII de esa comuna."""
    rol = rol.strip()
    if comuna is None:
        if not re.fullmatch(r"\d{4,5}-\d+-\d+", rol):
            sys.exit(f"Rol '{rol}': usa cod_comuna-manzana-predio (ej. 13101-152-779) o --comuna \"Nombre\" manzana-predio")
        c, m, p = rol.split("-")
        return [f"{int(c)}-{int(m)}-{int(p)}"]
    if not re.fullmatch(r"\d+-\d+", rol):
        sys.exit(f"Con --comuna el rol va como manzana-predio (ej. 152-779), no '{rol}'")
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";")
    cods = [c for c, n in zip(cuts["cod_comuna"], cuts["nombre_mapa"]) if sin_tildes(n) == sin_tildes(comuna)]
    if not cods:
        sys.exit(f"Comuna '{comuna}' no está en el Gran Santiago del proyecto")
    m, p = rol.split("-")
    return [f"{c}-{int(m)}-{int(p)}" for c in cods]


def leer(rid_cands: list[str]) -> dict | None:
    # Con varios candidatos (Santiago tiene 3 códigos SII) se elige UNO, el del semestre más reciente donde aparezca,
    # para no mezclar datos de predios distintos entre semestres.
    rid = None
    for s in reversed(SEMESTRES):
        x = pl.scan_parquet(STAGING / "catastro" / f"roles_{s}.parquet").filter(pl.col("rol_id").is_in(rid_cands)).select("rol_id").collect()
        if x.height:
            rid = sorted(x["rol_id"], key=rid_cands.index)[0]
            break
    if rid is None:
        return None
    cat = {}
    for s in SEMESTRES:
        x = pl.scan_parquet(STAGING / "catastro" / f"roles_{s}.parquet").filter(pl.col("rol_id") == rid).collect()
        if x.height:
            cat[s] = x.row(0, named=True)
    d = {"rol_id": rid, "cat": cat}
    d["comp"] = pl.scan_parquet(STAGING / "avaluo_componentes_2026_2.parquet").filter(pl.col("rol_id") == rid).collect()
    d["contrib"] = pl.scan_parquet(STAGING / "contribucion_2026_2.parquet").filter(pl.col("rol_id") == rid).collect()
    d["r27"] = leer_r27(rid, cat.get("2026_2"))
    d["linaje"] = pl.scan_parquet(STAGING / "map_rol_linaje.parquet").filter(pl.col("rol_id") == rid).collect()
    hoy = dt.date.today()
    t = pl.scan_parquet(STAGING / "f2890.parquet").filter(pl.col("rol_id") == rid).collect()
    valida = pl.col("fecha_escritura").dt.year().is_between(ANIO_MIN, hoy.year) & (pl.col("fecha_escritura") <= hoy)
    d["n_fechas_invalidas"] = t.filter(~valida).height
    t = t.filter(valida)
    ft = pl.scan_parquet(STAGING / "fct_transferencia.parquet").filter(pl.col("rol_id") == rid).select("rol_id", "fecha_escritura", "n_roles_grupo", "primera_venta_obra_nueva").collect().unique(["fecha_escritura"])
    d["transf"] = t.join(ft, on=["rol_id", "fecha_escritura"], how="left").sort("fecha_escritura")
    # Ventas del rol en el mart y lo típico de su microbarrio (precio ÷ avalúo, UF/m²) en ventas comparables
    v = pl.scan_parquet(MARTS / "fct_venta.parquet").filter(pl.col("rol_principal") == rid).collect()
    d["ventas"] = v
    mb = pl.scan_parquet(STAGING / "map_barrio.parquet").filter((pl.col("cod_comuna") == int(rid.split("-")[0])) & (pl.col("manzana") == int(rid.split("-")[1]))).collect()
    d["microbarrio_id"] = mb["microbarrio_id"][0] if mb.height else None
    if d["microbarrio_id"]:
        ref = (pl.scan_parquet(MARTS / "fct_venta.parquet")
               .filter((pl.col("microbarrio_id") == d["microbarrio_id"]) & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
               .select("anio", "ratio_ia", "uf_m2").collect())
        d["ref_micro"] = ref
    return d


def leer_r27(rid: str, ult: dict | None) -> pl.DataFrame:
    """Fila del modelo 2027. En el paquete del servicio (src.titulos.empaquetar.compactar_reavaluo) el avalúo 2027
    viene como factor por comuna y los roles siempre exentos no vienen: se reconstruyen aquí."""
    r = pl.scan_parquet(MARTS / "reavaluo2027_roles.parquet").filter(pl.col("rol_id") == rid).collect()
    fac_f = MARTS / "reavaluo2027_factores.parquet"
    if not fac_f.exists() or ult is None:
        return r
    fac = pl.read_parquet(fac_f).filter(pl.col("cod_comuna") == ult["cod_comuna"])
    if not fac.height:
        return r
    esc = ("S0", "S2", "S1")
    if not r.height:
        r = pl.DataFrame({"rol_id": [rid], **{c: [0] for c in ("contrib_teo", "contrib_27_S2", "d_27_S0", "d_27_S1", "sob_teo", "sob_27_S0", "sob_27_S2", "sob_27_S1")}})
    r = r.with_columns(
        (pl.col("contrib_teo") + pl.col("d_27_S0")).alias("contrib_27_S0"),
        (pl.col("contrib_27_S2") + pl.col("d_27_S1")).alias("contrib_27_S1"),
        (pl.col("contrib_teo") - pl.col("sob_teo")).alias("contrib_neta_teo"),
    ).with_columns([(pl.col(f"contrib_27_{e}") - pl.col(f"sob_27_{e}")).alias(f"neta_27_{e}") for e in esc])
    return r.with_columns([pl.lit(round(ult["avaluo_total"] * fac[f"factor_{e}"][0])).alias(f"avaluo_27_{e}") for e in esc])


def tipico(ref: pl.DataFrame | None, anio: int, col: str) -> tuple[float | None, int]:
    if ref is None:
        return None, 0
    x = ref.filter(pl.col("anio").is_between(anio - 1, anio + 1) & pl.col(col).is_not_null() & (pl.col(col) > 0))[col]
    return (float(x.median()), x.len()) if x.len() >= 30 else (None, x.len())


def dec(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def clp(x) -> str:
    return "—" if x is None else "$" + f"{x:,.0f}".replace(",", ".")


def uf(x) -> str:
    return "—" if x is None else f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " UF"


def informe(d: dict, extra: str = "") -> str:
    rid, cat = d["rol_id"], d["cat"]
    ult = cat.get("2026_2") or list(cat.values())[-1]
    cod, mz, pr = rid.split("-")
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";")
    fila_c = cuts.filter(pl.col("cod_comuna") == int(cod))
    comuna = fila_c["nombre_mapa"][0] if fila_c.height else cod
    cut = int(fila_c["cut"][0]) if fila_c.height else None
    cbr = pl.read_csv(REF / "cbr_por_comuna.csv", separator=";").filter(pl.col("cut") == cut)
    cbr_txt = (f"CBR de {cbr['cbr_probable'][0]} ({'verificado' if cbr['estado'][0] == 'verificado' else 'probable, por verificar'})") if cbr.height else "—"
    alertas: list[tuple[str, str]] = []  # (nivel, texto)
    # Historia en el catastro
    hist = []
    for s in SEMESTRES:
        r = cat.get(s)
        hist.append((s.replace("_", "-") + "S", r["destino"] if r else None, r["avaluo_total"] if r else None, r["direccion"] if r else None))
    if "2021_2" not in cat and "2022_1" in cat:
        alertas.append(("media", "Rol nuevo en 2022-1S (no existía en 2021-2S): pedir también la inscripción del predio matriz y revisar loteo, subdivisión o ley de copropiedad."))
    elif "2021_2" not in cat and "2022_1" not in cat:
        alertas.append(("media", "Rol nuevo después de 2022-1S: pedir también la inscripción del predio matriz y revisar loteo, subdivisión o ley de copropiedad, y la recepción final municipal."))
    if "2026_2" not in cat:
        alertas.append(("alta", "El rol ya no figura en el catastro 2026-2S (dado de baja, fusionado o subdividido): verificar su rol vigente en el SII antes de pedir certificados."))
    dest = [h[1] for h in hist if h[1]]
    if len(set(dest)) > 1:
        alertas.append(("media", f"Cambio de destino en el catastro ({' → '.join(dict.fromkeys(dest))}): revisar permisos de edificación y recepción municipal."))
    pares = [(a, b) for a, b in zip(hist, hist[1:]) if a[2] and b[2]]
    for a, b in pares:
        if b[2] / a[2] > 1.8:
            alertas.append(("baja", f"Salto de avalúo de {a[0]} a {b[0]} (×{b[2] / a[2]:.1f}): puede reflejar ampliación, cambio de destino o reavalúo; conviene cotejar con la recepción municipal."))
    padre = (ult.get("padre_comuna"), ult.get("padre_manzana"), ult.get("padre_predio"))
    padre_txt = f"{padre[0]}-{padre[1]}-{padre[2]}" if all(padre) and padre[2] else "—"
    bcs = [f"{ult[f'bc{i}_comuna']}-{ult[f'bc{i}_manzana']}-{ult[f'bc{i}_predio']}" for i in (1, 2) if ult.get(f"bc{i}_predio")]
    if bcs:
        alertas.append(("info", f"Copropiedad: revisar el reglamento de copropiedad y los roles de bien común {', '.join(bcs)}."))
    # Transferencias
    t = d["transf"]
    hoy = dt.date.today()
    filas_t = []
    for r in t.iter_rows(named=True):
        anio = r["fecha_escritura"].year
        ratio_tip, n_ref = tipico(d.get("ref_micro"), anio, "ratio_ia")
        v = d["ventas"].filter(pl.col("fecha_escritura") == r["fecha_escritura"])
        ratio = v["ratio_ia"][0] if v.height else None
        obs = []
        if r.get("primera_venta_obra_nueva"):
            obs.append("primera venta de obra nueva")
        if (r.get("n_roles_grupo") or 1) > 1:
            obs.append(f"venta en bloque ({r['n_roles_grupo']} roles)")
            alertas.append(("info", f"Escritura de {r['fecha_escritura']:%d-%m-%Y} incluye {r['n_roles_grupo']} roles: verificar que la inscripción cubra todos (bodega, estacionamiento)."))
        if r.get("flag_inscripcion_antes_escritura"):
            obs.append("inscripción con fecha anterior a la escritura")
            alertas.append(("media", f"Transferencia de {r['fecha_escritura']:%d-%m-%Y}: la fecha de inscripción es anterior a la de escritura en el F2890. Puede ser un error de digitación; confirmar con la inscripción."))
        if ratio is not None and ratio_tip and ratio < 0.5 * ratio_tip:
            obs.append("precio muy bajo")
            alertas.append(("alta", f"Venta de {r['fecha_escritura']:%d-%m-%Y}: precio ÷ avalúo = {dec(ratio)}, menos de la mitad de lo típico en su microbarrio ({dec(ratio_tip)}, {n_ref} ventas). Puede ser la venta de una cuota o de derechos (herencias), una venta entre relacionados o un indicio de lesión enorme (art. 1889 CC): revisar el título."))
        filas_t.append((r["fecha_escritura"], r["fecha_inscripcion"], r["monto_uf_norm"], ratio, ratio_tip, ", ".join(obs)))
    hace10 = hoy.replace(year=hoy.year - 10)
    n10 = sum(1 for f in filas_t if f[0] >= hace10)
    ultima_previa = max((f for f in filas_t if f[0] < hace10), key=lambda f: f[0], default=None)
    # Contribuciones
    con = d["contrib"].row(0, named=True) if d["contrib"].height else {}
    r27 = d["r27"].row(0, named=True) if d["r27"].height else {}
    comp = d["comp"].row(0, named=True) if d["comp"].height else {}
    if con.get("exencion_especial"):
        alertas.append(("info", "Tiene una exención o rebaja especial de contribuciones: verificar si se mantiene tras la venta (algunas son personales, p. ej. adulto mayor)."))

    e = html.escape
    nivel_css = {"alta": "#b42318", "media": "#b54708", "baja": "#475467", "info": "#175cd3"}
    orden = {"alta": 0, "media": 1, "baja": 2, "info": 3}
    alertas = sorted(dict.fromkeys(alertas), key=lambda a: orden[a[0]])
    li_alertas = "".join(f'<li><span class="niv" style="background:{nivel_css[n]}">{n}</span> {e(x)}</li>' for n, x in alertas) or "<li>Sin alertas con los datos disponibles.</li>"
    filas_hist = "".join(f"<tr><td>{s}</td><td>{e(DESTINOS.get(dd, dd or '—'))}</td><td class=n>{clp(a)}</td><td>{e(dir_ or '—')}</td></tr>" for s, dd, a, dir_ in hist)
    filas_tr = "".join(
        f"<tr{' class=viejo' if f[0] < hace10 else ''}><td>{f[0]:%d-%m-%Y}</td><td>{f[1]:%d-%m-%Y}</td><td class=n>{uf(f[2])}</td><td class=n>{'—' if f[3] is None else dec(f[3])}</td><td class=n>{'—' if f[4] is None else dec(f[4])}</td><td>{e(f[5])}</td></tr>"
        if f[1] else f"<tr><td>{f[0]:%d-%m-%Y}</td><td>—</td><td class=n>{uf(f[2])}</td><td class=n>—</td><td class=n>—</td><td>{e(f[5])}</td></tr>"
        for f in reversed(filas_t)) or '<tr><td colspan=6>Sin transferencias registradas en el F2890 para este rol.</td></tr>'
    filas_27 = "".join(f"<tr><td>{ESC[k]}</td><td class=n>{clp(r27.get(f'avaluo_27_{k}'))}</td><td class=n>{clp((r27.get(f'contrib_27_{k}') or 0) * 2) if r27 else '—'}</td></tr>" for k in ("S0", "S2", "S1")) if r27 else "<tr><td colspan=3>Sin estimación (solo se calcula para roles habitacionales y comerciales del modelo).</td></tr>"
    guia = (f"Pedir al {cbr_txt.split(' (')[0]}: <b>copia de inscripción de dominio con vigencia</b>, <b>certificado de hipotecas, gravámenes, interdicciones y prohibiciones</b> (30 años si es para un banco) y "
            f"las <b>{n10} inscripción(es)</b> de los últimos 10 años" + (f", más la inscripción anterior a ese plazo (venta del {ultima_previa[0]:%d-%m-%Y}), que es el título que completa los 10 años." if ultima_previa else "."))
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-informe de títulos · rol {e(rid)}</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#eaecf0;--bg:#fff;--soft:#f9fafb}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:900px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.5rem;margin:.2em 0}} h2{{font-size:1.05rem;margin:1.6em 0 .4em;border-bottom:1px solid var(--rule);padding-bottom:4px}}
.eye{{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--rule);vertical-align:top}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}} tr.viejo td{{color:var(--ink2)}}
.niv{{display:inline-block;color:#fff;font-size:.7rem;text-transform:uppercase;padding:1px 6px;border-radius:4px;margin-right:4px}}
ul.al li{{margin:.35em 0}} .caja{{background:var(--soft);border:1px solid var(--rule);border-radius:8px;padding:10px 14px}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:.9rem}} dt{{color:var(--ink2)}}
.pie{{font-size:.8rem;color:var(--ink2);margin-top:2em}}
</style></head><body>
<span class="eye">Pre-informe de títulos · uso privado · {dt.date.today():%d-%m-%Y}</span>
<h1>Rol {e(f"{mz}-{pr}")} · {e(comuna)}</h1>
<p class="caja">{guia}</p>
<h2>Alertas</h2><ul class="al">{li_alertas}</ul>
<h2>Identificación (catastro SII 2026-2S)</h2>
<dl><dt>Rol SII</dt><dd>{e(rid)} (código de comuna SII {e(cod)})</dd>
<dt>Dirección</dt><dd>{e(ult.get('direccion') or '—')}</dd>
<dt>Destino</dt><dd>{e(DESTINOS.get(ult.get('destino'), ult.get('destino') or '—'))}</dd>
<dt>Ubicación según el SII</dt><dd>{e(UBICACION.get(ult.get('cod_ubicacion') or '', '—'))}</dd>
<dt>Superficie terreno</dt><dd>{ult.get('sup_terreno_m2') or '—'} m²</dd>
<dt>Superficie construida</dt><dd>{comp.get('sup_construida_total') or '—'} m² · año de construcción {comp.get('anio_construccion_max') or '—'} · calidad {e(str(comp.get('clase_calidad_principal') or '—'))}</dd>
<dt>Avalúo fiscal</dt><dd>{clp(ult.get('avaluo_total'))} (exento {clp(ult.get('avaluo_exento'))})</dd>
<dt>Contribución semestral</dt><dd>{clp(ult.get('contrib_semestral'))}</dd>
<dt>Rol matriz (padre)</dt><dd>{e(padre_txt)}</dd>
<dt>Roles de bien común</dt><dd>{e(', '.join(bcs) or '—')}</dd>
<dt>Microbarrio</dt><dd>{e(d.get('microbarrio_id') or '—')}</dd>
<dt>Conservador</dt><dd>{e(cbr_txt)}</dd></dl>
<h2>Historia en el catastro</h2>
<table><thead><tr><th>Semestre</th><th>Destino</th><th class=n>Avalúo</th><th>Dirección</th></tr></thead><tbody>{filas_hist}</tbody></table>
<h2>Cadena de transferencias (F2890 del SII)</h2>
<p style="font-size:.85rem;color:var(--ink2)">Cada fila es una enajenación informada por notarios y conservadores. En gris, las de más de 10 años. «Precio ÷ avalúo» compara el precio con el avalúo de referencia; «típico» es la mediana de su microbarrio en ±1 año (mín. 30 ventas).{f" Se omitieron {d['n_fechas_invalidas']} registro(s) con fecha imposible." if d['n_fechas_invalidas'] else ''}</p>
<table><thead><tr><th>Escritura</th><th>Inscripción</th><th class=n>Monto</th><th class=n>Precio ÷ avalúo</th><th class=n>Típico</th><th>Observaciones</th></tr></thead><tbody>{filas_tr}</tbody></table>
<h2>Contribuciones 2027 estimadas (reavalúo no oficial)</h2>
<table><thead><tr><th>Escenario</th><th class=n>Avalúo 2027</th><th class=n>Contribución anual</th></tr></thead><tbody>{filas_27}</tbody></table>
{extra}
<h2>Lo que este pre-informe no cubre</h2>
<ul><li>Quién es el dueño, la cadena de títulos con sus nombres y la continuidad de las inscripciones: certificados del Conservador.</li>
<li>Hipotecas, gravámenes, prohibiciones, interdicciones, embargos y litigios: certificado GP del Conservador y revisión de causas.</li>
<li>Deuda de contribuciones: certificado de deuda en la Tesorería (tgr.cl). Avalúo oficial vigente: certificado de avalúo en sii.cl.</li>
<li>Certificados municipales: número, no expropiación (municipal y SERVIU), recepción final, informes previos.</li>
<li>Gastos comunes y reglamento de copropiedad, si corresponde.</li></ul>
<p class="pie">Fuentes: detalle catastral SII 2021-2S, 2022-1S y 2026-2S; Formulario 2890 (enajenaciones); índices y modelo de reavalúo del proyecto. Los montos en UF usan la UF de la fecha de la escritura. Estimaciones de 2027 no oficiales. Este documento no contiene datos personales y no reemplaza el estudio de títulos de un abogado.</p>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rol", nargs="?")
    ap.add_argument("--comuna")
    ap.add_argument("--lote", help="archivo con un rol por línea (formato cod-manzana-predio)")
    a = ap.parse_args()
    roles = [x.strip() for x in open(a.lote, encoding="utf8") if x.strip()] if a.lote else [a.rol]
    if not roles or roles == [None]:
        ap.error("falta el rol")
    SALIDA.mkdir(parents=True, exist_ok=True)
    ok = no = 0
    for r in roles:
        d = leer(resolver(r, a.comuna))
        if d is None:
            print(f"[preinforme] {r}: no está en el catastro del Gran Santiago (2021-2S, 2022-1S ni 2026-2S)")
            no += 1
            continue
        out = SALIDA / f"{d['rol_id']}.html"
        out.write_text(informe(d), encoding="utf8")
        print(f"[preinforme] {r} → {out.relative_to(ROOT)} ({d['transf'].height} transferencias)")
        ok += 1
    print(f"[preinforme] {ok} generados, {no} no encontrados")


if __name__ == "__main__":
    main()
