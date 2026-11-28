"""Ingesta del detalle catastral del SII, serie AGRÍCOLA: roles, clases de suelo y construcciones.

Entrada (sin encabezado, separador "|", latin1; docs/estructura_detalle_catastral.pdf):
  Vigente por comuna:  data/raw/catastro_vigente/BRTMPCATAS_{sem}_{cod}.zip → BRTMPCATASA_* y BRTMPCATASAL_*
  Histórico nacional:  data/raw/catastro/BRORGA2441_NAC_{sem}.zip        → BRORGA2441A_NAC_* y BRORGA2441AL_NAC_*

Archivo A (un registro por rol): 8 campos en el histórico; el vigente agrega el 9.º, código de ubicación
  (U, R o E; ver src/etl/ref/ubicaciones_sii.csv).
Archivo AL (varias filas por rol): 11 campos en el histórico; el vigente agrega el 12.º, número de pisos.
  Cada fila es una línea de SUELO (código de suelo + superficie en hectáreas con 2 decimales implícitos)
  o una línea de CONSTRUCCIÓN (número de línea > 0, material, calidad, m², destino, condición especial).
  Clases de suelo: src/etl/ref/clases_suelo_sii.csv (1R–3R y 1–8 según el PDF; 4R y 20–29 aparecen en los
  datos pero no en el PDF).

Los roles agrícolas no se repiten en la serie no agrícola (verificado en el Gran Santiago 2026-2S): el rol
comuna-manzana-predio sigue siendo una llave única.

Salidas (data/staging/catastro/):
  agricola_roles_{sem}.parquet    un registro por rol
  agricola_suelos_{sem}.parquet   rol × línea de suelo (cod_suelo, sup_ha)
  agricola_lineas_{sem}.parquet   rol × línea de construcción
Uso:
  python -m src.etl.catastro_agricola --vigente 2026_2      (comunas descargadas, Gran Santiago)
  python -m src.etl.catastro_agricola 2022_1                (histórico nacional, todas las comunas)
"""

from __future__ import annotations

import sys
import zipfile
from collections.abc import Iterable

import polars as pl

from .catastro import _leer_miembro, _parse
from .common import RAW, REF, STAGING, Reporte

ROLES_A_CAMPOS = [
    ("cod_comuna", pl.Int32),
    ("manzana", pl.Int32),
    ("predio", pl.Int32),
    ("direccion", pl.Utf8),
    ("avaluo_total", pl.Int64),
    ("contrib_semestral", pl.Int64),  # con aseo
    ("destino", pl.Utf8),
    ("avaluo_exento", pl.Int64),
    ("cod_ubicacion", pl.Utf8),  # solo estructura vigente
]
LINEAS_AL_CAMPOS = [
    ("cod_comuna", pl.Int32),
    ("manzana", pl.Int32),
    ("predio", pl.Int32),
    ("cod_suelo", pl.Utf8),
    ("sup_suelo_centesimas_ha", pl.Int64),  # hectáreas × 100
    ("linea", pl.Int32),
    ("material", pl.Utf8),
    ("calidad", pl.Utf8),
    ("sup_construida", pl.Int64),  # m²
    ("destino_linea", pl.Utf8),
    ("condicion_especial", pl.Utf8),
    ("pisos", pl.Int32),  # solo estructura vigente
]
ROL_ID = pl.format("{}-{}-{}", "cod_comuna", "manzana", "predio").alias("rol_id")


def clases_suelo() -> pl.DataFrame:
    return pl.read_csv(REF / "clases_suelo_sii.csv", separator=";", schema_overrides={"cod_suelo": pl.Utf8})


def parse_roles(lineas: Iterable[str], comunas: set[int] | None, rep: Reporte) -> pl.DataFrame:
    return _parse(lineas, ROLES_A_CAMPOS, (8, 9), comunas, rep).with_columns(ROL_ID)


