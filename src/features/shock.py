"""Mart del shock del reavalúo 2022 a nivel de rol (2021-2S → 2022-1S).

Entradas: data/staging/contribucion_{2021_2,2022_1}.parquet y avaluo_componentes_{2021_2,2022_1}.parquet
Salida:   data/marts/shock_2022.parquet

Variables clave:
  ratio_avaluo, delta_contrib_teo (sin gradualidad), delta_contrib_pagada_teo (con gradualidad)
  pasa_a_afecto / pasa_a_exento
  Separación del alza de avalúo (en pesos del 1S-2022):
    delta_construccion_mecanico = construcción 2022 (tablas 2022, FC 2022) − construcción 2021 reajustada por IPC
      → cambio de tablas, factor comunal y depreciación: no depende del mercado del barrio
    delta_terreno = terreno 2022 − terreno 2021 reajustado por IPC → refleja precios de suelo (área homogénea)
  rebaja_21 / rebaja_22: huella del beneficio de adulto mayor ("100%", "50%", "ninguna", "otra")

Uso: python -m src.features.shock
"""

from __future__ import annotations

import polars as pl

from src.etl.common import MARTS, STAGING, Reporte
from src.features.contribucion import FACTOR_ACTUALIZACION_BASE_2022


def main() -> None:
    c21 = pl.read_parquet(STAGING / "contribucion_2021_2.parquet")
    c22 = pl.read_parquet(STAGING / "contribucion_2022_1.parquet")
    k21 = pl.read_parquet(STAGING / "avaluo_componentes_2021_2.parquet")
    k22 = pl.read_parquet(STAGING / "avaluo_componentes_2022_1.parquet")
    f = FACTOR_ACTUALIZACION_BASE_2022  # 2S-2021 → 1S-2022

    cols = ["avaluo_total", "avaluo_exento", "avaluo_afecto", "contrib_teo", "contrib_semestral", "contrib_obs_sin_aseo", "destino", "rebaja_obs"]
    a = c21.select("rol_id", *cols).rename({c: f"{c}_21" for c in cols}).rename({"rebaja_obs_21": "rebaja_21"})
    b = c22.select("rol_id", "cod_comuna", "manzana", *cols, "contrib_teo_gradual", "con_alza_gradual").rename(
        {c: f"{c}_22" for c in cols}
    ).rename({"rebaja_obs_22": "rebaja_22"})
    comp = ["avaluo_construccion_teo", "avaluo_terreno_teo", "sup_terreno_m2", "sup_construida_total", "copropiedad", "anio_construccion_max", "clase_calidad_principal"]
    ka = k21.select("rol_id", "avaluo_construccion_teo", "avaluo_terreno_teo", "sup_construida_total").rename(
        {"avaluo_construccion_teo": "construccion_21", "avaluo_terreno_teo": "terreno_21", "sup_construida_total": "sup_construida_21"}
    )
    kb = k22.select("rol_id", *comp).rename({"avaluo_construccion_teo": "construccion_22", "avaluo_terreno_teo": "terreno_22"})

    rep = Reporte("mart_shock_2022")
    rep.entrada = c22.height
    s = b.join(a, on="rol_id", how="inner")
    rep.descartar("rol_sin_2021_2", c22.height - s.height)
    s = s.join(ka, on="rol_id", how="left").join(kb, on="rol_id", how="left")

    s = s.with_columns(
        (pl.col("avaluo_total_22") / pl.col("avaluo_total_21")).alias("ratio_avaluo"),
        (pl.col("contrib_teo_22") - pl.col("contrib_teo_21")).alias("delta_contrib_teo"),
        (pl.col("contrib_teo_gradual") - pl.col("contrib_teo_21")).alias("delta_contrib_pagada_teo"),
        (pl.col("contrib_obs_sin_aseo_22") - pl.col("contrib_obs_sin_aseo_21")).alias("delta_contrib_obs"),
        ((pl.col("contrib_teo_21") <= 0) & (pl.col("contrib_teo_22") > 0)).alias("pasa_a_afecto"),
        ((pl.col("contrib_teo_21") > 0) & (pl.col("contrib_teo_22") <= 0)).alias("pasa_a_exento"),
        # Componentes del alza del avalúo, en pesos del 1S-2022
        (pl.col("avaluo_total_22") - f * pl.col("avaluo_total_21")).alias("delta_avaluo_real"),
        (pl.col("construccion_22") - f * pl.col("construccion_21")).alias("delta_construccion_mecanico"),
        (pl.col("terreno_22") - f * pl.col("terreno_21")).alias("delta_terreno"),
        (pl.col("sup_construida_total") != pl.col("sup_construida_21")).alias("cambio_superficie"),
    ).with_columns(
        pl.when(pl.col("contrib_teo_21") > 0)
        .then(pl.col("delta_contrib_teo") / pl.col("contrib_teo_21"))
        .otherwise(None)
        .alias("shock_pct_teo"),
        pl.when(pl.col("delta_avaluo_real").abs() > 0)
        .then(pl.col("delta_construccion_mecanico") / pl.col("delta_avaluo_real"))
        .otherwise(None)
        .alias("share_alza_mecanica"),
    )
    MARTS.mkdir(parents=True, exist_ok=True)
    s.write_parquet(MARTS / "shock_2022.parquet", compression="zstd")

    h = s.filter((pl.col("destino_22") == "H") & (pl.col("destino_21") == "H") & ~pl.col("cambio_superficie"))
    rep.notas["H_misma_superficie"] = h.height
    rep.notas["H_pasa_a_afecto"] = int(h["pasa_a_afecto"].sum())
    rep.notas["H_pasa_a_exento"] = int(h["pasa_a_exento"].sum())
    rep.notas["rebaja_21"] = dict(h.group_by("rebaja_21").len().sort("len", descending=True).iter_rows())
    rep.notas["consistencia_rebaja_100_o_50_entre_semestres"] = round(
        h.filter(pl.col("rebaja_21").is_in(["100%", "50%"]) & pl.col("rebaja_22").is_not_null())
        .select((pl.col("rebaja_21") == pl.col("rebaja_22")).mean())
        .item(),
        4,
    )
    rep.cerrar(s.height)


if __name__ == "__main__":
    main()
