"""Separación del avalúo en construcción y terreno (fórmula del SII).

  Avalúo construcción = Σ líneas  VUC(clase, calidad) · SC · CE · DP · FC · CC · factor_ipc
  Avalúo terreno      = avalúo total − avalúo construcción

Fuentes:
  Reavalúo 2022 (rige 2022-1S → 2026-2S): Res. SII 143/2021, Anexo 3 (factores) y Anexo 5 (VUC, $ del 2S-2021).
  Reavalúo 2018 (rige hasta 2021-2S): Res. SII 28/2018, Anexo 3 y Anexo 5 (VUC, $ del 1-7-2017).
  CC (coeficiente comercial) = 1: solo aplica en el centro de Santiago, fuera del piloto.

Factor IPC que lleva los VUC a pesos del semestre:
  2022-1S: 1,051 (citado en la Res. SII 143/2021)
  2026-2S: 1,051 × exento(2026-2S)/exento(2022-1S)  (los montos se reajustan con el mismo IPC)
  2021-2S: UF(1-7-2021)/UF(1-7-2017)  (aproximación del IPC acumulado)

Validación: en casas (sin copropiedad) el terreno por m² debería ser casi constante dentro de la manzana,
porque el SII lo valora por área homogénea. Se mide la dispersión del terreno/m² dentro de cada manzana.

Uso: python -m src.features.avaluo_construccion
"""

from __future__ import annotations

from datetime import date

import polars as pl

from src.etl.common import REF, STAGING, Reporte

# Depreciación: (% anual, % máximo) por clase
_DEP_BASE = {c: (0.008, 0.60) for c in "A B C L GA GB GC GL EA EB M SA SB TA TL".split()}
_DEP_BASE |= {c: (0.015, 0.80) for c in "E GE TE".split()}
_DEP_BASE |= {c: (0.020, 0.80) for c in "F GF".split()}
REAVALUOS = {
    "2022": {
        "vuc": "vuc_2022.csv",
        "anio_base": 2021,
        "dep": _DEP_BASE | {"G": (0.010, 0.70), "K": (0.010, 0.70)},
        "fc": "fc_2022",
    },
    "2018": {
        "vuc": "vuc_2018.csv",
        "anio_base": 2017,
        "dep": _DEP_BASE | {"G": (0.015, 0.70), "K": (0.010, 0.70)},
        "fc": "fc_2018",
    },
}
CE = {"CI": 0.8, "AL": 0.6, "CA": 1.0, "MS": 0.8, "PZ": 0.8, "SB": 0.7}
SEMESTRE_REAVALUO = {"2021_2": "2018", "2022_1": "2022", "2026_2": "2022"}


def factores_comunales(col: str) -> dict[int, float]:
    """Factor de localización comunal (Res. 28/2018 y 143/2021, Anexo 3), en src/etl/ref/factor_comunal.csv."""
    f = pl.read_csv(REF / "factor_comunal.csv", separator=";")
    return dict(zip(f["cod_comuna"].to_list(), f[col].to_list()))


def factor_ipc(semestre: str) -> float:
    if semestre == "2022_1":
        return 1.051
    if semestre == "2026_2":
        r = pl.read_parquet(STAGING / "contribucion_2026_2.parquet")["exento_h_semestre"][0]
        return 1.051 * r / 47_360_490
    if semestre == "2021_2":
        uf = pl.read_parquet(STAGING / "uf.parquet")
        v = {d: uf.filter(pl.col("fecha") == d)["uf"][0] for d in (date(2021, 7, 1), date(2017, 7, 1))}
        return v[date(2021, 7, 1)] / v[date(2017, 7, 1)]
    raise ValueError(semestre)


def valorar_lineas(lineas: pl.DataFrame, reavaluo: str, fipc: float) -> pl.DataFrame:
    cfg = REAVALUOS[reavaluo]
    vuc = pl.read_csv(REF / cfg["vuc"], separator=";", schema={"clase": pl.Utf8, "calidad": pl.Utf8, "vuc": pl.Float64})
    vuc_unica = vuc.filter(pl.col("calidad").is_null()).select("clase", pl.col("vuc").alias("vuc_unica"))
    vuc_cal = vuc.filter(pl.col("calidad").is_not_null())
    dep = pl.DataFrame(
        [(k, a, m) for k, (a, m) in cfg["dep"].items()],
        schema={"clase": pl.Utf8, "dep_anual": pl.Float64, "dep_max": pl.Float64},
        orient="row",
    )
    df = (
        lineas.with_columns(pl.col("material").str.strip_chars().alias("clase"), pl.col("calidad").str.strip_chars())
        .join(vuc_cal, on=["clase", "calidad"], how="left")
        .join(vuc_unica, on="clase", how="left")
        .join(dep, on="clase", how="left")
        .with_columns(
            pl.coalesce("vuc", "vuc_unica").alias("vuc"),
            pl.col("condicion_especial").replace_strict(CE, default=1.0, return_dtype=pl.Float64).alias("ce"),
            pl.col("cod_comuna").replace_strict(factores_comunales(cfg["fc"]), default=None, return_dtype=pl.Float64).alias("fc"),
            pl.when(pl.col("anio_construccion") > 1800)
            .then((cfg["anio_base"] - pl.col("anio_construccion")).clip(lower_bound=0))
            .otherwise(None)
            .alias("edad"),
        )
        .with_columns(
            pl.when(pl.col("dep_anual").is_null())
            .then(1.0)  # obras civiles, pavimentos y piscinas no se deprecian
            .otherwise(1 - pl.min_horizontal(pl.col("dep_anual") * pl.col("edad").fill_null(0), pl.col("dep_max")))
            .alias("dp")
        )
        .with_columns(
            (pl.col("vuc") * pl.col("sup_construida") * pl.col("ce") * pl.col("dp") * pl.col("fc") * fipc).alias(
                "avaluo_linea"
            )
        )
    )
    return df


