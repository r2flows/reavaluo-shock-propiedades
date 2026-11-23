"""Fase 7: predictor del reavalúo no agrícola 2027 por rol (Gran Santiago).

Método (calibrado con el reavalúo 2022):
  1. Terreno: el SII revalúa el suelo por área homogénea según los precios de mercado. Se modela por microbarrio:
       y = mediana log(T_nuevo / (T_previo · IPC))      (cambio real del componente terreno)
       X = brecha precio/avalúo del microbarrio en los 3 años previos (y de su comuna), crecimiento SPAR del barrio
           en los 4 años previos, nivel del valor de suelo y % de copropiedad.
     Backtest: con información hasta 2021 se predice el cambio 2021-2S → 2022-1S, dejando una comuna fuera a la vez (LOCO).
  2. Construcción: cambio real observado en 2022 por clase-calidad principal, en comunas sin cambio de factor comunal
     (incluye el cambio de tablas y el reinicio de la depreciación). Escenario "se repite 2022".
  3. Exento y cambio de tasa: suben en la misma proporción que el avalúo habitacional (regla verificada en 2022:
     exento +22,3% vs. avalúo habitacional nacional +22,1%). Tasas: escenario base ×0,957 (como en 2022,
     tope de +10% de recaudación); alternativo: sin cambio.
  4. Contribución 2027 por rol (src.features.contribucion.contribucion_teorica) y alza gradual del primer semestre.

Todos los montos de 2027 se expresan en $ del 2S-2026 (sin el reajuste IPC del 1S-2027).

Salidas:
  data/marts/reavaluo2027_roles.parquet
  data/staging/_reportes/reavaluo2027.json
Uso: scripts/correr.sh --mem 5G src.models.reavaluo2027
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl

from src.etl.common import MARTS, REF, REPORTES, STAGING
from src.features.contribucion import CUOTA_MIN_GRADUAL_2022, contribucion_teorica

IPC_22 = 1.051
K = 10
COLS = ["rol_id", "cod_comuna", "manzana", "destino", "avaluo_total", "avaluo_construccion_teo", "avaluo_terreno_teo",
        "sup_terreno_m2", "copropiedad", "clase_calidad_principal"]


def comp(sem: str) -> pl.DataFrame:
    return pl.read_parquet(STAGING / f"avaluo_componentes_{sem}.parquet", columns=COLS)


def micro() -> pl.DataFrame:
    return pl.read_parquet(STAGING / "map_barrio.parquet", columns=["cod_comuna", "manzana", "microbarrio_id", "barrio_id"])


def features(anios: tuple[int, int, int], spar_desde: int, spar_hasta: int, terreno: pl.DataFrame) -> pl.DataFrame:
    """Variables por microbarrio con información de los años dados (sin mirar el año del reavalúo)."""
    v = pl.read_parquet(MARTS / "fct_venta.parquet", columns=["microbarrio_id", "barrio_id", "cod_comuna", "anio", "ratio_ia", "outlier_precio", "primera_venta_obra_nueva"])
    v = v.filter(pl.col("anio").is_in(list(anios)) & pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    v = v.with_columns(pl.col("ratio_ia").log().alias("lr"))
    c = v.group_by("cod_comuna").agg(pl.col("lr").median().alias("lb_comuna"))
    m = v.group_by("microbarrio_id", "barrio_id", "cod_comuna").agg(pl.col("lr").median().alias("lb_m"), pl.len().alias("n_v"))
    m = m.join(c, on="cod_comuna").with_columns(((pl.col("n_v") * pl.col("lb_m") + K * pl.col("lb_comuna")) / (pl.col("n_v") + K)).alias("lb_micro"))
    sp = pl.read_parquet(MARTS / "indice_spar_barrio.parquet", columns=["barrio_id", "anio", "spar_log"])
    g = sp.filter(pl.col("anio") == spar_hasta).join(sp.filter(pl.col("anio") == spar_desde), on="barrio_id", suffix="_0").select(
        "barrio_id", (pl.col("spar_log") - pl.col("spar_log_0")).alias("spar_crec")
    )
    t = terreno.join(micro(), on=["cod_comuna", "manzana"], how="left").filter(pl.col("destino") == "H")
    nivel = t.group_by("microbarrio_id").agg(
        (pl.col("avaluo_terreno_teo") / pl.col("sup_terreno_m2")).filter((pl.col("sup_terreno_m2") > 0) & ~pl.col("copropiedad")).median().log().alias("log_suelo_m2"),
        pl.col("copropiedad").mean().alias("share_coprop"),
        pl.len().alias("n_roles"),
    )
    out = m.join(g, on="barrio_id", how="left").join(nivel, on="microbarrio_id", how="left")
    return out.with_columns(
        pl.col("spar_crec").fill_null(pl.col("spar_crec").median()),
        pl.col("log_suelo_m2").fill_null(pl.col("log_suelo_m2").median().over("cod_comuna")).fill_null(pl.col("log_suelo_m2").median()),
    )


X_COLS = ["lb_micro", "lb_comuna", "spar_crec", "log_suelo_m2", "share_coprop"]


def objetivo_terreno(a: pl.DataFrame, b: pl.DataFrame, f_ipc: float) -> pl.DataFrame:
    j = a.select("rol_id", "cod_comuna", "manzana", pl.col("avaluo_terreno_teo").alias("t0"), pl.col("sup_terreno_m2").alias("s0")).join(
        b.select("rol_id", pl.col("avaluo_terreno_teo").alias("t1"), pl.col("sup_terreno_m2").alias("s1")), on="rol_id"
    ).filter((pl.col("t0") > 0) & (pl.col("t1") > 0) & (pl.col("s0") == pl.col("s1")))
    j = j.with_columns((pl.col("t1") / (pl.col("t0") * f_ipc)).log().alias("dlt")).join(micro(), on=["cod_comuna", "manzana"], how="left")
    return j.group_by("microbarrio_id").agg(pl.col("dlt").median().alias("y"), pl.len().alias("n_obj"))


def _ols(X: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    Xc = np.column_stack([np.ones(len(X)), X])
    W = np.sqrt(w)[:, None]
    return np.linalg.lstsq(Xc * W, y * W[:, 0], rcond=None)[0]


def _pred(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def backtest(df: pl.DataFrame) -> tuple[dict, pl.DataFrame, np.ndarray]:
    d = df.drop_nulls(X_COLS + ["y"])
    X, y, w = d.select(X_COLS).to_numpy(), d["y"].to_numpy(), np.log1p(d["n_obj"].to_numpy())
    comunas = d["cod_comuna"].to_numpy()
    pred = np.empty(len(d))
    for c in np.unique(comunas):
        k = comunas == c
        beta = _ols(X[~k], y[~k], w[~k])
        pred[k] = _pred(beta, X[k])
    beta_full = _ols(X, y, w)
    ss = lambda e: float(np.average(e ** 2, weights=w))  # noqa: E731
    res = {
        "microbarrios": len(d),
        "coeficientes": dict(zip(["intercepto"] + X_COLS, [round(float(b), 4) for b in beta_full])),
        "rmse_LOCO": round(np.sqrt(ss(y - pred)), 4),
        "rmse_base_media_global": round(np.sqrt(ss(y - np.average(y, weights=w))), 4),
        "rmse_base_sin_cambio_real": round(np.sqrt(ss(y)), 4),
        "r2_LOCO_vs_media": round(1 - ss(y - pred) / ss(y - np.average(y, weights=w)), 4),
        "corr_LOCO": round(float(np.corrcoef(y, pred)[0, 1]), 4),
    }
    return res, d.with_columns(pl.Series("y_pred_loco", pred)), beta_full


def factor_construccion() -> pl.DataFrame:
    """Cambio real del componente construcción 2021→2022 por clase-calidad, en comunas sin cambio de factor comunal."""
    fc = pl.read_csv(REF / "factor_comunal.csv", separator=";").filter(pl.col("fc_2018") == pl.col("fc_2022"))["cod_comuna"].to_list()
    a, b = comp("2021_2"), comp("2022_1")
    j = a.select("rol_id", "cod_comuna", pl.col("avaluo_construccion_teo").alias("c0")).join(
        b.select("rol_id", "clase_calidad_principal", pl.col("avaluo_construccion_teo").alias("c1")), on="rol_id"
    ).filter(pl.col("cod_comuna").is_in(fc) & (pl.col("c0") > 0) & (pl.col("c1") > 0))
    return j.group_by("clase_calidad_principal").agg(
        (pl.col("c1") / (pl.col("c0") * IPC_22)).log().median().exp().alias("g_constr"), pl.len().alias("n")
    ).filter(pl.col("n") >= 50)


def evaluar_roles(dmb: pl.DataFrame, fac_c: pl.DataFrame) -> dict:
    """Error por rol del avalúo 2022 predicho (terreno LOCO; construcción por factor de clase o con el oráculo de tablas)."""
    a, b = comp("2021_2"), comp("2022_1")
    j = a.join(b.select("rol_id", pl.col("avaluo_total").alias("A22"), pl.col("avaluo_construccion_teo").alias("C22")), on="rol_id").filter(
        (pl.col("destino") == "H") & (pl.col("avaluo_total") > 0)
    ).join(micro(), on=["cod_comuna", "manzana"], how="left").join(dmb.select("microbarrio_id", "y_pred_loco"), on="microbarrio_id", how="left")
    j = j.join(fac_c, on="clase_calidad_principal", how="left").with_columns(pl.col("g_constr").fill_null(1.0), pl.col("y_pred_loco").fill_null(0.0))
    t_hat = pl.col("avaluo_terreno_teo").clip(lower_bound=0) * IPC_22 * pl.col("y_pred_loco").exp()
    j = j.with_columns(
        (t_hat + pl.col("avaluo_construccion_teo") * IPC_22 * pl.col("g_constr")).alias("A_hat"),
        (t_hat + pl.col("C22")).alias("A_hat_oraculo_constr"),
        (pl.col("avaluo_total") * IPC_22).alias("A_base_ipc"),
    )
    out = {}
    for nombre in ("A_hat", "A_hat_oraculo_constr", "A_base_ipc"):
        e = (j[nombre] / j["A22"] - 1).abs()
        out[nombre] = {"error_abs_mediano_pct": round(float(e.median()) * 100, 2), "share_error_<10pct": round(float((e < 0.10).mean()), 4)}
    out["n_roles"] = j.height
    return out


CIERRE_2022 = None  # se calcula: log(brecha 2019–21) − log(brecha 2022–23), mediana entre comunas
TRASPASO_COMUNAL = 0.45
ESCENARIOS = {  # fracción del cierre de brecha de 2022 que el SII repetiría en 2027
    "S0_mantiene_razon_2022": 0.0,
    "S2_cierre_medio": 0.5,
    "S1_repite_cierre_2022": 1.0,
}


def brecha_comunal(anios: list[int]) -> pl.DataFrame:
    v = pl.read_parquet(MARTS / "fct_venta.parquet", columns=["cod_comuna", "anio", "ratio_ia", "outlier_precio", "primera_venta_obra_nueva"])
    v = v.filter(pl.col("anio").is_in(anios) & pl.col("ratio_ia").is_not_null() & ~pl.col("outlier_precio") & ~pl.col("primera_venta_obra_nueva"))
    return v.group_by("cod_comuna").agg(pl.col("ratio_ia").log().median().alias("lb"))


def proyectar_2027(rep: dict) -> pl.DataFrame:
    """Avalúo y contribución 2027 por rol en tres escenarios de nivel (alza uniforme dentro de cada comuna).

    Nivel por comuna:  L_c = max(0, m̄ + 0,45·(m_c − m̄) + f · cierre_2022),  m_c = lb_c(2024–26) − lb_c(2022–23)
      - el primer término es lo que el mercado se movió frente al avalúo desde el reavalúo 2022 (mantener la razón);
      - f · cierre_2022 es un cierre adicional de la brecha como el de 2022 (f = 0; 0,5; 1).
    Tasas: regla del tope de +10% de recaudación (aproximada con el Gran Santiago, todos los destinos).
    Exento y cambio de tasa: × crecimiento del avalúo habitacional.
    """
    b1921, b2223, b2426 = brecha_comunal([2019, 2020, 2021]), brecha_comunal([2022, 2023]), brecha_comunal([2024, 2025, 2026])
    cierre = b1921.join(b2223, on="cod_comuna", suffix="_22").select((pl.col("lb") - pl.col("lb_22")).alias("c"))["c"].median()
    mov = b2426.join(b2223, on="cod_comuna", suffix="_22").select("cod_comuna", (pl.col("lb") - pl.col("lb_22")).alias("mov_mercado"))
    # Calibración comunal 2022: el SII traspasó ~45% de las diferencias de brecha entre comunas
    # (pendiente 0,45; corr 0,32–0,48; n = 36) y ninguna comuna bajó su avalúo real (mínimo +8%).
    med = float(mov["mov_mercado"].median())
    mov = mov.with_columns((med + TRASPASO_COMUNAL * (pl.col("mov_mercado") - med)).alias("mov_mercado"))
    rep["cierre_brecha_2022_log"] = round(float(cierre), 4)
    rep["traspaso_comunal_calibrado_2022"] = TRASPASO_COMUNAL
    rep["movimiento_mercado_vs_avaluo_2022_2026_mediana_log"] = round(float(mov["mov_mercado"].median()), 4)

    r = comp("2026_2").join(mov, on="cod_comuna", how="left").with_columns(pl.col("mov_mercado").fill_null(0.0))
    c26 = pl.read_parquet(STAGING / "contribucion_2026_2.parquet", columns=["rol_id", "avaluo_exento", "exento_h_semestre", "cambio_tasa_semestre", "contrib_teo", "contrib_neta_teo", "exencion_especial"])
    p26 = {"exento_h": float(c26["exento_h_semestre"][0]), "cambio_tasa": float(c26["cambio_tasa_semestre"][0])}
    r = r.join(c26.drop("exento_h_semestre", "cambio_tasa_semestre"), on="rol_id", how="left").with_columns(pl.col("contrib_teo").fill_null(0.0), pl.col("contrib_neta_teo").fill_null(0.0))
    giro26 = float(r["contrib_teo"].sum())
    cuota_min = CUOTA_MIN_GRADUAL_2022 * p26["exento_h"] / 47_360_490
    rep["escenarios"] = {}
    for esc, f in ESCENARIOS.items():
        A = pl.col("avaluo_total") * (pl.col("mov_mercado") + f * cierre).clip(lower_bound=0.0).exp()  # piso: sin baja real
        x = r.with_columns(A.alias("A27"))
        h = x.filter(pl.col("destino") == "H")
        g_h = float(h["A27"].sum() / h["avaluo_total"].sum())
        base = {"exento_h": p26["exento_h"] * g_h, "cambio_tasa": p26["cambio_tasa"] * g_h, "sobretasa": 0.00025}

        def calc(ft: float) -> pl.DataFrame:
            p = base | {"t1": 0.00893 * ft, "t2": 0.01042 * ft, "t_no_h": 0.01042 * ft}
            y = x.with_columns(
                pl.when(pl.col("exencion_especial").fill_null(False))
                .then(pl.col("avaluo_exento") * pl.col("A27") / pl.col("avaluo_total"))
                .when(pl.col("destino") == "H")
                .then(pl.min_horizontal(pl.col("A27"), pl.lit(p["exento_h"])))
                .otherwise(pl.col("avaluo_exento"))
                .alias("avaluo_exento"),
                pl.col("A27").alias("avaluo_total"),
            ).select("rol_id", "destino", "avaluo_total", "avaluo_exento")
            return contribucion_teorica(y, p), p

        y1, _ = calc(1.0)
        ft = min(1.0, 1.10 * giro26 / float(y1["contrib_teo"].sum()))
        y, p = calc(ft) if ft < 1 else (y1, base | {"t1": 0.00893, "t2": 0.01042, "t_no_h": 0.01042})
        suf = esc.split("_")[0]
        r = r.join(
            y.select("rol_id", pl.col("avaluo_total").alias(f"avaluo_27_{suf}"), pl.col("contrib_teo").alias(f"contrib_27_{suf}"), pl.col("contrib_neta_teo").alias(f"neta_27_{suf}")),
            on="rol_id",
        ).with_columns(
            ((pl.col("contrib_teo") <= 0) & (pl.col(f"contrib_27_{suf}") > 0)).alias(f"pasa_a_afecto_{suf}"),
            ((pl.col("contrib_teo") > 0) & (pl.col(f"contrib_27_{suf}") <= 0)).alias(f"pasa_a_exento_{suf}"),
            ((pl.col(f"neta_27_{suf}") / 2 > cuota_min) & (pl.col(f"neta_27_{suf}") > 1.25 * pl.col("contrib_neta_teo"))).alias(f"alza_gradual_{suf}"),
        )
        hh = r.filter(pl.col("destino") == "H")
        sube = (hh[f"contrib_27_{suf}"] - hh["contrib_teo"]) * 2
        rep["escenarios"][esc] = {
            "alza_real_avaluo_habitacional_pct": round((g_h - 1) * 100, 1),
            "factor_tasas_tope_10pct": round(ft, 4),
            "exento_h_$2S2026": round(p["exento_h"]),
            "t1_t2_pct": [round(p["t1"] * 100, 3), round(p["t2"] * 100, 3)],
            "viviendas_pasan_a_afecto": int(hh[f"pasa_a_afecto_{suf}"].sum()),
            "viviendas_pasan_a_exento": int(hh[f"pasa_a_exento_{suf}"].sum()),
            "viviendas_con_alza_gradual": int(hh[f"alza_gradual_{suf}"].sum()),
            "alza_anual_mediana_$_entre_las_que_suben": round(float(sube.filter(sube > 0).median() or 0)),
            "viviendas_con_alza_anual_>$200mil": int((sube > 200_000).sum()),
            "recaudacion_habitacional_cambio_pct": round((float(hh[f"contrib_27_{suf}"].sum()) / float(hh["contrib_teo"].sum()) - 1) * 100, 1),
        }
    return r


def main() -> None:
    rep: dict = {}
    a21, a22 = comp("2021_2"), comp("2022_1")
    obj = objetivo_terreno(a21, a22, IPC_22)
    f = features((2019, 2020, 2021), 2017, 2021, a21)
    d = obj.join(f, on="microbarrio_id", how="inner").filter(pl.col("n_obj") >= 10)
    rep["backtest_terreno_2022"], dmb, _ = backtest(d)
    fac_c = factor_construccion()
    rep["backtest_avaluo_por_rol_2022"] = evaluar_roles(dmb, fac_c)
    rep["conclusion_backtest"] = (
        "La variación entre microbarrios del alza del SII es poco predecible con datos de mercado (R² LOCO ≈ 0,12); "
        "el error por rol (~9%) depende sobre todo de acertar el nivel. 2027 se proyecta por escenarios de nivel, uniformes dentro de cada comuna."
    )
    del a21, a22, obj, f, d
    r = proyectar_2027(rep)
    r.write_parquet(MARTS / "reavaluo2027_roles.parquet", compression="zstd")
    h = r.filter(pl.col("destino") == "H")
    por_comuna = h.group_by("cod_comuna").agg(
        pl.len().alias("viviendas"),
        ((pl.col("avaluo_27_S1") / pl.col("avaluo_total")).median() * 100 - 100).round(1).alias("alza_avaluo_S1_pct"),
        ((pl.col("avaluo_27_S0") / pl.col("avaluo_total")).median() * 100 - 100).round(1).alias("alza_avaluo_S0_pct"),
        pl.col("pasa_a_afecto_S0").sum().alias("afecto_S0"),
        pl.col("pasa_a_afecto_S2").sum().alias("afecto_S2"),
        pl.col("pasa_a_afecto_S1").sum().alias("afecto_S1"),
    ).sort("afecto_S1", descending=True)
    por_comuna.write_csv(REPORTES / "reavaluo2027_por_comuna.csv")
    (REPORTES / "reavaluo2027.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    print(por_comuna.head(10))


if __name__ == "__main__":
    main()
