"""Estimación de P3 según docs/analysis_plan.md v1.0 + desviaciones DV1 y DV2 (§9).

D1 registrado (no identificado por tendencias previas; se reporta igual):
  y1 ~ post·shock·paga + post·shock + controles×post | rol + barrio×q + grupo×q
DV1 (exploratoria): lo mismo + tendencias lineales q·shock·paga y q·shock.
  Sensibilidad: período pre restringido a 2020–2021, sin tendencias.
  Placebo: y2 (transferencias sin monto) con la especificación DV1.
D2/D3 (secundarios): fuzzy RKD; resultado = venta de segunda mano en 2022-T1 … 2023-T4; versión registrada y DV2 (con covs).

Escala: shock en desviaciones estándar de delta_contrib_teo (semestral). Se reporta además el efecto por cada
+$100.000 de alza anual, en pp de probabilidad anual de venta.

Salida: data/staging/_reportes/resultados_p3.json (+ p3_<modelo>.json). Cada modelo corre en un subproceso (memoria).
Estudio de eventos anual (DV3).
Uso: python -m src.models.estimar_p3
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import polars as pl

from src.etl.common import MARTS, REPORTES
from src.models.prechequeos import datos_rk
from src.features.contribucion import CUOTA_MIN_GRADUAL_2022, FACTOR_ACTUALIZACION_BASE_2022

warnings.filterwarnings("ignore")

CONTROLES = "i(decil_avaluo_21, post) + post:sup_k + post:anio_constr + i(copropiedad, post)"
FE = "rol_id + barrio_id^q + grupo^q"


def panel() -> "pd.DataFrame":
    p = pl.read_parquet(MARTS / "panel_d1.parquet").with_columns(
        (pl.col("shock") * pl.col("paga")).alias("sxp"),
        pl.col("q").cast(pl.Int32),
        (pl.col("sup_construida_total").fill_null(0) / 100).alias("sup_k"),
        pl.col("copropiedad").cast(pl.Int8),
    )
    p = p.with_columns(
        (pl.col("q") // 4 + 2018).alias("anio_q"),
        (pl.col("post") * pl.col("sxp")).alias("post_sxp"),
        (pl.col("post") * pl.col("shock")).alias("post_shock"),
        (pl.col("q") * pl.col("sxp")).alias("t_sxp"),
        (pl.col("q") * pl.col("shock")).alias("t_shock"),
    )
    cols = ["y1", "y2", "q", "anio_q", "post", "sxp", "shock", "paga", "post_sxp", "post_shock", "t_sxp", "t_shock",
            "decil_avaluo_21", "sup_k", "anio_constr", "copropiedad", "rol_id", "barrio_id", "grupo"]
    df = p.select(cols).to_pandas()
    for c in ("rol_id", "barrio_id", "grupo", "decil_avaluo_21"):
        df[c] = df[c].astype("category")
    for c in ("y1", "y2", "post", "paga", "copropiedad"):
        df[c] = df[c].astype("int8")
    return df


def _coef(fit, nombre: str, sd_semestral: float) -> dict:
    b, se, pv = float(fit.coef()[nombre]), float(fit.se()[nombre]), float(fit.pvalue()[nombre])
    por_100k_anual = b * 4 * 100 * (100_000 / (2 * sd_semestral))  # pp de prob. anual por +$100k/año
    return {
        "coef_trimestral_pp_por_sd": round(b * 100, 4),
        "se_pp": round(se * 100, 4),
        "p_valor": round(pv, 4),
        "ic95_pp": [round((b - 1.96 * se) * 100, 4), round((b + 1.96 * se) * 100, 4)],
        "efecto_pp_anual_por_100k_anual": round(por_100k_anual, 4),
        "n_obs": int(fit._N),
    }


MODELOS = {
    "D1_registrado": ("y1", "post_sxp + post_shock", None),
    "DV1_tendencias": ("y1", "post_sxp + post_shock + t_sxp + t_shock", None),
    "DV1_sens_pre_2020_2021": ("y1", "post_sxp + post_shock", 8),
    "DV1_placebo_y2": ("y2", "post_sxp + post_shock + t_sxp + t_shock", None),
}
EVENTOS = {  # DV3: dummies anuales, referencia 2021
    "eventos_registrado": "i(anio_q, sxp, ref=2021) + i(anio_q, shock, ref=2021)",
    # Con tendencias lineales se omiten 2018 y 2021 (dos normalizaciones); dummies construidas a mano
    "eventos_dv1_tendencias": " + ".join(
        [f"ev_sxp_{a}" for a in (2019, 2020, 2022, 2023, 2024, 2025)] + [f"ev_shock_{a}" for a in (2019, 2020, 2022, 2023, 2024, 2025)]
    ) + " + t_sxp + t_shock",
}


def correr(nombre: str) -> None:
    """Estima un modelo en este proceso y guarda su resultado (para aislar el uso de memoria)."""
    import pyfixest as pf

    df = panel()
    sd = float(pl.read_parquet(MARTS / "panel_d1.parquet").select("rol_id", "delta_contrib_teo").unique()["delta_contrib_teo"].std())
    vc = {"CRV1": "barrio_id"}
    kw = dict(vcov=vc, lean=True, store_data=False, copy_data=False)
    if nombre in MODELOS:
        y, rhs, q_min = MODELOS[nombre]
        d = df[df["q"] >= q_min] if q_min else df
        f = pf.feols(f"{y} ~ {rhs} + {CONTROLES} | {FE}", data=d, **kw)
        res = _coef(f, "post_sxp", sd)
    else:
        if nombre == "eventos_dv1_tendencias":
            for a in (2019, 2020, 2022, 2023, 2024, 2025):
                df[f"ev_sxp_{a}"] = (df["anio_q"] == a) * df["sxp"]
                df[f"ev_shock_{a}"] = (df["anio_q"] == a) * df["shock"]
        f = pf.feols(f"y1 ~ {EVENTOS[nombre]} | {FE}", data=df, **kw)
        c, se = f.coef(), f.se()
        res = {
            k: {"coef_pp": round(float(c[k]) * 100, 4), "se_pp": round(float(se[k]) * 100, 4)}
            for k in c.index
            if ("sxp" in k and "anio_q" in k) or k.startswith("ev_sxp_") or k == "t_sxp"
        }
    (REPORTES / f"p3_{nombre}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(nombre, "ok")


def _rk_fuzzy(y, x, d, c, covs=None) -> dict:
    from rdrobust import rdrobust

    r = rdrobust(y, x, c=c, fuzzy=d, deriv=1, p=1, kernel="triangular", bwselect="mserd", covs=covs)
    est, se = float(r.coef.iloc[0, 0]), float(r.se.iloc[2, 0])  # fila 2: robusto
    pv = float(r.pv.iloc[2, 0])
    return {"efecto": round(est, 5), "se_robusto": round(se, 5), "p_robusto": round(pv, 4), "h": round(float(r.bws.iloc[0, 0]), 4), "n_efectivo": int(r.N_h[0] + r.N_h[1])}


def resultado_ventas(roles: pl.DataFrame, q_ini: int = 16, q_fin: int = 23) -> pl.DataFrame:
    p = pl.read_parquet(MARTS / "fct_venta.parquet").filter(
        ~pl.col("primera_venta_obra_nueva") & ~pl.col("outlier_precio") & (pl.col("monto_uf") > 0)
    ).with_columns(((pl.col("fecha_escritura").dt.year() - 2018) * 4 + (pl.col("fecha_escritura").dt.month() - 1) // 3).alias("q"))
    vend = p.filter(pl.col("q").is_between(q_ini, q_fin)).select(pl.col("rol_principal").alias("rol_id")).unique().with_columns(pl.lit(1).alias("vende"))
    return roles.join(vend, on="rol_id", how="left").with_columns(pl.col("vende").fill_null(0))


def d2_d3() -> dict:
    r = resultado_ventas(datos_rk())
    f = FACTOR_ACTUALIZACION_BASE_2022
    out = {}
    m2 = r.filter(
        (pl.col("grupo") == "G_0") & (pl.col("neta_teo_21") > 0) & (pl.col("neta_teo_22") / 2 > CUOTA_MIN_GRADUAL_2022) & (pl.col("contrib_obs_sin_aseo_21") > 0)
    ).with_columns(
        (pl.col("neta_teo_22") / (pl.col("neta_teo_21") * f) - 1).alias("x"),
        (pl.col("contrib_obs_sin_aseo_22") / (pl.col("contrib_obs_sin_aseo_21") * f) - 1).alias("d"),
    ).filter(pl.col("x").is_between(-0.5, 1.5))
    m3 = r.filter((pl.col("contrib_teo_21") <= 0) & (pl.col("neta_teo_22") > 0) & (pl.col("grupo") == "otro")).with_columns(
        (pl.col("neta_teo_22") / 2).alias("x"), (pl.col("contrib_obs_sin_aseo_22") / 2 / 1000).alias("d")  # d en miles de $
    ).filter(pl.col("x") < 40_000)
    for nombre, m, c, unidad in (
        ("D2_kink_25pct", m2, 0.25, "Δ prob. de venta 2022–23 por +1,0 (100 pp) de alza pagada relativa"),
        ("D3_kink_9415", m3, float(CUOTA_MIN_GRADUAL_2022), "Δ prob. de venta 2022–23 por +$1.000 de cuota trimestral pagada"),
    ):
        covs = m.select("log_aval_21", "sup", "anio_constr").fill_null(0).to_numpy()
        y, x, d = m["vende"].to_numpy().astype(float), m["x"].to_numpy(), m["d"].to_numpy()
        out[nombre] = {
            "unidad": unidad,
            "tasa_venta_muestra": round(float(y.mean()), 4),
            "registrado": _rk_fuzzy(y, x, d, c),
            "DV2_con_covariables": _rk_fuzzy(y, x, d, c, covs),
        }
    return out


def main() -> None:
    import subprocess
    import sys

    if len(sys.argv) > 1:
        correr(sys.argv[1])
        return
    res = {}
    for nombre in list(MODELOS) + list(EVENTOS):
        r = subprocess.run([sys.executable, "-m", "src.models.estimar_p3", nombre], capture_output=True, text=True)
        if r.returncode != 0:
            res[nombre] = {"error": f"código {r.returncode}", "stderr": r.stderr[-500:]}
            continue
        res[nombre] = json.loads((REPORTES / f"p3_{nombre}.json").read_text())
    res |= d2_d3()
    p = pl.read_parquet(MARTS / "panel_d1.parquet")
    res["notas"] = {
        "sd_shock_semestral_$": round(float(p.select("rol_id", "delta_contrib_teo").unique()["delta_contrib_teo"].std())),
        "base_prob_venta_trimestral_G0_pre": round(float(p.filter((pl.col("post") == 0) & (pl.col("paga") == 1))["y1"].mean()), 5),
        "umbral_relevancia_pp_anual_por_100k": 0.4,
    }
    (REPORTES / "resultados_p3.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
