"""Ingesta del detalle catastral histórico (SII), serie no agrícola.

Entrada: data/raw/catastro/BRORGA2441_NAC_{AAAA}_{S}.zip con los archivos
BRORGA2441N_NAC_{AAAA}_{S} (un registro por rol) y BRORGA2441NL_NAC_{AAAA}_{S}
(una fila por línea de construcción). Sin encabezado, separador "|".
Estructura: docs/estructura_detalle_catastral.pdf. El histórico trae 15 campos en N
(sin ubicación ni rol padre) y 10 en NL (sin pisos); se aceptan también 19 y 11.

Salida (solo comunas seleccionadas, por defecto las piloto):
  data/staging/catastro/roles_{AAAA}_{S}.parquet
  data/staging/catastro/lineas_{AAAA}_{S}.parquet

Uso: python -m src.etl.catastro 2021_2 [2022_1 ...] [--comunas 15105,15103,14109 | --gran-santiago | --todas]
     python -m src.etl.catastro --vigente 2026_2
"""

from __future__ import annotations

import io
import sys
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import polars as pl

from .common import GRAN_SANTIAGO, PILOTO, RAW, STAGING, Reporte

ROLES_CAMPOS = [
    ("cod_comuna", pl.Int32),
    ("manzana", pl.Int32),
    ("predio", pl.Int32),
    ("direccion", pl.Utf8),
    ("avaluo_total", pl.Int64),
    ("contrib_semestral", pl.Int64),  # con aseo
    ("destino", pl.Utf8),
    ("avaluo_exento", pl.Int64),
    ("bc1_comuna", pl.Int32),
    ("bc1_manzana", pl.Int32),
    ("bc1_predio", pl.Int32),
    ("bc2_comuna", pl.Int32),
    ("bc2_manzana", pl.Int32),
    ("bc2_predio", pl.Int32),
    ("sup_terreno_m2", pl.Int64),
    # Solo estructura vigente (19 campos):
    ("cod_ubicacion", pl.Utf8),
    ("padre_comuna", pl.Int32),
    ("padre_manzana", pl.Int32),
    ("padre_predio", pl.Int32),
]
LINEAS_CAMPOS = [
    ("cod_comuna", pl.Int32),
    ("manzana", pl.Int32),
    ("predio", pl.Int32),
    ("linea", pl.Int32),
    ("material", pl.Utf8),
    ("calidad", pl.Utf8),
    ("anio_construccion", pl.Int32),
    ("sup_construida", pl.Int64),  # m2 o m3 según tipo
    ("destino_linea", pl.Utf8),
    ("condicion_especial", pl.Utf8),
    ("pisos", pl.Int32),  # solo estructura vigente (11 campos)
]


def _parse(
    lineas: Iterable[str],
    campos: list[tuple[str, pl.DataType]],
    n_validos: tuple[int, ...],
    comunas: set[int] | None,
    rep: Reporte,
) -> pl.DataFrame:
    filas: list[list[str | None]] = []
    ancho = len(campos)
    for linea in lineas:
        rep.entrada += 1
        # Sin quitar el último campo vacío: en NL la condición especial suele venir vacía.
        partes = linea.rstrip("\r\n").split("|")
        if len(partes) == max(n_validos) + 1 and partes[-1] == "":
            partes = partes[:-1]  # estructura vigente: separador al final de la línea
        if len(partes) not in n_validos:
            rep.descartar(f"n_campos_{len(partes)}")
            continue
        try:
            cod = int(partes[0])
        except ValueError:
            rep.descartar("comuna_no_numerica")
            continue
        if comunas is not None and cod not in comunas:
            rep.descartar("fuera_de_comunas_seleccionadas")
            continue
        partes = [p.strip() or None for p in partes]
        filas.append(partes + [None] * (ancho - len(partes)))
    df = pl.DataFrame(filas, schema={n: pl.Utf8 for n, _ in campos}, orient="row")
    return df.with_columns(
        [pl.col(n).cast(t, strict=False) for n, t in campos if t != pl.Utf8]
    )


def parse_roles(lineas: Iterable[str], comunas: set[int] | None, rep: Reporte) -> pl.DataFrame:
    df = _parse(lineas, ROLES_CAMPOS, (15, 19), comunas, rep)
    return df.with_columns(
        pl.format("{}-{}-{}", "cod_comuna", "manzana", "predio").alias("rol_id")
    )


def parse_lineas(lineas: Iterable[str], comunas: set[int] | None, rep: Reporte) -> pl.DataFrame:
    df = _parse(lineas, LINEAS_CAMPOS, (10, 11), comunas, rep)
    return df.with_columns(
        pl.format("{}-{}-{}", "cod_comuna", "manzana", "predio").alias("rol_id")
    )


