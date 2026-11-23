"""Contribución teórica por rol y semestre, y shock del reavalúo 2022.

Fórmula (Ley 17.235; guía SII para calcular la contribución, reavalúo 2022):
  afecto = avalúo total − avalúo exento del rol
  Habitacional (H):
    neta anual = t1 · min(afecto, max(0, cambio − exento_rol)) + t2 · max(0, total − cambio)
    sobretasa fiscal anual = 0,025% · max(0, total − cambio)
  No habitacional:
    neta anual = t_no_h · afecto ; sobretasa fiscal = 0,025% · afecto
  Sitio eriazo (W) afecto: + sobretasa 100% de la tasa (t_no_h · afecto)
  Semestral = anual / 2.

La contribución del catastro incluye el aseo municipal, que es un monto fijo por comuna y semestre.
Se estima como la moda del residuo (observado − teórico) en roles habitacionales afectos
con exención general.

Alza gradual (solo 2022-1S; aplica a la contribución neta, no a las sobretasas):
  base = cuota trimestral teórica 2021-2S (sin beneficios) ; nueva = cuota teórica 2022-1S
  si nueva > 9.415 y base = 0          → paga 9.415 por cuota
  si nueva > 9.415 y nueva > 1,25·base → paga max(1,25·base, 9.415) por cuota  [supuesto en el piso]

Salidas:
  data/staging/contribucion_{semestre}.parquet

Uso: python -m src.features.contribucion
"""

from __future__ import annotations

import polars as pl

from src.etl.common import REF, STAGING, Reporte

CUOTA_MIN_GRADUAL_2022 = 9_415  # $ por cuota trimestral, 1-1-2022
# La cuota base 2S-2021 se actualiza a pesos del 1-1-2022 (IPC). El factor 1,051 lo cita la Res. SII 143/2021
# y se verificó empíricamente: cuota observada / cuota con tope sin actualizar ≈ 1,051 en los roles con alza gradual.
FACTOR_ACTUALIZACION_BASE_2022 = 1.051
TOL = 0.01  # error relativo aceptado (1%)


def parametros() -> pl.DataFrame:
    return pl.read_csv(REF / "parametros_impuesto.csv", separator=";", infer_schema_length=0).with_columns(
        pl.col("exento_h", "cambio_tasa").cast(pl.Float64, strict=False),
        pl.col("t1", "t2", "t_no_h", "sobretasa").cast(pl.Float64),
    )


def completar_parametros(p: dict, roles: pl.DataFrame) -> dict:
    """Para semestres sin exento publicado (vigente), lo toma como la moda del catastro."""
    p = dict(p)
    if p["exento_h"] is None:
        moda = (
            roles.filter((pl.col("destino") == "H") & (pl.col("avaluo_exento") > 0))
            .group_by("avaluo_exento").len().sort("len", descending=True)["avaluo_exento"][0]
        )
        p["exento_h"] = float(moda)
        p["cambio_tasa"] = 169_144_585 * moda / 47_360_490
    return p


def contribucion_teorica(df: pl.DataFrame, p: dict) -> pl.DataFrame:
    """Agrega afecto, contribución neta y sobretasas teóricas semestrales (en pesos del semestre)."""
    total = pl.col("avaluo_total").cast(pl.Float64)
    exento = pl.col("avaluo_exento").cast(pl.Float64)
    afecto = (total - exento).clip(lower_bound=0)
    es_h = pl.col("destino") == "H"
    cambio = p["cambio_tasa"]
    tramo1 = pl.min_horizontal(afecto, (pl.lit(cambio) - exento).clip(lower_bound=0))
    tramo2 = (total - cambio).clip(lower_bound=0)
    neta_anual = (
        pl.when(es_h)
        .then(p["t1"] * tramo1 + p["t2"] * pl.min_horizontal(tramo2, afecto))
        .otherwise(p["t_no_h"] * afecto)
    )
    sobretasa_anual = (
        pl.when(es_h).then(p["sobretasa"] * pl.min_horizontal(tramo2, afecto)).otherwise(p["sobretasa"] * afecto)
    ) + pl.when(pl.col("destino") == "W").then(p["t_no_h"] * afecto).otherwise(0.0)
    return df.with_columns(
        afecto.alias("avaluo_afecto"),
        (neta_anual / 2).alias("contrib_neta_teo"),
        (sobretasa_anual / 2).alias("sobretasas_teo"),
        (exento > p["exento_h"] + 1).alias("exencion_especial"),  # DFL2, culto, etc.
    ).with_columns((pl.col("contrib_neta_teo") + pl.col("sobretasas_teo")).alias("contrib_teo"))


