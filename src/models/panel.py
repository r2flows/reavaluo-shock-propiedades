"""Panel rol × trimestre para P3 (docs/analysis_plan.md §2).

Muestra base (§2.1): roles habitacionales en 2021-2S y 2022-1S, sin cambio de superficie, sin exención especial
(ninguno de los dos semestres), existentes en 2021-2S. Trimestres 2018-T1 … 2025-T4 (q = 0 … 31; post: q ≥ 16).

Resultados (§2.2):
  y1 = el rol es rol principal de una compraventa con monto > 0 en el trimestre
       (ventas de segunda mano: sin obra nueva y sin outliers de precio)
  y2 = el rol tiene una transferencia sin monto en el trimestre (proxy de herencia/adjudicación)

Grupos (§2.3): G_AM = rebaja_21 "100%" ; G_0 = rebaja_21 "ninguna" ; resto = "otro" (fuera de D1).
Tratamiento D1: shock = delta_contrib_teo estandarizado en la muestra D1 (G_AM ∪ G_0); paga = 1 si G_0.

Salidas:
  data/marts/panel_roles.parquet   (atributos por rol, toda la muestra base)
  data/marts/panel_d1.parquet      (rol × trimestre, solo G_AM ∪ G_0)

Uso: python -m src.models.panel
"""

from __future__ import annotations

import polars as pl

from src.etl.common import MARTS, STAGING, Reporte

Q_INI, Q_FIN, Q_POST = (2018, 1), (2025, 4), 16


def trimestre(fecha: pl.Expr) -> pl.Expr:
    return (fecha.dt.year() - Q_INI[0]) * 4 + (fecha.dt.month() - 1) // 3


def roles_base(rep: Reporte) -> pl.DataFrame:
    s = pl.read_parquet(MARTS / "shock_2022.parquet")
    rep.entrada = s.height
    esp = []
    for sem in ("2021_2", "2022_1"):
        c = pl.read_parquet(STAGING / f"contribucion_{sem}.parquet").select("rol_id", pl.col("exencion_especial").alias(f"esp_{sem}"))
        esp.append(c)
    s = s.join(esp[0], on="rol_id", how="left").join(esp[1], on="rol_id", how="left")
    reglas = [
        ("no_habitacional", ~((pl.col("destino_21") == "H") & (pl.col("destino_22") == "H"))),
        ("cambio_superficie", pl.col("cambio_superficie").fill_null(True)),
        ("exencion_especial", pl.col("esp_2021_2").fill_null(True) | pl.col("esp_2022_1").fill_null(True)),
    ]
    for motivo, cond in reglas:
        rep.descartar(motivo, s.filter(cond).height)
        s = s.filter(~cond)
    barrios = pl.read_parquet(STAGING / "map_barrio.parquet").select("cod_comuna", "manzana", "microbarrio_id", "barrio_id")
    s = s.join(barrios, on=["cod_comuna", "manzana"], how="left")
    return s.with_columns(
        pl.when(pl.col("rebaja_21") == "100%")
        .then(pl.lit("G_AM"))
        .when(pl.col("rebaja_21") == "ninguna")
        .then(pl.lit("G_0"))
        .otherwise(pl.lit("otro"))
        .alias("grupo"),
        pl.col("avaluo_total_21").qcut(10, labels=[f"d{i}" for i in range(1, 11)], allow_duplicates=True).cast(pl.Utf8).alias("decil_avaluo_21"),
        pl.col("anio_construccion_max").fill_null(0).alias("anio_constr"),
    )


def eventos() -> tuple[pl.DataFrame, pl.DataFrame]:
    v = pl.read_parquet(MARTS / "fct_venta.parquet").filter(
        ~pl.col("primera_venta_obra_nueva") & ~pl.col("outlier_precio") & (pl.col("monto_uf") > 0)
    )
    y1 = v.select(pl.col("rol_principal").alias("rol_id"), trimestre(pl.col("fecha_escritura")).alias("q")).unique().with_columns(pl.lit(1).alias("y1"))
    t = pl.read_parquet(STAGING / "fct_transferencia.parquet").filter(
        pl.col("monto_uf_norm").is_null() | (pl.col("monto_uf_norm") <= 0)
    )
    y2 = t.select("rol_id", trimestre(pl.col("fecha_escritura")).alias("q")).unique().with_columns(pl.lit(1).alias("y2"))
    return y1, y2


def main() -> None:
    rep = Reporte("panel_roles")
    r = roles_base(rep)
    r.write_parquet(MARTS / "panel_roles.parquet", compression="zstd")
    rep.notas["por_grupo"] = dict(r.group_by("grupo").len().sort("grupo").iter_rows())
    rep.notas["G_AM_mantiene_rebaja_100_en_2022"] = round(
        r.filter(pl.col("grupo") == "G_AM").select((pl.col("rebaja_22") == "100%").mean()).item(), 4
    )
    rep.cerrar(r.height)

    rep = Reporte("panel_d1")
    d1 = r.filter(pl.col("grupo").is_in(["G_AM", "G_0"]))
    mu, sd = d1["delta_contrib_teo"].mean(), d1["delta_contrib_teo"].std()
    d1 = d1.with_columns(
        ((pl.col("delta_contrib_teo") - mu) / sd).alias("shock"),
        (pl.col("grupo") == "G_0").cast(pl.Int8).alias("paga"),
    ).select(
        "rol_id", "cod_comuna", "barrio_id", "microbarrio_id", "grupo", "paga", "shock", "delta_contrib_teo",
        "delta_contrib_pagada_teo", "decil_avaluo_21", "sup_construida_total", "anio_constr", "copropiedad",
        "clase_calidad_principal", "rebaja_22",
    )
    rep.entrada = d1.height
    qs = pl.DataFrame({"q": list(range(0, (Q_FIN[0] - Q_INI[0]) * 4 + Q_FIN[1]))}, schema={"q": pl.Int32})
    y1, y2 = eventos()
    p = (
        d1.join(qs, how="cross")
        .join(y1.with_columns(pl.col("q").cast(pl.Int32)), on=["rol_id", "q"], how="left")
        .join(y2.with_columns(pl.col("q").cast(pl.Int32)), on=["rol_id", "q"], how="left")
        .with_columns(
            pl.col("y1").fill_null(0).cast(pl.Int8),
            pl.col("y2").fill_null(0).cast(pl.Int8),
            (pl.col("q") >= Q_POST).cast(pl.Int8).alias("post"),
        )
    )
    p.write_parquet(MARTS / "panel_d1.parquet", compression="zstd")
    rep.notas["roles"] = d1.height
    rep.notas["shock_media_sd_pesos_semestrales"] = (round(mu), round(sd))
    rep.notas["tasa_trimestral_y1_pre_por_grupo"] = {
        g: round(x, 5) for g, x in p.filter(pl.col("post") == 0).group_by("grupo").agg(pl.col("y1").mean()).iter_rows()
    }
    rep.cerrar(p.height)


if __name__ == "__main__":
    main()
