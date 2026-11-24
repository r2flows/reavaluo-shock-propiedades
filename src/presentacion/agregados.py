"""Agregados por comuna para el mapa (solo datos agregados; nunca por rol).

Capas (todas validadas en docs/fase5…fase7):
  reavaluo_2027  por escenario S0/S2/S1: alza mediana del avalúo, % viviendas con alza > $200.000/año,
                 viviendas que pasan a pagar, alza anual mediana entre las que suben  (reavaluo2027_roles.parquet)
  reclamo        avalúo/precio mediano 2024–26, % de ventas con avalúo/precio sobre el p75 del Gran Santiago,
                 COD y PRD (estándar IAAO)                                              (fct_venta.parquet)
  brecha         precio/avalúo mediano 2024–26 y cambio desde 2022–23
  mercado        retorno 2022→2025 del índice SPAR comunal con IC95 y UF/m² mediano 2024–26
  contribuciones % de viviendas exentas y contribución anual mediana de las afectas (contribucion_2026_2.parquet)
Series por comuna: brecha 2018–2026 e índice SPAR 2010–2026.

Las comunas SII Santiago Centro/Oeste/Sur se agregan en Santiago (CUT 13101). Indicadores de ventas con n < 30 → null.

Salida: web/data/comunas.json
Uso: scripts/correr.sh --mem 4G src.presentacion.agregados
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl

from src.etl.common import MARTS, REF, ROOT, STAGING

SALIDA = ROOT / "web" / "data" / "comunas.json"
N_MIN = 30
ESC = ("S0", "S2", "S1")


def cut_map() -> pl.DataFrame:
    return pl.read_csv(REF / "comunas_cut.csv", separator=";", schema={"cod_comuna": pl.Int32, "cut": pl.Utf8, "nombre_mapa": pl.Utf8})


def reavaluo() -> pl.DataFrame:
    cols = ["rol_id", "cod_comuna", "destino", "avaluo_total", "contrib_teo"] + [f"{p}_{e}" for e in ESC for p in ("avaluo_27", "contrib_27", "pasa_a_afecto")]
    r = pl.read_parquet(MARTS / "reavaluo2027_roles.parquet", columns=cols).filter(pl.col("destino") == "H").join(cut_map(), on="cod_comuna")
    aggs = [pl.len().alias("viviendas")]
    for e in ESC:
        sube = (pl.col(f"contrib_27_{e}") - pl.col("contrib_teo")) * 2
        aggs += [
            ((pl.col(f"avaluo_27_{e}") / pl.col("avaluo_total")).median() * 100 - 100).alias(f"r27_{e}_alza_avaluo_pct"),
            ((sube > 200_000).mean() * 100).alias(f"r27_{e}_pct_alza_200k"),
            pl.col(f"pasa_a_afecto_{e}").sum().alias(f"r27_{e}_pasan_a_pagar"),
            sube.filter(sube > 0).median().alias(f"r27_{e}_alza_anual_mediana"),
        ]
    return r.group_by("cut").agg(aggs)


def ventas() -> pl.DataFrame:
    v = pl.read_parquet(
        MARTS / "fct_venta.parquet",
        columns=["cod_comuna", "anio", "monto_uf", "avaluo_uf", "ratio_ia", "avaluo_uf_ref", "avaluo_ref_incompleto", "uf_m2", "outlier_precio", "primera_venta_obra_nueva"],
    ).filter(~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    return v.join(cut_map(), on="cod_comuna")


def reclamo_brecha_mercado(v: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    con = v.filter(pl.col("ratio_ia").is_not_null()).with_columns((1 / pl.col("ratio_ia")).alias("ap"), pl.col("ratio_ia").log().alias("lr"))
    rec = con.filter(pl.col("anio").is_between(2024, 2026))
    p75 = float(rec["ap"].quantile(0.75))
    reclamo = rec.group_by("cut").agg(
        pl.len().alias("n_ventas_2426"),
        pl.col("ap").median().alias("rec_aval_precio_mediano"),
        ((pl.col("ap") > p75).mean() * 100).alias("rec_pct_sobre_p75"),
        ((pl.col("ap") - pl.col("ap").median()).abs().mean() / pl.col("ap").median() * 100).alias("rec_cod"),
        (pl.col("ap").mean() / (pl.col("avaluo_uf").sum() / pl.col("monto_uf").sum())).alias("rec_prd"),
        pl.col("lr").median().exp().alias("bre_nivel_2426"),
        pl.col("uf_m2").median().alias("mer_uf_m2"),
    )
    b2223 = con.filter(pl.col("anio").is_in([2022, 2023])).group_by("cut").agg(pl.col("lr").median().alias("lr2223"), pl.len().alias("n_2223"))
    reclamo = reclamo.join(b2223, on="cut", how="left").with_columns(
        ((pl.col("bre_nivel_2426").log() - pl.col("lr2223")).exp() * 100 - 100).alias("bre_cambio_pct")
    ).drop("lr2223")
    serie_brecha = con.group_by("cut", "anio").agg(pl.col("lr").median().exp().alias("v"), pl.len().alias("n")).filter(pl.col("n") >= N_MIN)

    # Índice SPAR comunal: mediana log(precio / avalúo fijo de referencia 2S-2026) por año; se por MAD
    s = v.filter(~pl.col("avaluo_ref_incompleto") & (pl.col("avaluo_uf_ref") > 0) & (pl.col("anio") >= 2010)).with_columns(
        (pl.col("monto_uf") / pl.col("avaluo_uf_ref")).log().alias("ls")
    ).filter(pl.col("ls").is_between(-3, 3))
    sp = s.group_by("cut", "anio").agg(
        pl.col("ls").median().alias("ls"),
        (1.2533 * 1.4826 * (pl.col("ls") - pl.col("ls").median()).abs().median() / pl.len().sqrt()).alias("se"),
        pl.len().alias("n"),
    ).filter(pl.col("n") >= N_MIN)
    a, b = sp.filter(pl.col("anio") == 2022), sp.filter(pl.col("anio") == 2025)
    ret = a.join(b, on="cut", suffix="_b").select(
        "cut",
        ((pl.col("ls_b") - pl.col("ls")).exp() * 100 - 100).alias("mer_ret_22_25_pct"),
        (1.96 * (pl.col("se") ** 2 + pl.col("se_b") ** 2).sqrt() * 100).alias("mer_ret_ic95_pp"),
    )
    base = sp.filter(pl.col("anio") == 2010).select("cut", pl.col("ls").alias("ls0"))
    serie_spar = sp.join(base, on="cut", how="left").with_columns(((pl.col("ls") - pl.col("ls0")).exp() * 100).alias("v"))
    series = {}
    for nombre, df in (("brecha", serie_brecha), ("spar", serie_spar)):
        for r in df.sort("anio").iter_rows(named=True):
            if r["v"] is not None:
                series.setdefault(r["cut"], {}).setdefault(nombre, []).append([r["anio"], round(float(r["v"]), 3)])
    return reclamo.join(ret, on="cut", how="left"), {"series": series, "p75_gs_aval_precio": round(p75, 4)}


def contribuciones() -> pl.DataFrame:
    c = pl.read_parquet(STAGING / "contribucion_2026_2.parquet", columns=["cod_comuna", "destino", "contrib_teo"]).filter(pl.col("destino") == "H").join(cut_map(), on="cod_comuna")
    return c.group_by("cut").agg(
        ((pl.col("contrib_teo") <= 0).mean() * 100).alias("con_pct_exentas"),
        (pl.col("contrib_teo") * 2).filter(pl.col("contrib_teo") > 0).median().alias("con_anual_mediana_afectas"),
    )


def microbarrios() -> dict:
    """Indicadores por microbarrio (sin geometría): rango de manzanas SII para ubicarlos en SII Mapas.

    Solo agregados; los indicadores de ventas se suprimen con n < N_MIN.
    """
    mb = pl.read_parquet(STAGING / "map_barrio.parquet", columns=["cod_comuna", "manzana", "microbarrio_id"])
    cols = ["cod_comuna", "manzana", "destino", "avaluo_total", "contrib_teo"] + [f"{p}_{e}" for e in ESC for p in ("avaluo_27", "contrib_27")]
    r = pl.read_parquet(MARTS / "reavaluo2027_roles.parquet", columns=cols).filter(pl.col("destino") == "H").join(mb, on=["cod_comuna", "manzana"], how="inner")
    aggs = [pl.len().alias("viviendas"), pl.col("manzana").min().alias("mz_min"), pl.col("manzana").max().alias("mz_max"), pl.col("cod_comuna").first()]
    for e in ESC:
        sube = (pl.col(f"contrib_27_{e}") - pl.col("contrib_teo")) * 2
        aggs += [
            ((pl.col(f"avaluo_27_{e}") / pl.col("avaluo_total")).median() * 100 - 100).alias(f"r27_{e}_alza_avaluo_pct"),
            ((sube > 200_000).mean() * 100).alias(f"r27_{e}_pct_alza_200k"),
            sube.filter(sube > 0).median().alias(f"r27_{e}_alza_anual_mediana"),
        ]
    a = r.group_by("microbarrio_id").agg(aggs)
    v = pl.read_parquet(MARTS / "fct_venta.parquet", columns=["microbarrio_id", "anio", "ratio_ia", "uf_m2", "outlier_precio", "primera_venta_obra_nueva"])
    v = v.filter(pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    reciente = pl.col("anio").is_between(2024, 2026)
    previo = pl.col("anio").is_between(2022, 2023)
    b = v.group_by("microbarrio_id").agg(
        reciente.sum().alias("n_ventas_2426"),
        previo.sum().alias("n_ventas_2223"),
        (1 / pl.col("ratio_ia")).filter(reciente).median().alias("rec_aval_precio_mediano"),
        pl.col("ratio_ia").filter(reciente).log().median().alias("_log_2426"),
        pl.col("ratio_ia").filter(previo).log().median().alias("_log_2223"),
        pl.col("uf_m2").filter(reciente & (pl.col("uf_m2") > 0)).median().alias("uf_m2_mediano_2426"),
    ).with_columns(
        pl.col("_log_2426").exp().alias("bre_nivel_2426"),
        ((pl.col("_log_2426") - pl.col("_log_2223")).exp() * 100 - 100).alias("bre_cambio_pct"),
    )
    # Densificación: viviendas (roles H) 2026-2S frente a 2021-2S, por microbarrio
    h21 = pl.read_parquet(STAGING / "catastro" / "roles_2021_2.parquet", columns=["cod_comuna", "manzana", "destino"]).filter(pl.col("destino") == "H").join(mb, on=["cod_comuna", "manzana"], how="inner").group_by("microbarrio_id").agg(pl.len().alias("_viv_21"))
    # Rotación: compraventas de viviendas usadas 2016–2025 (sin primera venta de obra nueva) por cada 100 viviendas al año
    t = (pl.scan_parquet(STAGING / "fct_transferencia.parquet").select("rol_id", "cod_comuna", "manzana", "fecha_escritura", "es_h", "primera_venta_obra_nueva")
         .filter(pl.col("es_h") & ~pl.col("primera_venta_obra_nueva") & pl.col("fecha_escritura").dt.year().is_between(2016, 2025))
         .unique(["rol_id", "fecha_escritura"]).collect()
         .join(mb, on=["cod_comuna", "manzana"], how="inner").group_by("microbarrio_id").agg(pl.len().alias("_ventas_1625")))
    nom = pl.read_parquet(STAGING / "microbarrio_nombres.parquet")
    hit = pl.read_parquet(STAGING / "microbarrio_hitos.parquet")
    d = (a.join(b, on="microbarrio_id", how="left").join(h21, on="microbarrio_id", how="left").join(t, on="microbarrio_id", how="left")
         .join(nom, on="microbarrio_id", how="left").join(hit, on="microbarrio_id", how="left")
         .join(cut_map().select("cod_comuna", "cut"), on="cod_comuna"))
    d = d.with_columns(
        pl.when(pl.col("_viv_21") >= N_MIN).then((pl.col("viviendas") / pl.col("_viv_21") - 1) * 100).otherwise(None).alias("viv_crec_21_26_pct"),
        pl.when(pl.col("viviendas") >= N_MIN).then(pl.col("_ventas_1625").fill_null(0) / pl.col("viviendas") / 10 * 100).otherwise(None).alias("rotacion_anual_pct"),
    )
    d = d.with_columns([pl.when(pl.col("n_ventas_2426") >= N_MIN).then(pl.col(c)).otherwise(None).alias(c) for c in ("rec_aval_precio_mediano", "bre_nivel_2426", "uf_m2_mediano_2426")])
    d = d.with_columns(pl.when((pl.col("n_ventas_2426") >= N_MIN) & (pl.col("n_ventas_2223") >= N_MIN)).then(pl.col("bre_cambio_pct")).otherwise(None).alias("bre_cambio_pct"))
    # Formato compacto: encabezado de campos + filas como arreglos (≈ 120 KB para 2.000 microbarrios)
    campos = ["id", "mz_min", "mz_max", "viviendas"] + [f"r27_{e}_{m}" for e in ESC for m in ("alza_avaluo_pct", "pct_alza_200k", "alza_anual_mediana")] + ["rec_aval_precio_mediano", "bre_nivel_2426", "n_ventas_2426", "uf_m2_mediano_2426", "bre_cambio_pct", "viv_crec_21_26_pct", "rotacion_anual_pct", "nombre", "calles", "barrio", "metro", "metro_m", "plazas"]
    dec = {"rec_aval_precio_mediano": 3, "bre_nivel_2426": 3, "uf_m2_mediano_2426": 1, "bre_cambio_pct": 1, "viv_crec_21_26_pct": 1, "rotacion_anual_pct": 2, "metro_m": 0}
    out: dict = {"campos": campos, "comunas": {}}
    d = d.rename({"microbarrio_id": "id"})
    for row in d.sort("cod_comuna", "mz_min").iter_rows(named=True):
        fila = []
        for c in campos:
            x = row[c]
            if isinstance(x, float):
                x = round(x, dec.get(c, 1)) if "mediana" not in c or c in dec else round(x)
                x = int(x) if c == "metro_m" else x
            if c == "calles":
                x = json.loads(x) if x else []
            fila.append(x)
        out["comunas"].setdefault(row["cut"], []).append(fila)
    return out


def main() -> None:
    v = ventas()
    rbm, extra = reclamo_brecha_mercado(v)
    del v
    df = (
        cut_map().group_by("cut").agg(pl.col("nombre_mapa").first().alias("nombre"))
        .join(reavaluo(), on="cut", how="left")
        .join(rbm, on="cut", how="left")
        .join(contribuciones(), on="cut", how="left")
    )
    # Supresión: indicadores de ventas con pocas observaciones
    venta_cols = [c for c in df.columns if c.startswith(("rec_", "bre_", "mer_"))]
    df = df.with_columns([pl.when(pl.col("n_ventas_2426") >= N_MIN).then(pl.col(c)).otherwise(None).alias(c) for c in venta_cols])
    filas = []
    for r in df.sort("nombre").iter_rows(named=True):
        filas.append({k: (round(float(x), 3) if isinstance(x, float) else x) for k, x in r.items()})
    salida = {
        "generado": "2026-11-23",
        "fuente": "SII (F2890, detalle catastral 2021-2S/2022-1S/2026-2S), UF SII; análisis en github.com/r2flows/reavaluo-shock-propiedades",
        "n_min": N_MIN,
        "p75_gs_aval_precio": extra["p75_gs_aval_precio"],
        "comunas": filas,
        "series": extra["series"],
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    micro = microbarrios()
    (SALIDA.parent / "microbarrios.json").write_text(json.dumps(micro, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    print(f"[agregados] {sum(len(v) for v in micro['comunas'].values())} microbarrios → web/data/microbarrios.json ({(SALIDA.parent / 'microbarrios.json').stat().st_size / 1024:.0f} KB)")
    print(f"[agregados] {len(filas)} comunas → {SALIDA.relative_to(ROOT)} ({SALIDA.stat().st_size / 1024:.0f} KB)")
    print(df.select("nombre", "viviendas", "r27_S1_alza_avaluo_pct", "r27_S1_pct_alza_200k", "rec_aval_precio_mediano", "rec_prd", "bre_cambio_pct", "mer_ret_22_25_pct", "con_pct_exentas").sort("nombre"))


if __name__ == "__main__":
    main()
