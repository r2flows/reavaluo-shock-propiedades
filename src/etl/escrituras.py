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


def catalogo(cod_comuna: int | None = None) -> tuple[pl.DataFrame, list[str]]:
    """Roles de todos los semestres disponibles; atributos del semestre más reciente.

    Lectura perezosa y solo con las columnas necesarias; con `cod_comuna` filtra antes de cargar (memoria).
    """
    archivos = sorted((STAGING / "catastro").glob("roles_*.parquet"))
    semestres = [p.stem.removeprefix("roles_") for p in archivos]
    filtro = (pl.col("cod_comuna") == cod_comuna) if cod_comuna is not None else pl.lit(True)
    roles = pl.concat(
        [pl.scan_parquet(p).select("rol_id", "cod_comuna", "destino", "avaluo_total", "semestre").filter(filtro) for p in archivos],
        how="vertical_relaxed",
    )
    lineas = pl.concat(
        [
            pl.scan_parquet(p).select("rol_id", "cod_comuna", "anio_construccion").filter(filtro)
            for p in sorted((STAGING / "catastro").glob("lineas_*.parquet"))
        ],
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
        .collect()
    )
    return cat, semestres


def linaje(semestres: list[str]) -> pl.DataFrame:
    """Altas y bajas de roles entre semestres consecutivos (el histórico no trae rol padre)."""
    out = []
    for a, b in zip(semestres, semestres[1:]):
        ra = pl.read_parquet(STAGING / "catastro" / f"roles_{a}.parquet", columns=["rol_id", "cod_comuna", "manzana"])
        rb = pl.read_parquet(STAGING / "catastro" / f"roles_{b}.parquet", columns=["rol_id", "cod_comuna", "manzana"])
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


def procesar_comuna(cod: int) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Cruce, obra nueva y agrupación para una comuna (las escrituras nunca cruzan comunas)."""
    cat, _ = catalogo(cod)
    f = pl.scan_parquet(STAGING / "f2890.parquet").filter(pl.col("cod_comuna") == cod).collect()
    tr = f.join(cat.drop("cod_comuna"), on="rol_id", how="left").with_columns(
        pl.col("primer_semestre").is_not_null().alias("match_catalogo")
    )
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
    tasa = tr.filter(con_precio).group_by("cod_comuna", anio.alias("anio")).agg(
        pl.col("match_catalogo").sum().alias("n_match"), pl.len().alias("n")
    )
    tr, esc = agrupar(tr)
    return tr, esc, tasa


def main() -> None:
    import gc

    comunas_cat = (
        pl.scan_parquet(sorted((STAGING / "catastro").glob("roles_*.parquet"))[-1]).select("cod_comuna").unique().collect()["cod_comuna"].sort().to_list()
    )
    partes = STAGING / "_partes" / "escrituras"
    partes.mkdir(parents=True, exist_ok=True)
    for p in partes.glob("*.parquet"):
        p.unlink()
    tasas = []
    for cod in comunas_cat:
        tr, esc, tasa = procesar_comuna(cod)
        tr.write_parquet(partes / f"tr_{cod}.parquet", compression="zstd")
        esc.write_parquet(partes / f"esc_{cod}.parquet", compression="zstd")
        tasas.append(tasa)
        del tr, esc
        gc.collect()

    rep = Reporte("fase2_match")
    pl.scan_parquet(partes / "tr_*.parquet").sink_parquet(STAGING / "fct_transferencia.parquet", compression="zstd")
    tasa = pl.concat(tasas).sort("cod_comuna", "anio").with_columns((pl.col("n_match") / pl.col("n")).alias("tasa_match"))
    tasa.write_csv(STAGING / "_reportes" / "fase2_tasa_match_por_anio.csv")
    v = tasa.filter(pl.col("anio").is_between(2020, 2023))
    rep.entrada = pl.scan_parquet(STAGING / "fct_transferencia.parquet").select(pl.len()).collect().item()
    rep.notas["tasa_match_con_precio_2020_2023"] = round(v["n_match"].sum() / v["n"].sum(), 4)
    rep.notas["comunas_con_match_2020_2023_<95pct"] = {
        r["cod_comuna"]: round(r["t"], 4)
        for r in v.group_by("cod_comuna").agg((pl.col("n_match").sum() / pl.col("n").sum()).alias("t")).filter(pl.col("t") < 0.95).iter_rows(named=True)
    }
    rep.notas["tasa_match_con_precio_todos_los_anios"] = round(tasa["n_match"].sum() / tasa["n"].sum(), 4)
    rep.cerrar(rep.entrada)

    rep = Reporte("fase2_escrituras")
    pl.scan_parquet(partes / "esc_*.parquet").sink_parquet(STAGING / "fct_escritura.parquet", compression="zstd")
    tr_l = pl.scan_parquet(STAGING / "fct_transferencia.parquet")
    esc = pl.read_parquet(STAGING / "fct_escritura.parquet", columns=["tipo_grupo", "regla_monto", "primera_venta_obra_nueva"])
    rep.entrada = rep_n = tr_l.select(pl.len()).collect().item()
    sin_esc = tr_l.filter(pl.col("escritura_id").is_null()).select(pl.len()).collect().item()
    rep.descartar("anexo_no_asignable", sin_esc)
    rep.descartar("agrupado_en_escritura", rep_n - sin_esc - esc.height)
    rep.notas["por_tipo_grupo"] = dict(esc.group_by("tipo_grupo").len().sort("len", descending=True).iter_rows())
    rep.notas["por_regla_monto"] = dict(esc.group_by("regla_monto").len().sort("len", descending=True).iter_rows())
    rep.notas["primera_venta_obra_nueva"] = int(esc["primera_venta_obra_nueva"].sum())
    rep.cerrar(esc.height)
    del esc
    gc.collect()

    rep = Reporte("fase2_linaje")
    semestres = [p.stem.removeprefix("roles_") for p in sorted((STAGING / "catastro").glob("roles_*.parquet"))]
    lin = linaje(semestres)
    rep.entrada = lin.height
    rep.notas["por_tipo"] = dict(lin.group_by("tipo").len().iter_rows())
    rep.notas["en_manzanas_con_altas_y_bajas"] = int(lin["manzana_con_altas_y_bajas"].sum())
    lin.write_parquet(STAGING / "map_rol_linaje.parquet", compression="zstd")
    rep.cerrar(lin.height)


if __name__ == "__main__":
    main()
