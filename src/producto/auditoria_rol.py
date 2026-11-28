"""Auditor de avalúo por rol: señales de posible error técnico (insumo para un reclamo, no una conclusión).

En Chile el reclamo del avalúo no agrícola se funda en causales técnicas (art. 149 del Código Tributario):
  1. superficie errónea de terreno o construcciones;
  2. aplicación errónea de las tablas de clasificación de las construcciones o de los coeficientes;
  3. errores de transcripción, copia o cálculo.
Este módulo NO usa el valor de mercado como causal. Compara el avalúo de cada vivienda con el que resulta de
aplicar las tablas del SII a sus propios datos (src/features/avaluo_construccion.py) y con sus pares:

  terreno_sobre_manzana  (casas, sin copropiedad; manzana con ≥ 5 casas válidas)
      El SII valora el suelo por área homogénea: el terreno/m² implícito (avalúo − construcción reconstruida)
      es casi constante dentro de la manzana (desvío mediano 0,2%). Un terreno/m² mucho mayor que el de la
      manzana indica que el avalúo es más alto de lo que explican sus líneas: causal 2 o 3.
      fuerte: desvío ≥ 20% ; revisar: desvío ≥ 10%. Exige además un exceso ≥ 2% del avalúo y que el valor sea
      aislado: si otras 2 o más casas de la manzana tienen el mismo terreno/m² (±3%), se trata de otra área
      homogénea dentro de la manzana y no se marca.
  avaluo_m2_sobre_edificio  (departamentos; ≥ 5 unidades del mismo edificio, clase-calidad y año)
      Dentro de un edificio las unidades iguales tienen el mismo avalúo/m² (p99 del desvío: 0,6%).
      fuerte: desvío ≥ 5% ; revisar: desvío ≥ 2%. Igual que en casas, solo valores aislados (±1%).
  calidad_sobre_edificio  (departamentos; ≥ 5 unidades de la misma clase y año en el edificio)
      La unidad tiene una calidad mejor (número menor = más cara) que la moda de sus pares: causal 2.
      Exceso = avalúo de construcción × (1 − VUC(calidad de los pares) / VUC(su calidad)). Nivel: revisar.
  superficie_aumento  (solo con semestre previo)
      La superficie construida subió ≥ 10% y ≥ 10 m² desde el semestre previo: verificar que la ampliación
      exista y esté bien medida (causal 1). Nivel: revisar. Sin exceso estimado.

Ahorro: contribución anual teórica con el avalúo actual menos la contribución con (avalúo − exceso),
con los parámetros del semestre (src/features/contribucion.py).

Backtest (criterio de aceptación, docs/plan.md, Fase 9-bis): se marcan los roles con el catastro 2022-1S y se
mira si en 2026-2S el SII bajó su avalúo (> 2% bajo el reajuste común) sin cambio físico en sus líneas.

Salidas:
  data/marts/auditoria_roles_2026_2.parquet  (una fila por rol × señal; solo roles con señal)
  data/staging/_reportes/auditoria_roles.json
Uso: scripts/correr.sh --mem 5G src.producto.auditoria_rol
"""

from __future__ import annotations

import polars as pl

from src.etl.common import GRAN_SANTIAGO, MARTS, REF, STAGING, Reporte
from src.features.avaluo_construccion import REAVALUOS, SEMESTRE_REAVALUO
from src.features.contribucion import contribucion_teorica

UMBRAL_CASA = {"fuerte": 0.20, "revisar": 0.10}
UMBRAL_DEPTO = {"fuerte": 0.05, "revisar": 0.02}
MIN_PARES = 5
MIN_EXCESO_REL = 0.02
AHV_TOL = 0.03  # log: casas con terreno/m² a ±3% se consideran de la misma área homogénea
DEPTO_TOL = 0.01  # log: unidades con avalúo/m² a ±1% se consideran del mismo tipo (p. ej. todos los pisos altos)
CAUSAL = {
    "terreno_sobre_manzana": "Art. 149 N°2 o N°3 (coeficientes o cálculo)",
    "avaluo_m2_sobre_edificio": "Art. 149 N°2 o N°3 (tablas, coeficientes o cálculo)",
    "calidad_sobre_edificio": "Art. 149 N°2 (clasificación de la construcción)",
    "superficie_aumento": "Art. 149 N°1 (superficie)",
}
COLS_SALIDA = ["rol_id", "cod_comuna", "senal", "nivel", "desvio", "valor_rol", "valor_pares", "n_pares", "exceso_avaluo"]
EDIFICIO = ["cod_comuna", "manzana", "bc1_manzana", "bc1_predio"]


