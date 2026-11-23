"""Chequeos previos a estimar efectos (docs/analysis_plan.md §3). No usan resultados del período post.

D1: estudio de eventos estimado SOLO con trimestres pre (2018-T1 … 2021-T4; referencia 2021-T4):
      y1 ~ Σ_k β_k·1[q=k]·shock·paga + Σ_k θ_k·1[q=k]·shock | rol + barrio×q + grupo×q
    Prueba conjunta β_k = 0 (Wald, errores agrupados por barrio). Criterio: p > 0,10.
D2: RKD en el tope de gradualidad (+25%). Muestra G_0 afecta en ambos semestres con cuota 2022 > $9.415.
      x = cuota_neta_teo_22 / (cuota_neta_teo_21 · 1,051) − 1 ; kink en 0,25
      Primera etapa con el pago OBSERVADO: y_fs = contrib_obs_22 / (contrib_obs_21 · 1,051) − 1
D3: RKD en el tope de $9.415 por cuota. Muestra: exentos en 2021-2S que pasan a afectos en 2022-1S.
      x = cuota neta teórica 2022 ; primera etapa: cuota observada 2022 (sin aseo)
Para D2 y D3: rdrobust(deriv=1); F = (kink/se)²; densidad con rddensity; covariables con rdrobust(deriv=1).

Salida: data/staging/_reportes/prechequeos.json (+ coeficientes pre de D1 en prechequeos_d1_pre.csv)
Uso: python -m src.models.prechequeos
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import polars as pl
from scipy import stats

from src.etl.common import MARTS, REPORTES, STAGING
from src.features.contribucion import CUOTA_MIN_GRADUAL_2022, FACTOR_ACTUALIZACION_BASE_2022

warnings.filterwarnings("ignore")


def d1_pretendencias() -> dict:
    import pyfixest as pf

    p = pl.read_parquet(MARTS / "panel_d1.parquet").filter(pl.col("post") == 0)
    p = p.with_columns((pl.col("shock") * pl.col("paga")).alias("sxp"), pl.col("q").cast(pl.Int32))
    df = p.select("y1", "q", "sxp", "shock", "rol_id", "barrio_id", "grupo").to_pandas()
    fit = pf.feols(
        "y1 ~ i(q, sxp, ref=15) + i(q, shock, ref=15) | rol_id + barrio_id^q + grupo^q",
        data=df,
        vcov={"CRV1": "barrio_id"},
    )
    coef, vcov = fit.coef(), fit._vcov
    names = list(coef.index)
    idx = [i for i, n in enumerate(names) if "sxp" in n]
    b = coef.values[idx]
    V = vcov[np.ix_(idx, idx)]
    k = len(idx)
    W = float(b @ np.linalg.solve(V, b))
    G = df["barrio_id"].nunique()
    F = W / k
    pval = float(1 - stats.f.cdf(F, k, G - 1))
    tabla = pl.DataFrame(
        {
            "termino": [names[i] for i in idx],
            "coef": b,
            "se": np.sqrt(np.diag(V)),
        }
    )
    tabla.write_csv(REPORTES / "prechequeos_d1_pre.csv")
    return {
        "n_obs": int(fit._N),
        "n_coef_pre": k,
        "F_conjunta": round(F, 3),
        "p_valor": round(pval, 4),
        "cumple_p>0.10": pval > 0.10,
        "coef_pre_max_abs": round(float(np.abs(b).max()), 5),
        "tasa_y1_pre": round(float(df["y1"].mean()), 5),
    }


def _rk(y: np.ndarray, x: np.ndarray, c: float) -> dict:
    from rdrobust import rdrobust

    r = rdrobust(y, x, c=c, deriv=1, p=1, kernel="triangular", bwselect="mserd")
    est = float(r.coef.iloc[0, 0])
    se = float(r.se.iloc[0, 0])
    return {
        "kink": round(est, 6),
        "se": round(se, 6),
        "F": round((est / se) ** 2, 2),
        "h": round(float(r.bws.iloc[0, 0]), 5),
        "n_efectivo": int(r.N_h[0] + r.N_h[1]),
    }


def _densidad(x: np.ndarray, c: float) -> dict:
    from rddensity import rddensity

    d = rddensity(X=x, c=c)
    pv = d.test["p_jk"]
    pv = pv.iloc[0] if hasattr(pv, "iloc") else pv
    return {"p_valor_densidad": round(float(pv), 4)}


def datos_rk() -> pl.DataFrame:
    r = pl.read_parquet(MARTS / "panel_roles.parquet")
    neta = []
    for sem, suf in (("2021_2", "21"), ("2022_1", "22")):
        neta.append(
            pl.read_parquet(STAGING / f"contribucion_{sem}.parquet").select(
                "rol_id", pl.col("contrib_neta_teo").alias(f"neta_teo_{suf}")
            )
        )
    return r.join(neta[0], on="rol_id", how="left").join(neta[1], on="rol_id", how="left").with_columns(
        (pl.col("sup_construida_total").cast(pl.Float64)).alias("sup"),
        pl.col("avaluo_total_21").log().alias("log_aval_21"),
        pl.col("anio_constr").cast(pl.Float64),
    )


def d2(r: pl.DataFrame) -> dict:
    f = FACTOR_ACTUALIZACION_BASE_2022
    m = r.filter(
        (pl.col("grupo") == "G_0")
        & (pl.col("neta_teo_21") > 0)
        & (pl.col("neta_teo_22") / 2 > CUOTA_MIN_GRADUAL_2022)
        & (pl.col("contrib_obs_sin_aseo_21") > 0)
    ).with_columns(
        (pl.col("neta_teo_22") / (pl.col("neta_teo_21") * f) - 1).alias("x"),
        (pl.col("contrib_obs_sin_aseo_22") / (pl.col("contrib_obs_sin_aseo_21") * f) - 1).alias("y_fs"),
    ).filter(pl.col("x").is_between(-0.5, 1.5))
    x, c = m["x"].to_numpy(), 0.25
    out = {"n_muestra": m.height, "n_sobre_kink": int((x > c).sum())}
    out["primera_etapa_obs"] = _rk(m["y_fs"].to_numpy(), x, c)
    out["densidad"] = _densidad(x, c)
    out["covariables"] = {v: _rk(m[v].to_numpy(), x, c) for v in ("log_aval_21", "sup", "anio_constr")}
    return out


def d3(r: pl.DataFrame) -> dict:
    m = r.filter(
        (pl.col("contrib_teo_21") <= 0) & (pl.col("neta_teo_22") > 0) & (pl.col("grupo") == "otro")
    ).with_columns(
        (pl.col("neta_teo_22") / 2).alias("x"),
        (pl.col("contrib_obs_sin_aseo_22") / 2).alias("y_fs"),
    ).filter(pl.col("x") < 40_000)
    x, c = m["x"].to_numpy(), float(CUOTA_MIN_GRADUAL_2022)
    out = {"n_muestra": m.height, "n_sobre_kink": int((x > c).sum())}
    out["primera_etapa_obs"] = _rk(m["y_fs"].to_numpy(), x, c)
    out["densidad"] = _densidad(x, c)
    out["covariables"] = {v: _rk(m[v].to_numpy(), x, c) for v in ("log_aval_21", "sup", "anio_constr")}
    return out


def main() -> None:
    res = {}
    print("D1: pretendencias…")
    res["D1_pretendencias"] = d1_pretendencias()
    r = datos_rk()
    print("D2: kink +25%…")
    res["D2_kink_25pct"] = d2(r)
    print("D3: kink $9.415…")
    res["D3_kink_9415"] = d3(r)
    for d in ("D2_kink_25pct", "D3_kink_9415"):
        fs = res[d]["primera_etapa_obs"]
        res[d]["cumple_F>10"] = fs["F"] > 10
    (REPORTES / "prechequeos.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
