"""Fase 5: índice de precios por barrio (ventas repetidas), brecha precio/avalúo y regresividad.

Índice (Bailey–Muth–Nourse anual, 2010 = 0 en log; la columna se llama "semestre" por compatibilidad, pero contiene el año):
  Pares = ventas consecutivas del mismo rol principal (habitacional, sin outliers), separadas por
  ≥ 1 semestre. Se descartan los pares con retorno anualizado |log| > 0,5 (probables cambios físicos o errores).
  1) Índice comunal c_t por MCO:  Δlog p = c_t2 − c_t1
  2) Desviación del barrio d_b,t con ridge (λ) sobre los residuos:  resid = d_b,t2 − d_b,t1
     → índice_b,t = c_t + d_b,t. El ridge encoge hacia la comuna a los barrios con pocos pares.
  Error estándar aproximado: diag((X'X + λI)^-1) · σ².

Brecha:
  brecha_micro_t = exp(mediana log ratio_ia del microbarrio en el semestre, encogida hacia el barrio y este hacia la comuna)
  residuo_prop   = log ratio_ia − log brecha_micro_t
Regresividad (estándar de estudios de ratio de la IAAO), por comuna y año:
  mediana del ratio, COD y PRD = media(ratio) / (Σ precio / Σ avalúo). PRD > 1,03 indica avalúo regresivo,
  es decir, las viviendas baratas se tasan relativamente más cerca de su precio.

Salidas:
  data/marts/indice_barrio.parquet  (barrio_id × semestre: indice_log, se, n_pares_barrio)
  data/marts/brecha_barrio.parquet  (microbarrio_id × semestre: brecha_micro, brecha_barrio, brecha_comuna, n)
  data/marts/indice_spar_barrio.parquet (barrio_id × año: spar_log, se) ← índice principal por barrio
  data/marts/fct_venta.parquet      (+ brecha_barrio, residuo_prop)
  data/staging/_reportes/regresividad.csv

Uso: python -m src.features.indices
"""

from __future__ import annotations

import numpy as np
import polars as pl

from src.etl.common import MARTS, REPORTES, Reporte

LAMBDA = 20.0
K_BRECHA = 10
K_SPAR = 10
MAX_RET_ANUAL = 0.5


def semestres(desde: int = 2010, hasta: int = 2026) -> list[str]:
    """Períodos del índice: años (el índice semestral por barrio resultó demasiado ruidoso)."""
    return [str(a) for a in range(desde, hasta + 1)]


def pares(v: pl.DataFrame) -> pl.DataFrame:
    base = v.filter(~pl.col("outlier_precio") & (pl.col("anio") >= 2010)).sort("rol_principal", "fecha_escritura")
    p = base.with_columns(
        pl.col("monto_uf").shift(1).over("rol_principal").alias("p0"),
        pl.col("anio").cast(pl.Utf8).shift(1).over("rol_principal").alias("s0"),
        pl.col("fecha_escritura").shift(1).over("rol_principal").alias("f0"),
    ).filter(pl.col("p0").is_not_null() & (pl.col("s0") != pl.col("anio").cast(pl.Utf8)))
    p = p.with_columns(
        (pl.col("monto_uf") / pl.col("p0")).log().alias("dlogp"),
        ((pl.col("fecha_escritura") - pl.col("f0")).dt.total_days() / 365.25).alias("anios"),
    )
    return p.filter((pl.col("dlogp") / pl.col("anios")).abs() <= MAX_RET_ANUAL).select(
        "rol_principal", "cod_comuna", "barrio_id", "s0", pl.col("anio").cast(pl.Utf8).alias("s1"), "dlogp"
    )


def _diseno(pp: pl.DataFrame, idx: dict[str, int]) -> np.ndarray:
    X = np.zeros((pp.height, len(idx)))
    r = np.arange(pp.height)
    X[r, [idx[s] for s in pp["s1"]]] += 1
    X[r, [idx[s] for s in pp["s0"]]] -= 1
    return X


