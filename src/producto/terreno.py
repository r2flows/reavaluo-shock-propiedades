"""Ficha de terreno por rol y búsqueda de roles por dirección (para compradores de terrenos).

Fuentes, en orden de preferencia para un rol:
  1. Catastro vigente 2026-2S, serie no agrícola (Gran Santiago): roles_2026_2.
  2. Catastro vigente 2026-2S, serie agrícola (Gran Santiago): agricola_roles_2026_2 + agricola_suelos_2026_2.
  3. Catastro 2022-1S, serie agrícola (resto de la Región Metropolitana): agricola_roles_2022_1 + suelos.
     Es la foto de hace 4 años; las comunas periurbanas no están descargadas en su versión vigente.

Ubicación (U urbano, R rural, E probable extensión urbana): código del catastro sin definición publicada
por el SII (src/etl/ref/ubicaciones_sii.csv). Es una clasificación tributaria: lo que rige es el límite
urbano del plan regulador, que certifica la municipalidad en el Certificado de Informaciones Previas.
Clases de suelo de los predios agrícolas: src/etl/ref/clases_suelo_sii.csv.

Búsqueda por dirección: el SII abrevia ("PJE", "AV", "PC 39", "LT 1"), así que cada palabra buscada se
traduce a sus abreviaturas y se exige que todas aparezcan; los números deben calzar enteros (ignorando ceros
a la izquierda). Sin datos personales: solo rol, dirección y datos del predio.

Uso: .venv/bin/python -m src.producto.terreno 14109 "los heroes parcela 39"
     .venv/bin/python -m src.producto.terreno 14109 1035-64
"""

from __future__ import annotations

import html
import re
import sys
import unicodedata

import polars as pl

from src.etl.common import REF
from src.titulos import preinforme as pi

FUENTES = [  # (archivo de roles, archivo de suelos, serie, semestre)
    ("catastro/roles_2026_2.parquet", None, "No agrícola", "2026-2S"),
    ("catastro/agricola_roles_2026_2.parquet", "catastro/agricola_suelos_2026_2.parquet", "Agrícola", "2026-2S"),
    ("catastro/agricola_roles_2022_1.parquet", "catastro/agricola_suelos_2022_1.parquet", "Agrícola", "2022-1S"),
]
SINONIMOS = [  # formas en que la gente escribe → patrón que calza con las abreviaturas del SII
    (("AVENIDA", "AVDA", "AV"), r"(AV|AVDA|AVENIDA)\.?"),
    (("PASAJE", "PJE", "PSJE", "PJ"), r"(PJE|PSJE|PJ|PASAJE)\.?"),
    (("CAMINO", "CAM"), r"(CAM|CAMINO)\.?"),
    (("PARCELA", "PARC", "PC"), r"(PC|PARC|PARCELA)\.?"),
    (("LOTE", "LT"), r"(LT|LOTE)\.?"),
    (("SITIO", "ST"), r"(ST|SITIO)\.?"),
    (("HIJUELA", "HJ", "HIJ"), r"(HJ|HIJ|HIJUELA)\.?"),
    (("DEPARTAMENTO", "DEPTO", "DPTO", "DP"), r"(DP|DPTO|DEPTO|DEPARTAMENTO)\.?"),
    (("SANTA", "STA"), r"(STA|SANTA)\.?"),
    (("SANTO", "STO"), r"(STO|SANTO)\.?"),
    (("SAN",), r"(SAN|S)\.?"),
    (("GENERAL", "GRAL"), r"(GRAL|GENERAL)\.?"),
]
VACIAS = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "CALLE", "N", "NO", "NRO", "NUMERO"}
MAX_RESULTADOS = 30