def separar(semestre: str) -> tuple[pl.DataFrame, dict]:
    reav = SEMESTRE_REAVALUO[semestre]
    fipc = factor_ipc(semestre)
    lineas = pl.read_parquet(STAGING / "catastro" / f"lineas_{semestre}.parquet")
    roles = pl.read_parquet(STAGING / "catastro" / f"roles_{semestre}.parquet")
    val = valorar_lineas(lineas, reav, fipc)
    notas = {
        "reavaluo": reav,
        "factor_ipc": round(fipc, 5),
        "lineas_sin_vuc": val.filter(pl.col("vuc").is_null()).height,
        "lineas_sin_anio": val.filter(pl.col("edad").is_null()).height,
        "condiciones_especiales_sin_factor": dict(
            val.filter(~pl.col("condicion_especial").is_in(list(CE)) & pl.col("condicion_especial").is_not_null())
            .group_by("condicion_especial").len().iter_rows()
        ),
    }
    por_rol = val.group_by("rol_id").agg(
        pl.col("avaluo_linea").sum().alias("avaluo_construccion_teo"),
        pl.col("sup_construida").sum().alias("sup_construida_total"),
        pl.col("vuc").is_null().any().alias("linea_sin_vuc"),
        pl.col("anio_construccion").filter(pl.col("anio_construccion") > 1800).max().alias("anio_construccion_max"),
        (pl.col("clase") + pl.col("calidad").fill_null("")).mode().first().alias("clase_calidad_principal"),
    )
    out = roles.select(
        "rol_id", "cod_comuna", "manzana", "predio", "destino", "avaluo_total", "sup_terreno_m2", "bc1_predio"
    ).join(por_rol, on="rol_id", how="left").with_columns(
        pl.col("avaluo_construccion_teo").fill_null(0.0),
        pl.lit(semestre).alias("semestre"),
        (pl.col("bc1_predio") > 0).fill_null(False).alias("copropiedad"),
    ).with_columns(
        (pl.col("avaluo_total") - pl.col("avaluo_construccion_teo")).alias("avaluo_terreno_teo"),
    ).with_columns(
        (pl.col("avaluo_construccion_teo") / pl.col("avaluo_total")).alias("share_construccion"),
        pl.when(pl.col("sup_terreno_m2") > 0)
        .then(pl.col("avaluo_terreno_teo") / pl.col("sup_terreno_m2"))
        .otherwise(None)
        .alias("terreno_m2_teo"),
    )
    return out, notas


def validar(df: pl.DataFrame) -> dict:
    h = df.filter((pl.col("destino") == "H") & (pl.col("avaluo_total") > 0))
    casas = h.filter(~pl.col("copropiedad") & (pl.col("sup_terreno_m2") > 0) & (pl.col("avaluo_construccion_teo") > 0))
    # Dispersión del terreno/m² dentro de la manzana (manzanas con ≥ 5 casas)
    disp = (
        casas.group_by("cod_comuna", "manzana")
        .agg(
            pl.len().alias("n"),
            pl.col("terreno_m2_teo").median().alias("med"),
            ((pl.col("terreno_m2_teo") / pl.col("terreno_m2_teo").median() - 1).abs()).median().alias("desv_rel_med"),
        )
        .filter(pl.col("n") >= 5)
    )
    return {
        "habitacionales": h.height,
        "share_terreno_negativo_H": round((h["avaluo_terreno_teo"] < -0.01 * h["avaluo_total"]).mean(), 4),
        "share_construccion_mediana_casas": round(casas["share_construccion"].median(), 3),
        "share_construccion_mediana_deptos": round(
            h.filter(pl.col("copropiedad"))["share_construccion"].median() or float("nan"), 3
        ),
        "casas_validas": casas.height,
        "manzanas_validacion": disp.height,
        "desv_rel_mediana_terreno_m2_en_manzana": round(disp["desv_rel_med"].median(), 4),
        "share_manzanas_desv_menor_10pct": round((disp["desv_rel_med"] < 0.10).mean(), 4),
    }


def main() -> None:
    for sem in SEMESTRE_REAVALUO:
        if not (STAGING / "catastro" / f"lineas_{sem}.parquet").exists():
            continue
        rep = Reporte(f"avaluo_construccion_{sem}")
        df, notas = separar(sem)
        rep.entrada = df.height
        rep.notas.update(notas)
        rep.notas["validacion"] = validar(df)
        df.write_parquet(STAGING / f"avaluo_componentes_{sem}.parquet", compression="zstd")
        rep.cerrar(df.height)


if __name__ == "__main__":
    main()
