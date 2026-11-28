"""Comparables depurados para un rol: ventas cercanas y parecidas, sin transacciones fuera de mercado.

Reglas (en orden; cada descarte se cuenta por motivo):
  1. Ventas habitacionales con precio, de los últimos `anios` años y del mismo tipo (casa o departamento).
  2. Fuera: la propia venta del rol, la primera venta de obra nueva y los outliers de precio del mart.
  3. Fuera de mercado (hallazgo de P2): precio ÷ avalúo menor que la mitad de la mediana de su microbarrio y
     semestre (residuo_prop < log 0,5). Suelen ser cuotas de herencia, ventas entre relacionados o con rebaja.
  4. Superficie construida entre 0,7× y 1,43× la del rol (si se conoce).
  5. Primero el microbarrio; si quedan menos de 5, se amplía al barrio.
Orden: parecido en superficie (|log m² / m²_rol|) + 0,1 por año de antigüedad.

Los montos de las ventas van en UF a la fecha de la escritura (F2890). No hay datos personales: solo rol, fecha y monto.
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl

MIN_LOCAL = 5
FUERA_MERCADO = math.log(0.5)
COLS = [
    "rol_principal", "fecha_escritura", "anio", "microbarrio_id", "barrio_id", "destino_principal", "copropiedad",
    "sup_construida_total", "monto_uf", "uf_m2", "ratio_ia", "residuo_prop", "outlier_precio", "primera_venta_obra_nueva",
]


def seleccionar(ventas: pl.DataFrame, obj: dict, n: int = 10, anios: int = 3, hoy: date | None = None) -> tuple[pl.DataFrame, dict]:
    """obj: rol_id, microbarrio_id, barrio_id, copropiedad, sup_construida_total. Devuelve (comparables, conteos)."""
    hoy = hoy or date.today()
    cuenta: dict[str, int] = {}

    def paso(df: pl.DataFrame, cond: pl.Expr, motivo: str) -> pl.DataFrame:
        out = df.filter(cond)
        cuenta[motivo] = df.height - out.height
        return out

    v = ventas.filter(
        (pl.col("destino_principal") == "H") & (pl.col("monto_uf") > 0) & pl.col("ratio_ia").is_not_null()
        & (pl.col("fecha_escritura") >= date(hoy.year - anios, hoy.month, 1))
        & (pl.col("copropiedad").fill_null(False) == bool(obj.get("copropiedad")))
    )
    cuenta["entrada"] = v.height
    v = paso(v, pl.col("rol_principal") != obj["rol_id"], "venta_del_mismo_rol")
    v = paso(v, ~pl.col("primera_venta_obra_nueva").fill_null(False), "obra_nueva")
    v = paso(v, ~pl.col("outlier_precio").fill_null(False), "outlier_precio")
    v = paso(v, pl.col("residuo_prop").is_null() | (pl.col("residuo_prop") >= FUERA_MERCADO), "fuera_de_mercado")
    sup = obj.get("sup_construida_total") or 0
    if sup > 0:
        v = paso(v, pl.col("sup_construida_total").is_between(0.7 * sup, sup / 0.7), "superficie_distinta")
    local = v.filter(pl.col("microbarrio_id") == obj.get("microbarrio_id"))
    ambito = "microbarrio"
    if local.height < MIN_LOCAL and obj.get("barrio_id"):
        local, ambito = v.filter(pl.col("barrio_id") == obj["barrio_id"]), "barrio"
    cuenta["fuera_del_ambito"] = v.height - local.height
    dist = (pl.col("sup_construida_total") / sup).log().abs() if sup > 0 else pl.lit(0.0)
    out = (
        local.with_columns((dist + 0.1 * (hoy.year - pl.col("anio"))).alias("distancia"))
        .sort("distancia", "fecha_escritura", descending=[False, True])
        .head(n)
    )
    cuenta["salida"] = out.height
    cuenta["ambito"] = ambito
    return out, cuenta


def resumen(comp: pl.DataFrame, avaluo_uf: float | None, sup: float | None) -> dict:
    """Medianas de los comparables y cuánto representa el avalúo del rol del precio típico (avalúo ÷ precio)."""
    if comp.height < 3:
        return {"n": comp.height}
    uf_m2 = float(comp["uf_m2"].median()) if comp["uf_m2"].null_count() < comp.height else None
    precio_tipico = uf_m2 * sup if (uf_m2 and sup) else float(comp["monto_uf"].median())
    r = {
        "n": comp.height,
        "uf_m2_mediana": uf_m2,
        "precio_tipico_uf": precio_tipico,
        "precio_avaluo_mediana": float(comp["ratio_ia"].median()),
        "rango_uf": (float(comp["monto_uf"].quantile(0.25)), float(comp["monto_uf"].quantile(0.75))),
    }
    if avaluo_uf and precio_tipico:
        r["avaluo_sobre_precio"] = avaluo_uf / precio_tipico
    return r