def _nivel(desvio: pl.Expr, umbral: dict) -> pl.Expr:
    return pl.when(desvio >= umbral["fuerte"]).then(pl.lit("fuerte")).when(desvio >= umbral["revisar"]).then(pl.lit("revisar")).otherwise(None)


def base_habitacional(comp: pl.DataFrame) -> pl.DataFrame:
    """Viviendas auditables: destino H, avalúo > 0, construcción reconstruida y sin líneas sin tabla."""
    return comp.filter(
        (pl.col("destino") == "H")
        & (pl.col("avaluo_total") > 0)
        & (pl.col("avaluo_construccion_teo") > 0)
        & ~pl.col("linea_sin_vuc").fill_null(False)
    )


def senal_terreno(h: pl.DataFrame) -> pl.DataFrame:
    casas = h.filter(~pl.col("copropiedad") & (pl.col("sup_terreno_m2") > 0) & (pl.col("terreno_m2_teo") > 0))
    g = ["cod_comuna", "manzana"]
    x = casas.with_columns(
        pl.col("terreno_m2_teo").median().over(g).alias("valor_pares"),
        pl.len().over(g).alias("n_pares"),
    ).filter(pl.col("n_pares") >= MIN_PARES).with_columns(
        (pl.col("terreno_m2_teo") / pl.col("valor_pares") - 1).alias("desvio"),
        ((pl.col("terreno_m2_teo") - pl.col("valor_pares")) * pl.col("sup_terreno_m2")).alias("exceso_avaluo"),
    )
    cand = x.with_columns(
        _nivel(pl.col("desvio"), UMBRAL_CASA).alias("nivel"),
        pl.lit("terreno_sobre_manzana").alias("senal"),
        pl.col("terreno_m2_teo").alias("valor_rol"),
    ).filter(pl.col("nivel").is_not_null() & (pl.col("exceso_avaluo") >= MIN_EXCESO_REL * pl.col("avaluo_total")))
    # Si otras casas de la manzana tienen el mismo terreno/m² (±3%), es otra área homogénea (p. ej. la otra
    # calle de la manzana), no un error: se descarta. La señal queda solo para valores aislados.
    return aislados(cand, x.select(*g, "rol_id", pl.col("terreno_m2_teo").alias("v")), g, AHV_TOL)


def aislados(cand: pl.DataFrame, pares: pl.DataFrame, g: list[str], tol: float) -> pl.DataFrame:
    """Deja los candidatos cuyo valor_rol no lo comparten (±tol en log) otros 2 o más roles de su grupo."""
    vecinos = (
        cand.select("rol_id", *g, "valor_rol")
        .join(pares.rename({"rol_id": "rol_par"}), on=g, nulls_equal=True)
        .filter((pl.col("rol_id") != pl.col("rol_par")) & ((pl.col("v") / pl.col("valor_rol")).log().abs() < tol))
        .group_by("rol_id").len("n_iguales")
    )
    return cand.join(vecinos, on="rol_id", how="left").filter(pl.col("n_iguales").fill_null(0) < 2).drop("n_iguales")


