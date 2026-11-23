"""P1 según docs/analysis_plan.md v1.0 §4 (prueba H1.1).

Panel barrio × año t. Confirmatorio: t ∈ {2018, 2019, 2020}. Exploratorio: t = 2021 (su objetivo, 2022→2025, ya fue mirado).
  Y4         = SPAR(t+4) − SPAR(t+1)                                  (índice del barrio, en log)
  brecha_rel = mediana log(precio/avalúo) del barrio en el año t − la misma mediana de la comuna
               (ventas de segunda mano del año t: no se solapan con el objetivo, que parte en t+1)
  momentum   = SPAR(t) − SPAR(t−3)
Regresión: Y4 ~ brecha_rel + momentum | comuna×año, errores agrupados por barrio.
Inferencia principal: permutación de brecha_rel entre barrios dentro de cada comuna×año (2.000 réplicas), bilateral.

Salida: data/staging/_reportes/resultados_p1.json
R1 (§9): réplica confirmatoria en las 33 comunas nuevas del Gran Santiago (sin las 3 piloto).
Uso: python -m src.models.estimar_p1
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import polars as pl

from src.etl.common import MARTS, PILOTO, REPORTES

warnings.filterwarnings("ignore")
R_PERM = 2000


def panel() -> pl.DataFrame:
    sp = pl.read_parquet(MARTS / "indice_spar_barrio.parquet").select("cod_comuna", "barrio_id", "anio", "spar_log")
    w = {a: sp.filter(pl.col("anio") == a).select("barrio_id", pl.col("spar_log").alias(f"s{a}")) for a in range(2010, 2027)}
    v = pl.read_parquet(MARTS / "fct_venta.parquet").filter(
        ~pl.col("primera_venta_obra_nueva") & ~pl.col("outlier_precio") & pl.col("ratio_ia").is_not_null()
    ).with_columns(pl.col("ratio_ia").log().alias("lr"))
    b = v.group_by("cod_comuna", "barrio_id", "anio").agg(pl.col("lr").median().alias("lr_b"), pl.len().alias("n_ventas"))
    c = v.group_by("cod_comuna", "anio").agg(pl.col("lr").median().alias("lr_c"))
    b = b.join(c, on=["cod_comuna", "anio"]).with_columns((pl.col("lr_b") - pl.col("lr_c")).alias("brecha_rel"))
    filas = []
    for t in (2018, 2019, 2020, 2021):
        d = b.filter(pl.col("anio") == t)
        for a in (t - 3, t, t + 1, t + 4):
            d = d.join(w[a], on="barrio_id", how="left")
        d = d.with_columns(
            (pl.col(f"s{t + 4}") - pl.col(f"s{t + 1}")).alias("y4"),
            (pl.col(f"s{t}") - pl.col(f"s{t - 3}")).alias("momentum"),
            pl.lit(t).alias("t"),
        ).select("cod_comuna", "barrio_id", "t", "brecha_rel", "momentum", "y4", "n_ventas")
        filas.append(d)
    return pl.concat(filas).drop_nulls()


def _ajuste(df, var: str = "brecha_rel"):
    import pyfixest as pf

    return pf.feols(f"y4 ~ {var} + momentum | cod_comuna^t", data=df, vcov={"CRV1": "barrio_id"})


def _beta_rapido(y, x, m, grupos) -> float:
    """β de brecha_rel con efectos fijos comuna×año (demeaning) y control de momentum, por MCO."""
    def dm(a):
        out = a.copy()
        for g in np.unique(grupos):
            k = grupos == g
            out[k] = a[k] - a[k].mean()
        return out
    Y, X = dm(y), np.column_stack([dm(x), dm(m)])
    return float(np.linalg.lstsq(X, Y, rcond=None)[0][0])


def prueba(d: pl.DataFrame, semilla: int = 20261123) -> dict:
    pdf = d.to_pandas()
    f = _ajuste(pdf)
    b, se, p = float(f.coef()["brecha_rel"]), float(f.se()["brecha_rel"]), float(f.pvalue()["brecha_rel"])
    grupos = (pdf["cod_comuna"].astype(str) + "_" + pdf["t"].astype(str)).to_numpy()
    y, x, m = pdf["y4"].to_numpy(), pdf["brecha_rel"].to_numpy(), pdf["momentum"].to_numpy()
    b0 = _beta_rapido(y, x, m, grupos)
    rng = np.random.default_rng(semilla)
    perm = np.empty(R_PERM)
    for r in range(R_PERM):
        xp = x.copy()
        for g in np.unique(grupos):
            k = np.where(grupos == g)[0]
            xp[k] = rng.permutation(x[k])
        perm[r] = _beta_rapido(y, xp, m, grupos)
    p_perm = float((np.abs(perm) >= abs(b0)).mean())
    return {
        "beta_brecha_rel": round(b, 4),
        "se_cluster": round(se, 4),
        "p_cluster": round(p, 4),
        "p_permutacion": round(p_perm, 4),
        "beta_momentum": round(float(f.coef()["momentum"]), 4),
        "n_barrio_anio": int(f._N),
        "interpretacion_beta": "Δ retorno log t+1→t+4 por +1 log de brecha relativa (≈ +100% de precio/avalúo vs. la comuna)",
        "efecto_por_+10pct_brecha_pp": round(b * np.log(1.1) * 100, 2),
    }


def main() -> None:
    d = panel()
    piloto = d.filter(pl.col("cod_comuna").is_in(list(PILOTO)))
    nuevas = d.filter(~pl.col("cod_comuna").is_in(list(PILOTO)))
    res = {
        "H1_1_confirmatoria_t_2018_2020": prueba(piloto.filter(pl.col("t") <= 2020)),
        "H1_1_exploratoria_t_2021": prueba(piloto.filter(pl.col("t") == 2021)),
        "R1_replica_33_comunas_nuevas_t_2018_2020": prueba(nuevas.filter(pl.col("t") <= 2020)),
        "R1_exploratoria_t_2021_comunas_nuevas": prueba(nuevas.filter(pl.col("t") == 2021)),
        "exploratorio_gran_santiago_completo_t_2018_2020": prueba(d.filter(pl.col("t") <= 2020)),
        "H1_2": "Exploratoria hasta tener objetivos posteriores a 2025 (§4); no se estima en esta versión.",
    }
    (REPORTES / "resultados_p1.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
