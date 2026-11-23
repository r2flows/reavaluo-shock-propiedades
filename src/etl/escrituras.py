"""Fase 2: cruce F2890 ↔ catastro, agrupación por escritura y linaje básico de roles.

Entradas: data/staging/f2890.parquet, data/staging/catastro/{roles,lineas}_*.parquet
Salidas:
  data/staging/fct_transferencia.parquet  rol × escritura del F2890 (comunas del catálogo) + match y escritura_id
  data/staging/fct_escritura.parquet      una fila por escritura (venta) con rol principal y monto en UF
  data/staging/map_rol_linaje.parquet     altas y bajas de roles entre semestres consecutivos

Reglas de agrupación (copropiedad: depto + bodega + estacionamiento en la misma escritura):
  - Grupo = misma comuna, manzana, fecha de escritura y fecha de inscripción.
  - Con 0 o 1 rol habitacional, el grupo es una sola escritura. Su monto es el monto único
    si todos los montos positivos son iguales (monto global repetido) y, si no, la suma.
  - Con >1 rol habitacional, cada rol habitacional es su propia escritura con su propio monto
    (ventas simultáneas, típicas de proyectos nuevos). Los anexos quedan sin asignar.
  - Primera venta de obra nueva: primera transferencia observada del rol, con escritura
    ≤ 2 años después del año de construcción más reciente del rol.

Uso: python -m src.etl.escrituras
"""

from __future__ import annotations

import polars as pl

from .common import STAGING, Reporte

DESTINO_PRINCIPAL = "H"


def catalogo() -> tuple[pl.DataFrame, list[str]]:
    """Roles de todos los semestres disponibles; atributos del semestre más reciente."""
    archivos = sorted((STAGING / "catastro").glob("roles_*.parquet"))
    semestres = [p.stem.removeprefix("roles_") for p in archivos]
    roles = pl.concat([pl.read_parquet(p) for p in archivos], how="vertical_relaxed")
    lineas = pl.concat(
        [pl.read_parquet(p) for p in sorted((STAGING / "catastro").glob("lineas_*.parquet"))],
        how="vertical_relaxed",
    )
    anio = lineas.group_by("rol_id").agg(pl.col("anio_construccion").max().alias("anio_construccion_max"))
    cat = (
        roles.sort("semestre")
        .group_by("rol_id")
        .agg(
            pl.col("cod_comuna").last(),
            pl.col("destino").last(),
            pl.col("avaluo_total").last(),
            pl.col("semestre").first().alias("primer_semestre"),
            pl.col("semestre").last().alias("ultimo_semestre"),
        )
        .join(anio, on="rol_id", how="left")
    )
    return cat, semestres


def linaje(semestres: list[str]) -> pl.DataFrame:
    """Altas y bajas de roles entre semestres consecutivos (el histórico no trae rol padre)."""
    out = []
    for a, b in zip(semestres, semestres[1:]):
        ra = pl.read_parquet(STAGING / "catastro" / f"roles_{a}.parquet").select("rol_id", "cod_comuna", "manzana")
        rb = pl.read_parquet(STAGING / "catastro" / f"roles_{b}.parquet").select("rol_id", "cod_comuna", "manzana")
        out.append(rb.join(ra, on="rol_id", how="anti").with_columns(pl.lit("alta").alias("tipo")))
        out.append(ra.join(rb, on="rol_id", how="anti").with_columns(pl.lit("baja").alias("tipo")))
        out[-2] = out[-2].with_columns(pl.lit(a).alias("desde"), pl.lit(b).alias("hasta"))
        out[-1] = out[-1].with_columns(pl.lit(a).alias("desde"), pl.lit(b).alias("hasta"))
    if not out:
        return pl.DataFrame()
    df = pl.concat(out)
    # Manzanas con altas y bajas a la vez: candidatas a subdivisión/fusión
    mix = (
        df.group_by("cod_comuna", "manzana", "desde")
        .agg(pl.col("tipo").n_unique().alias("n_tipos"))
        .filter(pl.col("n_tipos") == 2)
        .select("cod_comuna", "manzana", "desde")
        .with_columns(pl.lit(True).alias("manzana_con_altas_y_bajas"))
    )
    return df.join(mix, on=["cod_comuna", "manzana", "desde"], how="left").with_columns(
        pl.col("manzana_con_altas_y_bajas").fill_null(False)
    )