def senal_edificio(h: pl.DataFrame) -> pl.DataFrame:
    d = h.filter(pl.col("copropiedad") & (pl.col("sup_construida_total") > 0) & pl.col("bc1_predio").is_not_null())
    g = EDIFICIO + ["clase_calidad_principal", "anio_construccion_max"]
    x = d.with_columns((pl.col("avaluo_total") / pl.col("sup_construida_total")).alias("valor_rol")).with_columns(
        pl.col("valor_rol").median().over(g).alias("valor_pares"),
        pl.len().over(g).alias("n_pares"),
    ).filter(pl.col("n_pares") >= MIN_PARES).with_columns(
        (pl.col("valor_rol") / pl.col("valor_pares") - 1).alias("desvio"),
        ((pl.col("valor_rol") - pl.col("valor_pares")) * pl.col("sup_construida_total")).alias("exceso_avaluo"),
    )
    cand = x.with_columns(
        _nivel(pl.col("desvio"), UMBRAL_DEPTO).alias("nivel"), pl.lit("avaluo_m2_sobre_edificio").alias("senal")
    ).filter(pl.col("nivel").is_not_null())
    return aislados(cand, x.select(*g, "rol_id", pl.col("valor_rol").alias("v")), g, DEPTO_TOL)


def tabla_vuc(reavaluo: str) -> pl.DataFrame:
    return pl.read_csv(REF / REAVALUOS[reavaluo]["vuc"], separator=";", schema={"clase": pl.Utf8, "calidad": pl.Utf8, "vuc": pl.Float64}).filter(pl.col("calidad").is_not_null())


def senal_calidad(h: pl.DataFrame, vuc: pl.DataFrame) -> pl.DataFrame:
    d = h.filter(pl.col("copropiedad") & pl.col("bc1_predio").is_not_null() & (pl.col("clase_calidad_principal").str.len_chars() >= 2))
    d = d.with_columns(
        pl.col("clase_calidad_principal").str.slice(0, pl.col("clase_calidad_principal").str.len_chars() - 1).alias("clase"),
        pl.col("clase_calidad_principal").str.slice(-1).alias("calidad"),
    )
    g = EDIFICIO + ["clase", "anio_construccion_max"]
    # Moda de la calidad en el grupo; ante empate, la peor (número mayor, más barata)
    moda = (
        d.group_by(g + ["calidad"]).len("k")
        .sort(g + ["k", "calidad"], descending=[False] * len(g) + [True, True], nulls_last=True)
        .group_by(g, maintain_order=True).first()
        .select(*g, pl.col("calidad").alias("calidad_pares"))
    )
    x = d.join(moda, on=g, how="left", nulls_equal=True).with_columns(pl.len().over(g).alias("n_pares")).filter(
        (pl.col("n_pares") >= MIN_PARES) & (pl.col("calidad") < pl.col("calidad_pares"))
    )
    x = x.join(vuc.rename({"calidad": "calidad", "vuc": "vuc_rol"}), on=["clase", "calidad"], how="left").join(
        vuc.rename({"calidad": "calidad_pares", "vuc": "vuc_pares"}), on=["clase", "calidad_pares"], how="left"
    ).filter(pl.col("vuc_rol").is_not_null() & pl.col("vuc_pares").is_not_null())
    return x.with_columns(
        (pl.col("vuc_rol") / pl.col("vuc_pares") - 1).alias("desvio"),
        (pl.col("avaluo_construccion_teo") * (1 - pl.col("vuc_pares") / pl.col("vuc_rol"))).alias("exceso_avaluo"),
        pl.col("calidad").cast(pl.Float64).alias("valor_rol"),
        pl.col("calidad_pares").cast(pl.Float64).alias("valor_pares"),
        pl.lit("revisar").alias("nivel"),
        pl.lit("calidad_sobre_edificio").alias("senal"),
    )


def senal_superficie(h: pl.DataFrame, previo: pl.DataFrame) -> pl.DataFrame:
    x = h.join(previo.select("rol_id", pl.col("sup_construida_total").alias("valor_pares")), on="rol_id").filter(pl.col("valor_pares") > 0)
    x = x.with_columns(
        pl.col("sup_construida_total").cast(pl.Float64).alias("valor_rol"),
        (pl.col("sup_construida_total") / pl.col("valor_pares") - 1).alias("desvio"),
    ).filter((pl.col("desvio") >= 0.10) & (pl.col("sup_construida_total") - pl.col("valor_pares") >= 10))
    return x.with_columns(
        pl.lit(1, dtype=pl.UInt32).alias("n_pares"),
        pl.lit(None, dtype=pl.Float64).alias("exceso_avaluo"),
        pl.lit("revisar").alias("nivel"),
        pl.lit("superficie_aumento").alias("senal"),
    )


