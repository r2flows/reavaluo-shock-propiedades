"""Definición de barrios sin coordenadas: tramos de manzanas consecutivas con valor de suelo similar.

El catastro no trae el área homogénea (AHV) ni coordenadas. Se usan dos regularidades:
  1. El SII numera las manzanas por sectores contiguos dentro de la comuna.
  2. El terreno se valora por área homogénea, así que el valor del suelo por m² (de la
     separación terreno/construcción) es casi constante dentro de un área.

Algoritmo (por comuna):
  - Valor de cada manzana = mediana del terreno/m² de sus casas (2022-1S). Las manzanas sin casas
    (solo departamentos) heredan el valor de la manzana anterior con valor.
  - Se recorren las manzanas en orden. Se abre un tramo nuevo si el valor se aleja más de SALTO_LOG
    del valor de referencia del tramo, si el número de manzana salta más de SALTO_NUM o si el tramo
    llega a MAX_MANZANAS.
  - Los tramos con menos de MIN_VENTAS ventas con precio (2010–2026) se fusionan con el siguiente
    (o con el anterior, si es el último).

Es una aproximación: falta validar la contigüidad con cartografía (pendiente).

Salida: data/staging/map_barrio.parquet (cod_comuna, manzana, microbarrio_id, barrio_id, valor_suelo_m2)
Dos escalas: microbarrio (≥ 300 ventas 2010–2026, para brecha y variables) y barrio (≥ 1.800, para índices).
Uso: python -m src.features.barrios
"""

from __future__ import annotations

import math

import polars as pl

from src.etl.common import STAGING, Reporte

SALTO_LOG = 0.15
SALTO_NUM = 20
MAX_MANZANAS = 40
MIN_VENTAS = 300  # microbarrio
MIN_VENTAS_BARRIO = 1800  # barrio: ~110 ventas/año → IC95 del retorno ≈ ±10%


def valor_manzanas() -> pl.DataFrame:
    comp = pl.read_parquet(STAGING / "avaluo_componentes_2022_1.parquet")
    casas = comp.filter(
        (pl.col("destino") == "H") & ~pl.col("copropiedad") & (pl.col("sup_terreno_m2") > 0) & (pl.col("terreno_m2_teo") > 0)
    )
    valor = casas.group_by("cod_comuna", "manzana").agg(pl.col("terreno_m2_teo").median().alias("valor_suelo_m2"))
    todas = pl.read_parquet(STAGING / "catastro" / "roles_2026_2.parquet").select("cod_comuna", "manzana").unique()
    return (
        todas.join(valor, on=["cod_comuna", "manzana"], how="left")
        .sort("cod_comuna", "manzana")
        .with_columns(pl.col("valor_suelo_m2").forward_fill().backward_fill().over("cod_comuna"))
    )


def ventas_por_manzana() -> pl.DataFrame:
    e = pl.read_parquet(STAGING / "fct_escritura.parquet")
    return (
        e.filter((pl.col("destino_principal") == "H") & (pl.col("monto_uf") > 0))
        .group_by("cod_comuna", "manzana")
        .len("ventas")
    )


def segmentar(man: pl.DataFrame) -> list[int]:
    """Devuelve el número de tramo de cada manzana (ordenadas por número)."""
    tramos, actual = [], 0
    ref, n_en_tramo, prev = None, 0, None
    for num, v in zip(man["manzana"], man["valor_suelo_m2"]):
        lv = math.log(v) if v and v > 0 else None
        nuevo = (
            prev is not None
            and (
                (num - prev > SALTO_NUM)
                or n_en_tramo >= MAX_MANZANAS
                or (lv is not None and ref is not None and abs(lv - ref) > SALTO_LOG)
            )
        )
        if nuevo:
            actual += 1
            ref, n_en_tramo = None, 0
        if ref is None and lv is not None:
            ref = lv
        tramos.append(actual)
        n_en_tramo += 1
        prev = num
    return tramos


def fusionar(df: pl.DataFrame, minimo: int = MIN_VENTAS) -> pl.DataFrame:
    """Fusiona tramos con pocas ventas con el tramo siguiente (o el anterior si es el último)."""
    while True:
        tot = df.group_by("tramo").agg(pl.col("ventas").sum()).sort("tramo")
        chicos = tot.filter(pl.col("ventas") < minimo)
        if chicos.is_empty() or tot.height == 1:
            return df
        t = chicos["tramo"][0]
        orden = tot["tramo"].to_list()
        i = orden.index(t)
        destino = orden[i + 1] if i + 1 < len(orden) else orden[i - 1]
        df = df.with_columns(pl.when(pl.col("tramo") == t).then(destino).otherwise(pl.col("tramo")).alias("tramo"))


def main() -> None:
    rep = Reporte("barrios")
    man = valor_manzanas().join(ventas_por_manzana(), on=["cod_comuna", "manzana"], how="left").with_columns(
        pl.col("ventas").fill_null(0)
    )
    rep.entrada = man.height
    partes = []
    for cod in man["cod_comuna"].unique().sort():
        m = man.filter(pl.col("cod_comuna") == cod).sort("manzana")
        m = m.with_columns(pl.Series("tramo", segmentar(m)))
        m = fusionar(m, MIN_VENTAS)
        orden = {t: i + 1 for i, t in enumerate(m["tramo"].unique(maintain_order=True))}
        m = m.with_columns(
            pl.format("{}-M{}", pl.col("cod_comuna"), pl.col("tramo").replace_strict(orden).cast(pl.Utf8).str.zfill(3)).alias("microbarrio_id")
        )
        # Barrio: fusión de microbarrios contiguos hasta MIN_VENTAS_BARRIO
        m = fusionar(m, MIN_VENTAS_BARRIO)
        orden = {t: i + 1 for i, t in enumerate(m["tramo"].unique(maintain_order=True))}
        m = m.with_columns(
            pl.format("{}-B{}", pl.col("cod_comuna"), pl.col("tramo").replace_strict(orden).cast(pl.Utf8).str.zfill(2)).alias("barrio_id")
        )
        partes.append(m)
    out = pl.concat(partes).select("cod_comuna", "manzana", "microbarrio_id", "barrio_id", "valor_suelo_m2", "ventas")
    out.write_parquet(STAGING / "map_barrio.parquet")
    resumen = out.group_by("cod_comuna", "barrio_id").agg(pl.len().alias("manzanas"), pl.col("ventas").sum())
    rep.notas["barrios_por_comuna"] = dict(resumen.group_by("cod_comuna").len().sort("cod_comuna").iter_rows())
    rep.notas["microbarrios_por_comuna"] = dict(
        out.select("cod_comuna", "microbarrio_id").unique().group_by("cod_comuna").len().sort("cod_comuna").iter_rows()
    )
    rep.notas["manzanas_por_barrio_mediana"] = resumen["manzanas"].median()
    rep.notas["ventas_por_barrio_mediana"] = resumen["ventas"].median()
    rep.notas["ventas_por_barrio_min"] = resumen["ventas"].min()
    # Coherencia: dispersión del valor de suelo dentro de cada barrio
    disp = out.group_by("barrio_id").agg(
        (pl.col("valor_suelo_m2").log() - pl.col("valor_suelo_m2").log().median()).abs().median().alias("d")
    )
    rep.notas["desv_log_valor_suelo_intra_barrio_mediana"] = round(disp["d"].median(), 4)
    rep.cerrar(out.height)


if __name__ == "__main__":
    main()