def estimar_aseo(df: pl.DataFrame, p: dict) -> pl.DataFrame:
    """Aseo semestral por comuna = moda del residuo observado − teórico (redondeado a $100)."""
    base = df.filter(
        (pl.col("destino") == "H")
        & (pl.col("contrib_semestral") > 0)
        & (pl.col("avaluo_exento") == p["exento_h"])
        & (pl.col("contrib_teo") > 0)
    ).with_columns(((pl.col("contrib_semestral") - pl.col("contrib_teo")) / 100).round(0).mul(100).alias("res"))
    return (
        base.group_by("cod_comuna", "res").len()
        .sort("len", descending=True)
        .group_by("cod_comuna", maintain_order=True)
        .first()
        .select("cod_comuna", pl.col("res").alias("aseo_sem"), pl.col("len").alias("n_moda"))
    )


def aplicar_gradualidad(nueva_sem: pl.Expr, base_sem: pl.Expr) -> pl.Expr:
    """Contribución neta semestral con alza gradual del primer semestre de un reavalúo."""
    nueva_q, base_q = nueva_sem / 2, base_sem / 2
    tope_q = pl.when(base_q <= 0).then(pl.lit(float(CUOTA_MIN_GRADUAL_2022))).otherwise(
        pl.max_horizontal(1.25 * base_q, pl.lit(float(CUOTA_MIN_GRADUAL_2022)))
    )
    aplica = (nueva_q > CUOTA_MIN_GRADUAL_2022) & (nueva_q > 1.25 * base_q)
    return pl.when(aplica).then(2 * tope_q).otherwise(nueva_sem)


def validar(df: pl.DataFrame, col_teo: str, p: dict) -> dict:
    """Error relativo observado (sin aseo) vs teórico, en H afectos con exención general."""
    d = df.filter(
        (pl.col("destino") == "H") & (pl.col("avaluo_exento") == p["exento_h"]) & (pl.col(col_teo) > 0)
    ).with_columns(((pl.col("contrib_obs_sin_aseo") - pl.col(col_teo)) / pl.col(col_teo)).alias("err"))
    return {
        "n": d.height,
        "error_mediano_abs": round(d["err"].abs().median(), 5),
        "share_err_menor_1pct": round((d["err"].abs() < TOL).mean(), 4),
        "share_obs_menor_teo_>1pct": round((d["err"] < -TOL).mean(), 4),
    }


def clasificar_rebaja(df: pl.DataFrame, col_teo: str, p: dict) -> pl.DataFrame:
    """Rebaja observada en viviendas afectas con exención general (huella del beneficio de adulto mayor).

    ratio = pagado sin aseo / teórico:  < 1% → "100%" ; 45–55% → "50%" ; 99–101% → "ninguna" ; resto → "otra".
    Para el resto de los roles (exentos, no habitacionales o con exención especial) queda null.
    """
    ratio = pl.col("contrib_obs_sin_aseo") / pl.col(col_teo)
    elegible = (pl.col("destino") == "H") & (pl.col("avaluo_exento") == p["exento_h"]) & (pl.col(col_teo) > 0)
    return df.with_columns(
        pl.when(~elegible)
        .then(None)
        .when(ratio < 0.01)
        .then(pl.lit("100%"))
        .when(ratio.is_between(0.45, 0.55))
        .then(pl.lit("50%"))
        .when(ratio.is_between(1 - TOL, 1 + TOL))
        .then(pl.lit("ninguna"))
        .otherwise(pl.lit("otra"))
        .alias("rebaja_obs")
    )