def senales(comp: pl.DataFrame, vuc: pl.DataFrame, previo: pl.DataFrame | None = None) -> pl.DataFrame:
    """comp: avaluo_componentes del semestre con bc1_manzana; devuelve una fila por rol × señal (COLS_SALIDA)."""
    h = base_habitacional(comp)
    partes = [senal_terreno(h), senal_edificio(h), senal_calidad(h, vuc)]
    if previo is not None:
        partes.append(senal_superficie(h, previo))
    out = [p.select([pl.col(c).cast(t) for c, t in _ESQUEMA.items()]) for p in partes]
    return pl.concat(out)


_ESQUEMA = {
    "rol_id": pl.Utf8, "cod_comuna": pl.Int32, "senal": pl.Utf8, "nivel": pl.Utf8, "desvio": pl.Float64,
    "valor_rol": pl.Float64, "valor_pares": pl.Float64, "n_pares": pl.UInt32, "exceso_avaluo": pl.Float64,
}


def ahorro_anual(sen: pl.DataFrame, roles: pl.DataFrame, p: dict) -> pl.DataFrame:
    """Contribución anual teórica actual menos la que resulta con (avalúo − exceso)."""
    x = sen.join(roles.select("rol_id", "destino", "avaluo_total", "avaluo_exento"), on="rol_id", how="left", maintain_order="left")
    c0 = contribucion_teorica(x, p)["contrib_teo"]
    corr = x.with_columns(
        (pl.col("avaluo_total") - pl.col("exceso_avaluo").fill_null(0).clip(lower_bound=0)).round(0).cast(pl.Int64).alias("avaluo_total")
    )
    c1 = contribucion_teorica(corr, p)["contrib_teo"]
    return x.drop("destino", "avaluo_total", "avaluo_exento").with_columns(((c0 - c1) * 2).round(0).alias("ahorro_anual"))


def cargar(semestre: str, comuna: int) -> pl.DataFrame:
    comp = pl.scan_parquet(STAGING / f"avaluo_componentes_{semestre}.parquet").filter(pl.col("cod_comuna") == comuna).collect()
    bc = pl.scan_parquet(STAGING / "catastro" / f"roles_{semestre}.parquet").filter(pl.col("cod_comuna") == comuna).select("rol_id", "bc1_manzana").collect()
    return comp.join(bc, on="rol_id", how="left")


def lineas_resumen(semestre: str, comuna: int) -> pl.DataFrame:
    return (
        pl.scan_parquet(STAGING / "catastro" / f"lineas_{semestre}.parquet").filter(pl.col("cod_comuna") == comuna)
        .group_by("rol_id").agg(
            pl.col("sup_construida").sum().alias("sup"),
            (pl.col("material") + "|" + pl.col("calidad").fill_null("") + "|" + pl.col("anio_construccion").cast(pl.Utf8) + "|" + pl.col("sup_construida").cast(pl.Utf8)).sort().str.join(",").alias("firma"),
        ).collect()
    )


def params(semestre: str) -> dict:
    c = pl.scan_parquet(STAGING / f"contribucion_{semestre}.parquet").select("exento_h_semestre", "cambio_tasa_semestre").head(1).collect()
    tasas = pl.read_csv(REF / "parametros_impuesto.csv", separator=";", infer_schema_length=0).filter(pl.col("semestre") == semestre).row(0, named=True)
    return {"exento_h": float(c["exento_h_semestre"][0]), "cambio_tasa": float(c["cambio_tasa_semestre"][0]), **{k: float(tasas[k]) for k in ("t1", "t2", "t_no_h", "sobretasa")}}