def parse_lineas(lineas: Iterable[str], comunas: set[int] | None, rep: Reporte) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Devuelve (suelos, construcciones). Una fila sin código de suelo ni línea de construcción se descarta."""
    df = _parse(lineas, LINEAS_AL_CAMPOS, (11, 12), comunas, rep).with_columns(ROL_ID)
    es_suelo = pl.col("cod_suelo").is_not_null()
    es_constr = pl.col("linea").fill_null(0) > 0
    vacias = df.filter(~es_suelo & ~es_constr).height
    rep.descartar("linea_sin_suelo_ni_construccion", vacias)
    suelos = df.filter(es_suelo).select(
        "rol_id", "cod_comuna", "manzana", "predio", "cod_suelo",
        (pl.col("sup_suelo_centesimas_ha") / 100).round(2).alias("sup_ha"),
    )
    constr = df.filter(es_constr).select(
        "rol_id", "cod_comuna", "manzana", "predio", "linea", "material", "calidad", "sup_construida",
        "destino_linea", "condicion_especial", "pisos",
    )
    # Se acumulan: en el vigente se llama una vez por comuna con el mismo reporte
    for k, n in (("lineas_suelo", suelos.height), ("lineas_construccion", constr.height), ("filas_suelo_y_construccion_a_la_vez", df.filter(es_suelo & es_constr).height)):
        rep.notas[k] = rep.notas.get(k, 0) + n
    return suelos, constr


def _guardar(semestre: str, roles: pl.DataFrame, suelos: pl.DataFrame, constr: pl.DataFrame, rep_r: Reporte, rep_l: Reporte) -> None:
    salida = STAGING / "catastro"
    salida.mkdir(parents=True, exist_ok=True)
    antes = roles.height
    roles = roles.unique("rol_id", keep="first", maintain_order=True).with_columns(pl.lit(semestre).alias("semestre"))
    rep_r.descartar("rol_duplicado", antes - roles.height)
    roles.write_parquet(salida / f"agricola_roles_{semestre}.parquet", compression="zstd")
    rep_r.notas["por_ubicacion"] = dict(roles.group_by("cod_ubicacion").len().sort("cod_ubicacion", nulls_last=True).iter_rows())
    rep_r.notas["por_destino"] = dict(roles.group_by("destino").len().sort("len", descending=True).iter_rows())
    rep_r.cerrar(roles.height)
    cs = clases_suelo()
    rep_l.notas["sup_ha_por_clase"] = {k: round(v, 2) for k, v in suelos.group_by("cod_suelo").agg(pl.col("sup_ha").sum()).sort("cod_suelo").iter_rows()}
    rep_l.notas["codigos_suelo_fuera_de_la_tabla"] = sorted(set(suelos["cod_suelo"].unique()) - set(cs["cod_suelo"]))
    rep_l.notas["roles_sin_ficha_en_A"] = pl.concat([suelos.select("rol_id"), constr.select("rol_id")]).join(roles, on="rol_id", how="anti")["rol_id"].n_unique()
    suelos.with_columns(pl.lit(semestre).alias("semestre")).write_parquet(salida / f"agricola_suelos_{semestre}.parquet", compression="zstd")
    constr.with_columns(pl.lit(semestre).alias("semestre")).write_parquet(salida / f"agricola_lineas_{semestre}.parquet", compression="zstd")
    rep_l.cerrar(suelos.height + constr.height)


def procesar_vigente(semestre: str) -> None:
    zips = sorted((RAW / "catastro_vigente").glob(f"BRTMPCATAS_{semestre}_*.zip"))
    if not zips:
        raise FileNotFoundError(f"no hay catastro vigente {semestre}")
    rep_r, rep_l = Reporte(f"catastro_agricola_roles_{semestre}"), Reporte(f"catastro_agricola_lineas_{semestre}")
    roles, suelos, constr = [], [], []
    for path in zips:
        cod = path.stem.rsplit("_", 1)[1]
        with zipfile.ZipFile(path) as z:
            roles.append(parse_roles(_leer_miembro(z, f"BRTMPCATASA_{semestre}_{cod}"), None, rep_r))
            s, c = parse_lineas(_leer_miembro(z, f"BRTMPCATASAL_{semestre}_{cod}"), None, rep_l)
            suelos.append(s)
            constr.append(c)
    _guardar(semestre, pl.concat(roles), pl.concat(suelos), pl.concat(constr), rep_r, rep_l)


def procesar_historico(semestre: str, comunas: set[int] | None = None) -> None:
    path = RAW / "catastro" / f"BRORGA2441_NAC_{semestre}.zip"
    rep_r, rep_l = Reporte(f"catastro_agricola_roles_{semestre}"), Reporte(f"catastro_agricola_lineas_{semestre}")
    with zipfile.ZipFile(path) as z:
        roles = parse_roles(_leer_miembro(z, f"BRORGA2441A_NAC_{semestre}"), comunas, rep_r)
        suelos, constr = parse_lineas(_leer_miembro(z, f"BRORGA2441AL_NAC_{semestre}"), comunas, rep_l)
    _guardar(semestre, roles, suelos, constr, rep_r, rep_l)


def main(argv: list[str]) -> None:
    if argv[:1] == ["--vigente"]:
        procesar_vigente(argv[1])
        return
    for s in argv or ["2022_1"]:
        procesar_historico(s)


if __name__ == "__main__":
    main(sys.argv[1:])
