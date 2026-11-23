"""Ingesta del F2890 (transferencias de bienes raíces, SII).

Entrada: data/raw/f2890/F2890_*.zip (un txt `;`, latin1, con encabezado:
COMUNA;MANZANA;PREDIO;FECHA_INSCRIPCION;FECHA_ESCRITURA;MONTO_PESOS;MONTO_UF).

Salida: data/staging/f2890.parquet, una fila por rol × escritura, con
cod_comuna, manzana, predio, rol_id, fechas, montos originales, uf_dia y monto_uf_norm
(monto en UF a la fecha de la escritura; null si la escritura no trae monto).

Uso: python -m src.etl.f2890
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from .common import RAW, STAGING, Reporte, comunas

COLUMNAS = [
    "COMUNA",
    "MANZANA",
    "PREDIO",
    "FECHA_INSCRIPCION",
    "FECHA_ESCRITURA",
    "MONTO_PESOS",
    "MONTO_UF",
]
SCHEMA_RAW = {c: pl.Utf8 for c in COLUMNAS}
FECHA_MIN = date(1950, 1, 1)


def leer_texto(texto: str) -> pl.DataFrame:
    """Lee el txt del F2890 como strings con el esquema explícito."""
    df = pl.read_csv(
        io.StringIO(texto.replace("\r", "")),
        separator=";",
        schema=SCHEMA_RAW,
        has_header=True,
        quote_char=None,
    )
    if df.columns != COLUMNAS:
        raise ValueError(f"columnas inesperadas: {df.columns}")
    return df


def transformar(
    raw: pl.DataFrame, uf: pl.DataFrame, fecha_corte: date, rep: Reporte
) -> pl.DataFrame:
    """Tipifica, descarta registros inválidos (con motivo) y normaliza montos a UF."""
    rep.entrada = raw.height
    df = raw.with_columns(
        pl.col("COMUNA").str.strip_chars().alias("nombre_f2890"),
        pl.col("MANZANA").str.strip_chars().cast(pl.Int32, strict=False).alias("manzana"),
        pl.col("PREDIO").str.strip_chars().cast(pl.Int32, strict=False).alias("predio"),
        pl.col("FECHA_INSCRIPCION").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("fecha_inscripcion"),
        pl.col("FECHA_ESCRITURA").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("fecha_escritura"),
        pl.col("MONTO_PESOS").str.strip_chars().cast(pl.Float64, strict=False).alias("monto_pesos"),
        pl.col("MONTO_UF").str.strip_chars().cast(pl.Float64, strict=False).alias("monto_uf"),
    ).select(
        "nombre_f2890", "manzana", "predio", "fecha_inscripcion", "fecha_escritura", "monto_pesos", "monto_uf"
    )

    # Comuna → código SII
    df = df.join(comunas().select("cod_comuna", "nombre_f2890"), on="nombre_f2890", how="left")

    reglas = [
        ("comuna_desconocida", pl.col("cod_comuna").is_null()),
        ("rol_invalido", pl.col("manzana").is_null() | pl.col("predio").is_null()),
        ("fecha_escritura_invalida", pl.col("fecha_escritura").is_null()),
        (
            "fecha_escritura_fuera_de_rango",
            (pl.col("fecha_escritura") < FECHA_MIN) | (pl.col("fecha_escritura") > fecha_corte),
        ),
    ]
    for motivo, cond in reglas:
        n = df.filter(cond).height
        rep.descartar(motivo, n)
        df = df.filter(~cond)

    # Duplicados exactos (réplica parcial del criterio de descarte del SII; el público no trae tipo de escritura)
    antes = df.height
    df = df.unique(maintain_order=True)
    rep.descartar("duplicado_exacto", antes - df.height)

    # Normalización a UF a la fecha de la escritura
    df = df.join(uf.rename({"fecha": "fecha_escritura", "uf": "uf_dia"}), on="fecha_escritura", how="left")
    df = df.with_columns(
        pl.when(pl.col("monto_uf") > 0)
        .then(pl.col("monto_uf"))
        .when((pl.col("monto_pesos") > 0) & pl.col("uf_dia").is_not_null())
        .then(pl.col("monto_pesos") / pl.col("uf_dia"))
        .otherwise(None)
        .alias("monto_uf_norm"),
        pl.when(pl.col("monto_uf") > 0)
        .then(pl.lit("UF"))
        .when(pl.col("monto_pesos") > 0)
        .then(pl.lit("CLP"))
        .otherwise(pl.lit("sin_monto"))
        .alias("unidad_origen"),
        (
            pl.col("fecha_inscripcion").is_not_null()
            & (pl.col("fecha_inscripcion") < pl.col("fecha_escritura"))
        ).alias("flag_inscripcion_antes_escritura"),
        pl.format(
            "{}-{}-{}",
            pl.col("cod_comuna"),
            pl.col("manzana"),
            pl.col("predio"),
        ).alias("rol_id"),
    )
    rep.notas["sin_uf_del_dia_con_monto_clp"] = df.filter(
        (pl.col("unidad_origen") == "CLP") & pl.col("uf_dia").is_null()
    ).height
    rep.notas["por_unidad"] = dict(df.group_by("unidad_origen").len().iter_rows())
    return df.select(
        "rol_id",
        "cod_comuna",
        "manzana",
        "predio",
        "fecha_escritura",
        "fecha_inscripcion",
        "monto_pesos",
        "monto_uf",
        "unidad_origen",
        "uf_dia",
        "monto_uf_norm",
        "flag_inscripcion_antes_escritura",
    )


def zip_actual() -> Path:
    zips = sorted((RAW / "f2890").glob("F2890_*.zip"))
    if not zips:
        raise FileNotFoundError("no hay F2890_*.zip en data/raw/f2890/")
    return zips[-1]


def fecha_de_corte(path: Path) -> date:
    d, m, a = path.stem.split("_")[1].split("-")
    return date(int(a), int(m), int(d))


def main() -> pl.DataFrame:
    path = zip_actual()
    with zipfile.ZipFile(path) as z:
        (nombre,) = z.namelist()
        texto = z.read(nombre).decode("latin1")
    raw = leer_texto(texto)
    del texto
    uf = pl.read_parquet(STAGING / "uf.parquet")
    rep = Reporte("f2890")
    df = transformar(raw, uf, fecha_de_corte(path), rep)
    df.write_parquet(STAGING / "f2890.parquet", compression="zstd")
    rep.notas["archivo"] = path.name
    rep.cerrar(df.height)
    return df


if __name__ == "__main__":
    main()