def resultado_backtest(sen: pl.DataFrame, univ: pl.DataFrame) -> dict:
    """univ: rol_id, sin_cambio, bajo (avalúo 2026-2S < 98% del reajuste común). Precisión por señal y nivel vs. tasa base."""
    from scipy.stats import binomtest  # solo en el backtest (el servicio no necesita scipy)

    u = univ.filter("sin_cambio")
    base = float(u["bajo"].mean()) if u.height else float("nan")
    out = {"universo_sin_cambio_fisico": u.height, "tasa_base_baja": round(base, 5), "por_senal": {}}
    x = sen.join(u.select("rol_id", "bajo"), on="rol_id")
    for (s, n), g in x.group_by(["senal", "nivel"]):
        out["por_senal"][f"{s}:{n}"] = {
            "roles": g.height,
            "bajados": int(g["bajo"].sum()),
            "precision": round(float(g["bajo"].mean()), 5),
            "veces_tasa_base": round(float(g["bajo"].mean()) / base, 1) if base else None,
            "p_binomial_unilateral": float(f"{binomtest(int(g['bajo'].sum()), g.height, base, 'greater').pvalue:.3g}") if base else None,
        }
    return out


def main() -> None:
    rep = Reporte("auditoria_roles")
    vuc22 = tabla_vuc(SEMESTRE_REAVALUO["2026_2"])
    p26 = params("2026_2")
    ex = {s: params(s)["exento_h"] for s in ("2022_1", "2026_2")}
    reajuste = ex["2026_2"] / ex["2022_1"]
    salida, bt_sen, bt_univ = [], [], []
    n_entrada = n_aud = 0
    for c in GRAN_SANTIAGO:
        comp = cargar("2026_2", c)
        if not comp.height:
            continue
        previo = cargar("2022_1", c)
        n_entrada += comp.height
        n_aud += base_habitacional(comp).height
        sen = senales(comp, vuc22, previo.select("rol_id", "sup_construida_total"))
        roles = pl.scan_parquet(STAGING / "catastro" / "roles_2026_2.parquet").filter(pl.col("cod_comuna") == c).select("rol_id", "destino", "avaluo_total", "avaluo_exento").collect()
        salida.append(ahorro_anual(sen, roles, p26))
        # Backtest: señales con 2022-1S (sin la de superficie) y resultado en 2026-2S
        sen22 = senales(previo, vuc22)
        la, lb = lineas_resumen("2022_1", c), lineas_resumen("2026_2", c)
        univ = (
            base_habitacional(previo).select("rol_id", "avaluo_total", "sup_terreno_m2")
            .join(comp.select("rol_id", pl.col("avaluo_total").alias("av26"), pl.col("sup_terreno_m2").alias("st26")), on="rol_id")
            .join(la, on="rol_id", how="left").join(lb, on="rol_id", how="left", suffix="26")
            .select(
                "rol_id",
                ((pl.col("firma") == pl.col("firma26")) & (pl.col("sup_terreno_m2") == pl.col("st26"))).fill_null(False).alias("sin_cambio"),
                (pl.col("av26") < 0.98 * pl.col("avaluo_total") * reajuste).alias("bajo"),
            )
        )
        bt_sen.append(sen22.select("rol_id", "senal", "nivel"))
        bt_univ.append(univ)
        print(f"[auditoria] {c}: {sen.height} señales", flush=True)
    out = pl.concat(salida)
    rep.entrada = n_entrada
    rep.descartar("no_auditable (no H, avalúo 0, sin construcción o línea sin tabla)", n_entrada - n_aud)
    sin_senal = n_aud - out["rol_id"].n_unique()
    rep.descartar("sin_senal", sin_senal)
    rep.notas["roles_con_senal"] = out["rol_id"].n_unique()
    rep.notas["filas_rol_x_senal"] = out.height
    rep.notas["por_senal_nivel"] = {f"{s}:{n}": k for s, n, k in out.group_by("senal", "nivel").len().sort("senal", "nivel").iter_rows()}
    rep.notas["ahorro_anual_mediano_$_fuertes"] = {s: float(g["ahorro_anual"].median()) for (s,), g in out.filter(pl.col("nivel") == "fuerte").group_by(["senal"])}
    rep.notas["reajuste_comun_2022_1_a_2026_2"] = round(reajuste, 5)
    rep.notas["backtest_2022"] = resultado_backtest(pl.concat(bt_sen), pl.concat(bt_univ))
    out.write_parquet(MARTS / "auditoria_roles_2026_2.parquet", compression="zstd")
    rep.cerrar(out["rol_id"].n_unique())


if __name__ == "__main__":
    main()