def procesar(semestre: str, p: dict) -> pl.DataFrame:
    roles = pl.read_parquet(STAGING / "catastro" / f"roles_{semestre}.parquet")
    p = completar_parametros(p, roles)
    df = contribucion_teorica(roles, p)
    aseo = estimar_aseo(df, p)
    df = df.join(aseo.select("cod_comuna", "aseo_sem"), on="cod_comuna", how="left").with_columns(
        pl.when(pl.col("contrib_semestral") > 0)
        .then((pl.col("contrib_semestral") - pl.col("aseo_sem")).clip(lower_bound=0))
        .otherwise(0)
        .alias("contrib_obs_sin_aseo"),
        pl.lit(p["exento_h"]).alias("exento_h_semestre"),
        pl.lit(p["cambio_tasa"]).alias("cambio_tasa_semestre"),
    )
    return df, aseo, p


def main() -> None:
    params = {r["semestre"]: r for r in parametros().iter_rows(named=True)}
    salidas = {}
    for sem in sorted(p.stem.removeprefix("roles_") for p in (STAGING / "catastro").glob("roles_*.parquet")):
        if sem not in params:
            print(f"[contribucion] sin parámetros para {sem}, se omite")
            continue
        rep = Reporte(f"contribucion_{sem}")
        df, aseo, p = procesar(sem, params[sem])
        rep.entrada = df.height
        rep.notas["parametros"] = {k: p[k] for k in ("exento_h", "cambio_tasa", "t1", "t2", "t_no_h")}
        rep.notas["aseo_semestral_estimado"] = {r["cod_comuna"]: r["aseo_sem"] for r in aseo.iter_rows(named=True)}
        if sem != "2022_1":
            rep.notas["validacion"] = validar(df, "contrib_teo", p)
        salidas[sem] = (df, p, rep)

    # Reavalúo 2022: base 2021-2S, gradualidad en 2022-1S
    if {"2021_2", "2022_1"} <= salidas.keys():
        d21, _, _ = salidas["2021_2"]
        d22, p22, rep22 = salidas["2022_1"]
        base = d21.select("rol_id", pl.col("contrib_neta_teo").alias("neta_teo_2021_2"))
        d22 = d22.join(base, on="rol_id", how="left").with_columns(
            pl.when(pl.col("neta_teo_2021_2").is_not_null() & (pl.col("destino") == "H"))
            .then(
                aplicar_gradualidad(
                    pl.col("contrib_neta_teo"), pl.col("neta_teo_2021_2") * FACTOR_ACTUALIZACION_BASE_2022
                )
            )
            .otherwise(pl.col("contrib_neta_teo"))
            .alias("contrib_neta_gradual")
        ).with_columns(
            (pl.col("contrib_neta_gradual") + pl.col("sobretasas_teo")).alias("contrib_teo_gradual"),
            (pl.col("contrib_neta_gradual") < pl.col("contrib_neta_teo") - 1).alias("con_alza_gradual"),
        )
        rep22.notas["validacion_sin_gradualidad"] = validar(d22, "contrib_teo", p22)
        rep22.notas["validacion_con_gradualidad"] = validar(d22, "contrib_teo_gradual", p22)
        rep22.notas["roles_con_alza_gradual"] = int(d22["con_alza_gradual"].sum())
        salidas["2022_1"] = (d22, p22, rep22)


    for sem, (df, p, rep) in salidas.items():
        col = "contrib_teo_gradual" if "contrib_teo_gradual" in df.columns else "contrib_teo"
        df = clasificar_rebaja(df, col, p)
        rep.notas["rebaja_observada_H"] = dict(
            df.filter(pl.col("destino") == "H").group_by("rebaja_obs").len().sort("len", descending=True).iter_rows()
        )
        df.write_parquet(STAGING / f"contribucion_{sem}.parquet", compression="zstd")
        rep.cerrar(df.height)


if __name__ == "__main__":
    main()