def agrupar(tr: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Asigna escritura_id a cada transferencia y construye la tabla de escrituras."""
    clave = ["cod_comuna", "manzana", "fecha_escritura", "fecha_inscripcion"]
    tr = tr.with_columns(
        pl.struct(clave).hash().alias("grupo_id"),
        (pl.col("destino") == DESTINO_PRINCIPAL).fill_null(False).alias("es_h"),
    )
    n_h = tr.group_by("grupo_id").agg(pl.col("es_h").sum().alias("n_h"), pl.len().alias("n_roles_grupo"))
    tr = tr.join(n_h, on="grupo_id")
    tr = tr.with_columns(
        pl.when(pl.col("n_h") <= 1)
        .then(pl.col("grupo_id").cast(pl.Utf8))
        .when(pl.col("es_h"))
        .then(pl.format("{}-{}", pl.col("grupo_id"), pl.col("rol_id")))
        .otherwise(None)
        .alias("escritura_id"),
        pl.when(pl.col("n_h") == 0)
        .then(pl.lit("sin_habitacional"))
        .when((pl.col("n_h") == 1) & (pl.col("n_roles_grupo") == 1))
        .then(pl.lit("simple"))
        .when(pl.col("n_h") == 1)
        .then(pl.lit("con_anexos"))
        .otherwise(pl.lit("multiples_habitacionales"))
        .alias("tipo_grupo"),
    )
    asignadas = tr.filter(pl.col("escritura_id").is_not_null())
    esc = (
        asignadas.sort(["es_h", "avaluo_total"], descending=True, nulls_last=True)
        .group_by("escritura_id")
        .agg(
            pl.col("rol_id").first().alias("rol_principal"),
            pl.col("destino").first().alias("destino_principal"),
            pl.col("cod_comuna").first(),
            pl.col("manzana").first(),
            pl.col("fecha_escritura").first(),
            pl.col("fecha_inscripcion").first(),
            pl.col("tipo_grupo").first(),
            pl.col("primera_venta_obra_nueva").first(),
            pl.len().alias("n_roles"),
            pl.col("monto_uf_norm").filter(pl.col("monto_uf_norm") > 0).alias("montos"),
        )
        .with_columns(
            pl.col("montos").list.len().alias("n_montos"),
            pl.when(pl.col("montos").list.len() == 0)
            .then(None)
            .when(pl.col("montos").list.n_unique() == 1)
            .then(pl.col("montos").list.first())
            .otherwise(pl.col("montos").list.sum())
            .alias("monto_uf"),
            pl.when(pl.col("montos").list.len() == 0)
            .then(pl.lit("sin_monto"))
            .when(pl.col("montos").list.len() == 1)
            .then(pl.lit("unico"))
            .when(pl.col("montos").list.n_unique() == 1)
            .then(pl.lit("repetido"))
            .otherwise(pl.lit("sumado"))
            .alias("regla_monto"),
        )
        .drop("montos")
    )
    return tr, esc


def main() -> None:
    cat, semestres = catalogo()
    comunas_cat = cat["cod_comuna"].unique().to_list()

    rep = Reporte("fase2_match")
    f = pl.read_parquet(STAGING / "f2890.parquet").filter(pl.col("cod_comuna").is_in(comunas_cat))
    rep.entrada = f.height
    tr = f.join(cat.drop("cod_comuna"), on="rol_id", how="left").with_columns(
        pl.col("primer_semestre").is_not_null().alias("match_catalogo")
    )

    # Primera venta de obra nueva
    tr = tr.sort("fecha_escritura").with_columns(
        (pl.col("fecha_escritura") == pl.col("fecha_escritura").min().over("rol_id")).alias("es_primera_obs")
    ).with_columns(
        (
            pl.col("es_primera_obs")
            & pl.col("anio_construccion_max").is_not_null()
            & (pl.col("fecha_escritura").dt.year() - pl.col("anio_construccion_max") <= 2)
        ).alias("primera_venta_obra_nueva")
    )

    con_precio = pl.col("monto_uf_norm") > 0
    anio = pl.col("fecha_escritura").dt.year()
    tasa = (
        tr.filter(con_precio)
        .group_by("cod_comuna", anio.alias("anio"))
        .agg(pl.col("match_catalogo").mean().alias("tasa_match"), pl.len().alias("n"))
        .sort("cod_comuna", "anio")
    )
    ventana = tr.filter(con_precio & anio.is_between(2020, 2023))
    rep.notas["tasa_match_con_precio_2020_2023"] = round(ventana["match_catalogo"].mean(), 4)
    rep.notas["tasa_match_con_precio_2020_2023_por_comuna"] = {
        k: round(v, 4)
        for k, v in ventana.group_by("cod_comuna").agg(pl.col("match_catalogo").mean()).iter_rows()
    }
    rep.notas["tasa_match_con_precio_todos_los_anios"] = round(tr.filter(con_precio)["match_catalogo"].mean(), 4)
    tasa.write_csv(STAGING / "_reportes" / "fase2_tasa_match_por_anio.csv")

    tr, esc = agrupar(tr)
    tr.write_parquet(STAGING / "fct_transferencia.parquet", compression="zstd")
    rep.cerrar(tr.height)

    rep = Reporte("fase2_escrituras")
    rep.entrada = tr.height
    rep.descartar("anexo_no_asignable", tr.filter(pl.col("escritura_id").is_null()).height)
    rep.descartar("agrupado_en_escritura", tr.filter(pl.col("escritura_id").is_not_null()).height - esc.height)
    rep.notas["por_tipo_grupo"] = dict(esc.group_by("tipo_grupo").len().sort("len", descending=True).iter_rows())
    rep.notas["por_regla_monto"] = dict(esc.group_by("regla_monto").len().sort("len", descending=True).iter_rows())
    rep.notas["primera_venta_obra_nueva"] = esc["primera_venta_obra_nueva"].sum()
    esc.write_parquet(STAGING / "fct_escritura.parquet", compression="zstd")
    rep.cerrar(esc.height)

    rep = Reporte("fase2_linaje")
    lin = linaje(semestres)
    rep.entrada = lin.height
    rep.notas["por_tipo"] = dict(lin.group_by("tipo").len().iter_rows())
    rep.notas["en_manzanas_con_altas_y_bajas"] = lin["manzana_con_altas_y_bajas"].sum()
    lin.write_parquet(STAGING / "map_rol_linaje.parquet", compression="zstd")
    rep.cerrar(lin.height)


if __name__ == "__main__":
    main()