def normalizar(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn" or c == "̃")
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", re.sub(r"[^\wÑ]+", " ", s)).strip()


def patrones(consulta: str) -> list[str]:
    """Un patrón regex por palabra de la consulta (todas deben calzar)."""
    out = []
    for w in normalizar(consulta).split():
        if w in VACIAS:
            continue
        if w.isdigit():
            out.append(rf"(^|[^0-9])0*{int(w)}([^0-9]|$)")
            continue
        pat = next((p for formas, p in SINONIMOS if w in formas), re.escape(w))
        out.append(rf"(^|[^A-ZÑ]){pat}")
    return out


def buscar_en(df: pl.DataFrame, consulta: str, limite: int = MAX_RESULTADOS) -> pl.DataFrame:
    """df: rol_id, direccion, … Devuelve las filas cuya dirección normalizada calza con todas las palabras."""
    ps = patrones(consulta)
    if not ps:
        return df.head(0)
    d = df.with_columns(
        pl.col("direccion").fill_null("").str.to_uppercase()
        .str.replace_all("[ÁÀ]", "A").str.replace_all("[ÉÈ]", "E").str.replace_all("[ÍÌ]", "I").str.replace_all("[ÓÒ]", "O").str.replace_all("[ÚÙÜ]", "U")
        .str.replace_all(r"[^\wÑ]+", " ").alias("_dir")
    )
    for p in ps:
        d = d.filter(pl.col("_dir").str.contains(p))
    # Primero las direcciones que contienen la consulta tal cual (p. ej. "IRARRAZAVAL 366" antes que "… BD 366")
    exacta = normalizar(consulta)
    return (d.with_columns((~pl.col("_dir").str.contains(exacta, literal=True)).alias("_r"), pl.col("_dir").str.len_chars().alias("_n"))
            .sort("_r", "_n", "direccion").drop("_dir", "_r", "_n").head(limite))


def buscar(cod_comuna: int, consulta: str) -> pl.DataFrame:
    partes, hay_vigente = [], False
    for rel, _, serie, sem in FUENTES:
        f = pi.STAGING / rel
        if not f.exists() or (sem == "2022-1S" and hay_vigente):
            continue  # la foto 2022 solo se usa en comunas sin catastro vigente
        df = pl.scan_parquet(f).filter(pl.col("cod_comuna") == cod_comuna).select("rol_id", "direccion", "destino", "cod_ubicacion").collect()
        hay_vigente |= sem == "2026-2S" and df.height > 0
        if df.height:
            partes.append(buscar_en(df, consulta).with_columns(pl.lit(serie).alias("serie"), pl.lit(sem).alias("semestre")))
    return pl.concat(partes).head(MAX_RESULTADOS) if partes else pl.DataFrame()


def comunas_con_datos() -> pl.DataFrame:
    cods = set()
    for rel, _, _, _ in FUENTES:
        f = pi.STAGING / rel
        if f.exists():
            cods |= set(pl.scan_parquet(f).select(pl.col("cod_comuna").unique()).collect()["cod_comuna"])
    c = pl.read_csv(REF / "comunas.csv", separator=";", schema_overrides={"cod_comuna": pl.Int32})
    return c.filter(pl.col("cod_comuna").is_in(sorted(cods))).sort("nombre_sii")


def ficha(rid: str) -> dict | None:
    cod = int(rid.split("-")[0])
    for rel, rel_s, serie, sem in FUENTES:
        f = pi.STAGING / rel
        if not f.exists():
            continue
        x = pl.scan_parquet(f).filter((pl.col("cod_comuna") == cod) & (pl.col("rol_id") == rid)).collect()
        if not x.height:
            continue
        d = {"rol_id": rid, "serie": serie, "semestre": sem, "rol": x.row(0, named=True), "suelos": pl.DataFrame()}
        if rel_s:
            s = pl.scan_parquet(pi.STAGING / rel_s).filter((pl.col("cod_comuna") == cod) & (pl.col("rol_id") == rid)).collect()
            cs = pl.read_csv(REF / "clases_suelo_sii.csv", separator=";", schema_overrides={"cod_suelo": pl.Utf8})
            d["suelos"] = (s.group_by("cod_suelo").agg(pl.col("sup_ha").sum())
                           .join(cs, on="cod_suelo", how="left").sort("orden", nulls_last=True))
        return d
    return None


def ubicacion(cod: str | None) -> tuple[str, str]:
    if not cod:
        return "Sin dato (el catastro 2022 no trae este código)", ""
    u = pl.read_csv(REF / "ubicaciones_sii.csv", separator=";").filter(pl.col("cod_ubicacion") == cod)
    return (f"{u['descripcion'][0]} (código {cod})", u["nota"][0]) if u.height else (f"Código {cod}", "")


def html_ficha(d: dict, comuna: str) -> str:
    e = html.escape
    r = d["rol"]
    u_txt, u_nota = ubicacion(r.get("cod_ubicacion"))
    cod, mz, pr = d["rol_id"].split("-")
    s = d["suelos"]
    if s.height:
        tot = float(s["sup_ha"].sum())
        filas = "".join(
            f"<tr><td>{e(str(x['cod_suelo']))}</td><td>{e(x['descripcion'] or 'Código sin descripción')}</td><td class=n>{x['sup_ha']:,.2f}</td><td class=n>{x['sup_ha'] / tot:.0%}</td></tr>".replace(",", "X").replace(".", ",").replace("X", ".")
            for x in s.iter_rows(named=True)
        )
        suelos = (f"<table><thead><tr><th>Clase</th><th>Descripción</th><th class=n>Hectáreas</th><th class=n>%</th></tr></thead><tbody>{filas}</tbody></table>"
                  "<p class=nota>Clases de suelo del SII para predios agrícolas: riego (1R a 4R, de mejor a peor) y secano (1 a 4 arable, 5 a 8 no arable). La 4R y los códigos 20 a 29 (solo Magallanes) no figuran en la documentación del SII.</p>")
        sup = f"{tot:,.2f} ha".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        suelos = "<p>No aplica: es un predio de la serie no agrícola (el SII no le asigna clases de suelo).</p>" if d["serie"] == "No agrícola" else "<p>Sin líneas de suelo registradas.</p>"
        sup = f"{r.get('sup_terreno_m2') or '—'} m²" if d["serie"] == "No agrícola" else "—"
    moneda = " · pesos de 2022, antes del reajuste por IPC" if d["semestre"] == "2022-1S" else ""
    return f"""<h1>Rol {e(f"{mz}-{pr}")} · {e(comuna)}</h1>
<dl><dt>Rol SII</dt><dd>{e(d['rol_id'])}</dd>
<dt>Dirección o nombre del predio</dt><dd>{e(r.get('direccion') or '—')}</dd>
<dt>Serie del catastro</dt><dd>{e(d['serie'])} (catastro {e(d['semestre'])})</dd>
<dt>Ubicación según el SII</dt><dd><b>{e(u_txt)}</b></dd>
<dt>Destino</dt><dd>{e(pi.DESTINOS.get(r.get('destino'), r.get('destino') or '—'))}</dd>
<dt>Superficie de terreno</dt><dd>{e(sup)}</dd>
<dt>Avalúo fiscal</dt><dd>{pi.clp(r.get('avaluo_total'))} (exento {pi.clp(r.get('avaluo_exento'))}){moneda}</dd>
<dt>Contribución semestral</dt><dd>{pi.clp(r.get('contrib_semestral'))}{moneda}</dd></dl>
<p class=nota>{e(u_nota)} La condición urbana o rural que rige es la del plan regulador: pida el Certificado de Informaciones Previas a la Dirección de Obras de la municipalidad.</p>
<h2>Clases de suelo</h2>{suelos}"""


def main(argv: list[str]) -> None:
    cod, q = int(argv[0]), " ".join(argv[1:])
    if re.fullmatch(r"\d+-\d+", q):
        m, p = q.split("-")
        d = ficha(f"{cod}-{int(m)}-{int(p)}")
        print(d if d is None else {k: v for k, v in d.items() if k != "suelos"}, d and d["suelos"])
    else:
        print(buscar(cod, q))


if __name__ == "__main__":
    main(sys.argv[1:])