def indice(pp: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    per = semestres()
    idx = {s: i for i, s in enumerate(per)}
    filas_c, filas_b = [], []
    for cod in pp["cod_comuna"].unique().sort():
        pc = pp.filter(pl.col("cod_comuna") == cod)
        X = _diseno(pc, idx)[:, 1:]  # base 2010_1
        y = pc["dlogp"].to_numpy()
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        c = np.concatenate([[0.0], beta])
        resid_c = y - X @ beta
        sigma2 = resid_c.var()
        se_c = np.sqrt(np.concatenate([[0.0], np.diag(np.linalg.pinv(X.T @ X)) * sigma2]))
        filas_c += [(cod, s, c[i], se_c[i]) for i, s in enumerate(per)]
        pc = pc.with_columns(pl.Series("resid", resid_c))
        for b in pc["barrio_id"].unique().sort():
            pb = pc.filter(pl.col("barrio_id") == b)
            Xb = _diseno(pb, idx)
            A = Xb.T @ Xb + LAMBDA * np.eye(len(per))
            d = np.linalg.solve(A, Xb.T @ pb["resid"].to_numpy())
            d -= d[0]  # misma base que la comuna
            rb = pb["resid"].to_numpy() - Xb @ d
            se_b = np.sqrt(np.diag(np.linalg.inv(A)) * max(rb.var(), 1e-6) + se_c**2)
            filas_b += [(cod, b, s, c[i] + d[i], se_b[i], pb.height) for i, s in enumerate(per)]
    ic = pl.DataFrame(filas_c, schema=["cod_comuna", "semestre", "indice_log", "se"], orient="row")
    ib = pl.DataFrame(filas_b, schema=["cod_comuna", "barrio_id", "semestre", "indice_log", "se", "n_pares_barrio"], orient="row")
    return ic, ib


def brecha(v: pl.DataFrame) -> pl.DataFrame:
    base = v.filter(pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    base = base.with_columns(pl.col("ratio_ia").log().alias("lr"))
    com = base.group_by("cod_comuna", "semestre").agg(pl.col("lr").median().alias("lr_comuna"))
    bar = base.group_by("cod_comuna", "barrio_id", "semestre").agg(pl.col("lr").median().alias("lr_b"), pl.len().alias("n_b"))
    mic = base.group_by("cod_comuna", "barrio_id", "microbarrio_id", "semestre").agg(pl.col("lr").median().alias("lr_m"), pl.len().alias("n"))
    bar = bar.join(com, on=["cod_comuna", "semestre"]).with_columns(
        ((pl.col("n_b") * pl.col("lr_b") + K_BRECHA * pl.col("lr_comuna")) / (pl.col("n_b") + K_BRECHA)).alias("lr_b_enc")
    )
    return mic.join(bar, on=["cod_comuna", "barrio_id", "semestre"]).with_columns(
        ((pl.col("n") * pl.col("lr_m") + K_BRECHA * pl.col("lr_b_enc")) / (pl.col("n") + K_BRECHA)).exp().alias("brecha_micro"),
        pl.col("lr_b_enc").exp().alias("brecha_barrio"),
        pl.col("lr_comuna").exp().alias("brecha_comuna"),
    ).select("cod_comuna", "barrio_id", "microbarrio_id", "semestre", "brecha_micro", "brecha_barrio", "brecha_comuna", "n")


def spar(v: pl.DataFrame) -> pl.DataFrame:
    """Índice SPAR por barrio y año: mediana de log(precio / avalúo de referencia 2S-2026).

    Usa todas las ventas de segunda mano, no solo los pares repetidos. Se encoge hacia la comuna con
    K_SPAR pseudo-observaciones. se ≈ 1,2533 · sd_robusta / √n (error estándar de la mediana; sd por MAD).
    Escala: barrio (≥ 1.800 ventas). La brecha se calcula por microbarrio.
    """
    b = v.filter(
        ~pl.col("outlier_precio")
        & ~pl.col("primera_venta_obra_nueva")
        & ~pl.col("avaluo_ref_incompleto")
        & (pl.col("avaluo_uf_ref") > 0)
        & (pl.col("anio") >= 2010)
    ).with_columns((pl.col("monto_uf") / pl.col("avaluo_uf_ref")).log().alias("lr"))
    b = b.filter(pl.col("lr").is_between(-3, 3))
    com = b.group_by("cod_comuna", "anio").agg(
        pl.col("lr").median().alias("lr_c"), (1.4826 * (pl.col("lr") - pl.col("lr").median()).abs().median()).alias("sd_c")
    )
    bar = b.group_by("cod_comuna", "barrio_id", "anio").agg(
        pl.col("lr").median().alias("lr_b"),
        (1.4826 * (pl.col("lr") - pl.col("lr").median()).abs().median()).alias("sd_b"),  # desviación robusta (MAD)
        pl.len().alias("n"),
    )
    out = bar.join(com, on=["cod_comuna", "anio"]).with_columns(
        ((pl.col("n") * pl.col("lr_b") + K_SPAR * pl.col("lr_c")) / (pl.col("n") + K_SPAR)).alias("spar_log"),
        (1.2533 * pl.col("sd_b").fill_null(pl.col("sd_c")) / (pl.col("n") + K_SPAR).sqrt()).alias("se"),
    )
    return out.select("cod_comuna", "barrio_id", "anio", "spar_log", "se", "n", pl.col("lr_c").alias("spar_log_comuna"))


def regresividad(v: pl.DataFrame) -> pl.DataFrame:
    b = v.filter(pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    # El ratio IAAO es avalúo/precio; se reporta así para seguir el estándar.
    b = b.with_columns((1 / pl.col("ratio_ia")).alias("a_p"))
    return (
        b.group_by("cod_comuna", "anio")
        .agg(
            pl.len().alias("n"),
            pl.col("a_p").median().alias("mediana_aval_precio"),
            ((pl.col("a_p") - pl.col("a_p").median()).abs().mean() / pl.col("a_p").median() * 100).alias("COD"),
            (pl.col("a_p").mean() / (pl.col("avaluo_uf").sum() / pl.col("monto_uf").sum())).alias("PRD"),
        )
        .sort("cod_comuna", "anio")
        .with_columns(pl.exclude("cod_comuna", "anio", "n").round(3))
    )


def main() -> None:
    v = pl.read_parquet(MARTS / "fct_venta.parquet")
    rep = Reporte("indices")
    pp = pares(v)
    rep.entrada = pp.height
    ic, ib = indice(pp)
    ib.write_parquet(MARTS / "indice_barrio.parquet")
    ic.write_parquet(MARTS / "indice_comuna.parquet")
    sp = spar(v)
    sp.write_parquet(MARTS / "indice_spar_barrio.parquet")
    a = sp.filter(pl.col("anio").is_in([2021, 2024])).pivot(on="anio", index="barrio_id", values=["spar_log", "se"])
    se_r = (a["se_2021"] ** 2 + a["se_2024"] ** 2).sqrt()
    rep.notas["spar_n_por_barrio_anio_mediana"] = int(sp["n"].median())
    rep.notas["spar_ic95_semiancho_mediano_nivel"] = round(float((1.96 * sp["se"]).median()), 4)
    rep.notas["spar_ic95_semiancho_mediano_retorno_2021_2024"] = round(float((1.96 * se_r).median()), 4)
    rep.notas["spar_share_barrios_ic95_retorno_<10pct"] = round(float((1.96 * se_r < 0.10).mean()), 4)
    # Concordancia SPAR vs ventas repetidas a nivel comunal (retorno 2012→2025)
    rs = ic.filter(pl.col("semestre").is_in(["2012", "2025"])).pivot(on="semestre", index="cod_comuna", values="indice_log")
    spc = sp.select("cod_comuna", "anio", "spar_log_comuna").unique().filter(pl.col("anio").is_in([2012, 2025])).pivot(on="anio", index="cod_comuna", values="spar_log_comuna")
    comp = rs.join(spc, on="cod_comuna").with_columns(
        ((pl.col("2025") - pl.col("2012")).exp() - 1).round(3).alias("ret_rs"),
        ((pl.col("2025_right") - pl.col("2012_right")).exp() - 1).round(3).alias("ret_spar"),
    )
    rep.notas["retorno_2012_2025_rs_vs_spar"] = {r["cod_comuna"]: (r["ret_rs"], r["ret_spar"]) for r in comp.iter_rows(named=True)}
    br = brecha(v)
    br.write_parquet(MARTS / "brecha_barrio.parquet")
    v = v.drop([c for c in ("brecha_micro", "brecha_barrio", "brecha_comuna", "residuo_prop") if c in v.columns])
    v = v.join(
        br.select("microbarrio_id", "semestre", "brecha_micro", "brecha_barrio", "brecha_comuna"),
        on=["microbarrio_id", "semestre"],
        how="left",
    ).with_columns((pl.col("ratio_ia").log() - pl.col("brecha_micro").log()).alias("residuo_prop"))
    v.write_parquet(MARTS / "fct_venta.parquet", compression="zstd")
    reg = regresividad(v)
    reg.write_csv(REPORTES / "regresividad.csv")

    # Estabilidad: IC 95% del nivel del índice 2024 y del retorno a 3 años 2021→2024 (aprox., sin covarianza)
    ult = ib.filter(pl.col("semestre") == "2024")
    r3 = ib.filter(pl.col("semestre").is_in(["2021", "2024"])).pivot(on="semestre", index="barrio_id", values="se")
    se_ret = (r3["2021"] ** 2 + r3["2024"] ** 2).sqrt()  # cota superior: ignora la covarianza positiva
    rep.notas["pares_por_comuna"] = dict(pp.group_by("cod_comuna").len().sort("cod_comuna").iter_rows())
    rep.notas["pares_por_barrio_mediana"] = int(ib.select("barrio_id", "n_pares_barrio").unique()["n_pares_barrio"].median())
    rep.notas["ic95_semiancho_mediano_nivel_2024"] = round(float((1.96 * ult["se"]).median()), 4)
    rep.notas["share_barrios_ic95_nivel_2024_<10pct"] = round(float((1.96 * ult["se"] < 0.10).mean()), 4)
    rep.notas["ic95_semiancho_mediano_retorno_2021_2024_cota"] = round(float((1.96 * se_ret).median()), 4)
    rep.notas["indice_comunal_2010_a_2025_pct"] = {
        r["cod_comuna"]: round((np.exp(r["indice_log"]) - 1) * 100, 1) for r in ic.filter(pl.col("semestre") == "2025").iter_rows(named=True)
    }
    rep.notas["filas_indice"] = ib.height
    rep.cerrar(pp.height)


if __name__ == "__main__":
    main()
