"""P2 según docs/analysis_plan.md v1.0 §4.

H2.1: residuo_prop_j = μ_{microbarrio×semestre} + β·AM_j + X_j'λ + ε_j
  Ventas de segunda mano 2018–2025 con ratio_ia válido (sin obra nueva ni outliers).
  AM_j = el rol principal tiene rebaja_21 o rebaja_22 en {100%, 50%} (huella del beneficio de adulto mayor).
  X: log superficie construida, año de construcción y copropiedad. Errores agrupados por barrio.
  Se espera β < 0 (descuento). Criterio económico (§6 b): descuento ≥ 4%.
  Heterogeneidad exploratoria (no registrada): ventas 2022–2025 de roles con rebaja en 2021-2S. Ahí el
  vendedor probablemente es el beneficiario; en las ventas anteriores a 2021 podría ser el comprador.

H2.2: compras "con descuento" (residuo < p10 de su microbarrio×semestre; residuo calculado con la mediana del
  microbarrio×semestre EXCLUYENDO la propia venta) que se revenden dentro de 4 años.
  Exceso de retorno = log(p_reventa / p_compra) − (SPAR_barrio[año reventa] − SPAR_barrio[año compra]).
  Se compara con las compras en el rango p40–p60. Se espera un exceso mayor. Se reporta el sesgo de
  regresión a la media y la comparación neta de costos de transacción (2–4%).

Salida: data/staging/_reportes/resultados_p2.json
Uso: python -m src.models.estimar_p2
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import polars as pl

from src.etl.common import MARTS, REPORTES, STAGING

warnings.filterwarnings("ignore")


def ventas_base() -> pl.DataFrame:
    v = pl.read_parquet(MARTS / "fct_venta.parquet").filter(
        ~pl.col("primera_venta_obra_nueva")
        & ~pl.col("outlier_precio")
        & pl.col("ratio_ia").is_not_null()
        & pl.col("anio").is_between(2018, 2025)
    )
    reb = []
    for sem, suf in (("2021_2", "21"), ("2022_1", "22")):
        reb.append(pl.read_parquet(STAGING / f"contribucion_{sem}.parquet").select(pl.col("rol_id").alias("rol_principal"), pl.col("rebaja_obs").alias(f"rebaja_{suf}")))
    v = v.join(reb[0], on="rol_principal", how="left").join(reb[1], on="rol_principal", how="left")
    return v.with_columns(
        (pl.col("rebaja_21").is_in(["100%", "50%"]) | pl.col("rebaja_22").is_in(["100%", "50%"])).fill_null(False).cast(pl.Int8).alias("AM"),
        pl.col("rebaja_21").is_in(["100%", "50%"]).fill_null(False).cast(pl.Int8).alias("AM_21"),
        pl.col("sup_construida_total").fill_null(1).clip(lower_bound=1).log().alias("log_sup"),
        pl.col("anio_construccion_max").fill_null(0).alias("anio_constr"),
        pl.col("copropiedad").fill_null(False).cast(pl.Int8),
        (pl.col("microbarrio_id") + "_" + pl.col("semestre")).alias("celda"),
    )


def h21(v: pl.DataFrame) -> dict:
    import pyfixest as pf

    df = v.select("residuo_prop", "AM", "AM_21", "log_sup", "anio_constr", "copropiedad", "celda", "barrio_id", "anio").to_pandas()
    out = {}
    for nombre, d in (("registrada_2018_2025", df), ("exploratoria_2022_2025", df[df["anio"] >= 2022])):
        var = "AM" if nombre.startswith("registrada") else "AM_21"
        f = pf.feols(f"residuo_prop ~ {var} + log_sup + anio_constr + copropiedad | celda", data=d, vcov={"CRV1": "barrio_id"})
        b, se, p = float(f.coef()[var]), float(f.se()[var]), float(f.pvalue()[var])
        out[nombre] = {
            "beta_log": round(b, 4),
            "descuento_pct": round((np.exp(b) - 1) * 100, 2),
            "ic95_pct": [round((np.exp(b - 1.96 * se) - 1) * 100, 2), round((np.exp(b + 1.96 * se) - 1) * 100, 2)],
            "p_valor": round(p, 4),
            "n": int(f._N),
            "n_AM": int(d[var].sum()),
        }
    return out


def residuo_loo(v: pl.DataFrame) -> pl.DataFrame:
    """log ratio menos la mediana de las OTRAS ventas de su microbarrio×semestre (celdas con ≥ 5 ventas)."""
    v = v.with_columns(pl.col("ratio_ia").log().alias("lr")).with_row_index("_i")
    res = np.full(v.height, np.nan)
    for (celda,), g in v.group_by(["celda"]):
        if g.height < 5:
            continue
        a, idx = g["lr"].to_numpy(), g["_i"].to_numpy()
        for j in range(len(a)):
            res[idx[j]] = a[j] - np.median(np.delete(a, j))
    return v.with_columns(pl.Series("residuo_loo", res)).with_columns(
        pl.col("residuo_loo").fill_nan(None)
    ).with_columns(
        pl.col("residuo_loo").rank("average").over("celda").truediv(pl.col("residuo_loo").count().over("celda")).alias("pct")
    )


def h22(v: pl.DataFrame) -> dict:
    import pyfixest as pf

    v = residuo_loo(v).filter(pl.col("residuo_loo").is_not_null())
    todas = pl.read_parquet(MARTS / "fct_venta.parquet").filter(~pl.col("outlier_precio") & (pl.col("monto_uf") > 0)).select(
        "rol_principal", pl.col("fecha_escritura").alias("f1"), pl.col("monto_uf").alias("p1"), pl.col("anio").alias("anio1")
    )
    spar = pl.read_parquet(MARTS / "indice_spar_barrio.parquet").select("barrio_id", "anio", "spar_log")
    c = v.filter((pl.col("pct") <= 0.10) | pl.col("pct").is_between(0.40, 0.60)).with_columns(
        (pl.col("pct") <= 0.10).cast(pl.Int8).alias("descuento")
    )
    # Primera reventa posterior dentro de 4 años
    r = (
        c.select("escritura_id", "rol_principal", "barrio_id", "fecha_escritura", "monto_uf", "anio", "descuento", "residuo_loo")
        .join(todas, on="rol_principal")
        .filter((pl.col("f1") > pl.col("fecha_escritura")) & ((pl.col("f1") - pl.col("fecha_escritura")).dt.total_days() <= 4 * 365.25) & ((pl.col("f1") - pl.col("fecha_escritura")).dt.total_days() >= 180))
        .sort("f1")
        .group_by("escritura_id")
        .first()
    )
    r = r.join(spar.rename({"anio": "anio", "spar_log": "s0"}), on=["barrio_id", "anio"], how="left").join(
        spar.rename({"anio": "anio1", "spar_log": "s1"}), on=["barrio_id", "anio1"], how="left"
    ).with_columns(
        ((pl.col("p1") / pl.col("monto_uf")).log() - (pl.col("s1") - pl.col("s0"))).alias("exceso")
    ).filter(pl.col("exceso").is_not_null() & pl.col("exceso").is_between(-2, 2))
    df = r.select("exceso", "descuento", "barrio_id", "anio").to_pandas()
    f = pf.feols("exceso ~ descuento | anio", data=df, vcov={"CRV1": "barrio_id"})
    b, se, p = float(f.coef()["descuento"]), float(f.se()["descuento"]), float(f.pvalue()["descuento"])
    g = r.group_by("descuento").agg(pl.len().alias("n"), pl.col("exceso").mean().alias("exceso_medio"), pl.col("residuo_loo").mean().alias("residuo_compra_medio"))
    tasa = c.group_by("descuento").agg(pl.len().alias("compras")).join(g.select("descuento", "n"), on="descuento").with_columns((pl.col("n") / pl.col("compras")).alias("tasa_reventa_4a"))
    return {
        "diferencia_exceso_log": round(b, 4),
        "diferencia_exceso_pct": round((np.exp(b) - 1) * 100, 2),
        "ic95_pct": [round((np.exp(b - 1.96 * se) - 1) * 100, 2), round((np.exp(b + 1.96 * se) - 1) * 100, 2)],
        "p_valor": round(p, 4),
        "neto_costos_2a4pct": [round((np.exp(b) - 1) * 100 - 4, 2), round((np.exp(b) - 1) * 100 - 2, 2)],
        "por_grupo": {("descuento" if row["descuento"] else "medio_p40_p60"): {k: (round(x, 4) if isinstance(x, float) else x) for k, x in row.items() if k != "descuento"} for row in g.iter_rows(named=True)},
        "tasa_reventa": {("descuento" if row["descuento"] else "medio_p40_p60"): round(row["tasa_reventa_4a"], 4) for row in tasa.iter_rows(named=True)},
        "nota_regresion_media": "El grupo 'descuento' se define por un precio bajo medido con ruido: parte del exceso es rebote estadístico, no oportunidad.",
    }


def main() -> None:
    v = ventas_base()
    res = {"H2_1": h21(v), "H2_2": h22(v)}
    (REPORTES / "resultados_p2.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
