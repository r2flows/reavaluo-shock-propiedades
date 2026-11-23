"""Ventas de mercado con avalúo a la fecha de la escritura y ratio precio/avalúo (ratio_ia).

Avalúo en UF a la fecha de venta. Entre reavalúos el SII reajusta los avalúos por IPC cada semestre,
igual que la UF, así que el avalúo en UF es casi constante dentro de cada período de vigencia:
  escritura 2018-01-01 … 2021-12-31 → avalúo 2021-2S / UF(2021-07-01)   (reavalúo 2018)
  escritura ≥ 2022-01-01            → avalúo 2022-1S / UF(2022-01-01)   (reavalúo 2022)
                                      si el rol no existe en 2022-1S: avalúo 2026-2S / UF(2026-07-01)
  escritura < 2018                  → sin avalúo (no tenemos el catastro del reavalúo 2014)
El avalúo de la escritura suma todos sus roles (depto + bodega + estacionamiento).

Filtros de calidad (se marcan, no se borran):
  outlier_precio: monto < 200 UF o ratio_ia fuera de [0,3 ; 15]

Salida: data/marts/fct_venta.parquet (una fila por escritura habitacional con precio)
Uso: python -m src.features.ventas
"""

from __future__ import annotations

from datetime import date

import polars as pl

from src.etl.common import MARTS, STAGING, Reporte

REGIMENES = [  # (semestre catastro, fecha UF, desde, hasta)
    ("2021_2", date(2021, 7, 1), date(2018, 1, 1), date(2021, 12, 31)),
    ("2022_1", date(2022, 1, 1), date(2022, 1, 1), date(2100, 1, 1)),
]


def avaluo_uf() -> pl.DataFrame:
    uf = pl.read_parquet(STAGING / "uf.parquet")
    u = lambda d: uf.filter(pl.col("fecha") == d)["uf"][0]  # noqa: E731
    a21 = pl.read_parquet(STAGING / "catastro" / "roles_2021_2.parquet").select(
        "rol_id", (pl.col("avaluo_total") / u(date(2021, 7, 1))).alias("aval_uf_r2018")
    )
    a22 = pl.read_parquet(STAGING / "catastro" / "roles_2022_1.parquet").select(
        "rol_id", (pl.col("avaluo_total") / u(date(2022, 1, 1))).alias("aval_uf_r2022a")
    )
    a26 = pl.read_parquet(STAGING / "catastro" / "roles_2026_2.parquet").select(
        "rol_id", (pl.col("avaluo_total") / u(date(2026, 7, 1))).alias("aval_uf_r2022b")
    )
    return a26.join(a22, on="rol_id", how="full", coalesce=True).join(a21, on="rol_id", how="full", coalesce=True)


def main() -> None:
    rep = Reporte("fct_venta")
    tr = pl.read_parquet(STAGING / "fct_transferencia.parquet").filter(pl.col("escritura_id").is_not_null())
    av = avaluo_uf()
    tr = tr.join(av, on="rol_id", how="left").with_columns(
        pl.when(pl.col("fecha_escritura") >= date(2022, 1, 1))
        .then(pl.coalesce("aval_uf_r2022a", "aval_uf_r2022b"))
        .when(pl.col("fecha_escritura") >= date(2018, 1, 1))
        .then(pl.col("aval_uf_r2018"))
        .otherwise(None)
        .alias("aval_uf_rol")
    )
    aval_esc = tr.group_by("escritura_id").agg(
        pl.col("aval_uf_rol").sum().alias("avaluo_uf"),
        pl.col("aval_uf_rol").is_null().any().alias("avaluo_incompleto"),
        # Avalúo fijo de referencia (vigente 2S-2026) para el índice SPAR: mismo valor para todas las fechas
        pl.col("aval_uf_r2022b").sum().alias("avaluo_uf_ref"),
        pl.col("aval_uf_r2022b").is_null().any().alias("avaluo_ref_incompleto"),
    )

    e = pl.read_parquet(STAGING / "fct_escritura.parquet")
    rep.entrada = e.height
    n = e.height
    e = e.filter(pl.col("destino_principal") == "H")
    rep.descartar("no_habitacional", n - e.height)
    n = e.height
    e = e.filter(pl.col("monto_uf") > 0)
    rep.descartar("sin_monto", n - e.height)

    comp = pl.read_parquet(STAGING / "avaluo_componentes_2026_2.parquet").select(
        pl.col("rol_id").alias("rol_principal"), "sup_construida_total", "copropiedad", "anio_construccion_max"
    )
    barrios = pl.read_parquet(STAGING / "map_barrio.parquet").select("cod_comuna", "manzana", "microbarrio_id", "barrio_id")
    v = (
        e.join(aval_esc, on="escritura_id", how="left")
        .join(comp, on="rol_principal", how="left")
        .join(barrios, on=["cod_comuna", "manzana"], how="left")
        .with_columns(
            pl.when(~pl.col("avaluo_incompleto") & (pl.col("avaluo_uf") > 0))
            .then(pl.col("monto_uf") / pl.col("avaluo_uf"))
            .otherwise(None)
            .alias("ratio_ia"),
            pl.col("fecha_escritura").dt.year().alias("anio"),
            (pl.col("fecha_escritura").dt.year().cast(pl.Utf8) + "_" + pl.when(pl.col("fecha_escritura").dt.month() <= 6).then(pl.lit("1")).otherwise(pl.lit("2"))).alias("semestre"),
            pl.when(pl.col("sup_construida_total") > 0).then(pl.col("monto_uf") / pl.col("sup_construida_total")).otherwise(None).alias("uf_m2"),
        )
        .with_columns(
            (
                (pl.col("monto_uf") < 200)
                | (pl.col("ratio_ia").is_not_null() & ~pl.col("ratio_ia").is_between(0.3, 15))
            ).alias("outlier_precio")
        )
    )
    v.write_parquet(MARTS / "fct_venta.parquet", compression="zstd")
    rep.notas["con_ratio_ia"] = v.filter(pl.col("ratio_ia").is_not_null()).height
    rep.notas["outlier_precio"] = int(v["outlier_precio"].sum())
    rep.notas["sin_barrio"] = v.filter(pl.col("barrio_id").is_null()).height
    rep.notas["obra_nueva"] = int(v["primera_venta_obra_nueva"].sum())
    rep.cerrar(v.height)


if __name__ == "__main__":
    main()