def _leer_miembro(z: zipfile.ZipFile, prefijo: str) -> Iterator[str]:
    (nombre,) = [n for n in z.namelist() if n.startswith(prefijo)]
    with z.open(nombre) as f:
        yield from io.TextIOWrapper(f, encoding="latin1", newline="")


def procesar(semestre: str, comunas: set[int] | None) -> None:
    path: Path = RAW / "catastro" / f"BRORGA2441_NAC_{semestre}.zip"
    salida = STAGING / "catastro"
    salida.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        rep = Reporte(f"catastro_roles_{semestre}")
        roles = parse_roles(_leer_miembro(z, f"BRORGA2441N_NAC_{semestre}"), comunas, rep)
        antes = roles.height
        roles = roles.unique("rol_id", keep="first", maintain_order=True)
        rep.descartar("rol_duplicado", antes - roles.height)
        roles = roles.with_columns(pl.lit(semestre).alias("semestre"))
        roles.write_parquet(salida / f"roles_{semestre}.parquet", compression="zstd")
        rep.notas["por_comuna"] = dict(roles.group_by("cod_comuna").len().sort("cod_comuna").iter_rows())
        rep.cerrar(roles.height)

        rep = Reporte(f"catastro_lineas_{semestre}")
        lineas = parse_lineas(_leer_miembro(z, f"BRORGA2441NL_NAC_{semestre}"), comunas, rep)
        lineas = lineas.with_columns(pl.lit(semestre).alias("semestre"))
        lineas.write_parquet(salida / f"lineas_{semestre}.parquet", compression="zstd")
        rep.notas["roles_sin_ficha_en_N"] = lineas.join(roles, on="rol_id", how="anti")["rol_id"].n_unique()
        rep.cerrar(lineas.height)


def procesar_vigente(semestre: str = "2026_2") -> None:
    """Catastro vigente por comuna: data/raw/catastro_vigente/BRTMPCATAS_{semestre}_{cod}.zip."""
    zips = sorted((RAW / "catastro_vigente").glob(f"BRTMPCATAS_{semestre}_*.zip"))
    if not zips:
        raise FileNotFoundError(f"no hay catastro vigente {semestre}")
    salida = STAGING / "catastro"
    salida.mkdir(parents=True, exist_ok=True)
    rep_r, rep_l = Reporte(f"catastro_roles_{semestre}"), Reporte(f"catastro_lineas_{semestre}")
    roles, lineas = [], []
    for path in zips:
        cod = path.stem.rsplit("_", 1)[1]
        with zipfile.ZipFile(path) as z:
            roles.append(parse_roles(_leer_miembro(z, f"BRTMPCATASN_{semestre}_{cod}"), None, rep_r))
            lineas.append(parse_lineas(_leer_miembro(z, f"BRTMPCATASNL_{semestre}_{cod}"), None, rep_l))
    r = pl.concat(roles)
    antes = r.height
    r = r.unique("rol_id", keep="first", maintain_order=True)
    rep_r.descartar("rol_duplicado", antes - r.height)
    r = r.with_columns(pl.lit(semestre).alias("semestre"))
    r.write_parquet(salida / f"roles_{semestre}.parquet", compression="zstd")
    rep_r.notas["por_comuna"] = dict(r.group_by("cod_comuna").len().sort("cod_comuna").iter_rows())
    rep_r.notas["con_rol_padre"] = r.filter(pl.col("padre_predio") > 0).height
    rep_r.cerrar(r.height)
    l = pl.concat(lineas).with_columns(pl.lit(semestre).alias("semestre"))
    l.write_parquet(salida / f"lineas_{semestre}.parquet", compression="zstd")
    rep_l.notas["roles_sin_ficha_en_N"] = l.join(r, on="rol_id", how="anti")["rol_id"].n_unique()
    rep_l.cerrar(l.height)


def main(argv: list[str]) -> None:
    comunas: set[int] | None = set(PILOTO)
    semestres: list[str] = []
    it = iter(argv)
    for a in it:
        if a == "--vigente":
            procesar_vigente(next(it))
            return
        if a == "--gran-santiago":
            comunas = set(GRAN_SANTIAGO)
            continue
        if a == "--todas":
            comunas = None
        elif a == "--comunas":
            comunas = {int(c) for c in next(it).split(",")}
        else:
            semestres.append(a)
    if not semestres:
        semestres = sorted(
            p.stem.removeprefix("BRORGA2441_NAC_") for p in (RAW / "catastro").glob("BRORGA2441_NAC_*.zip")
        )
    for s in semestres:
        procesar(s, comunas)


if __name__ == "__main__":
    main(sys.argv[1:])
