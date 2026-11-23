from datetime import date

import polars as pl

from src.etl.escrituras import agrupar

D1, D2 = date(2021, 3, 1), date(2021, 4, 1)


def _tr(filas):
    cols = ["rol_id", "cod_comuna", "manzana", "fecha_escritura", "fecha_inscripcion", "destino", "avaluo_total", "monto_uf_norm"]
    df = pl.DataFrame(filas, schema=cols, orient="row")
    return df.with_columns(pl.lit(False).alias("primera_venta_obra_nueva"))


def test_depto_con_anexos_monto_global():
    # Depto + bodega + estacionamiento: monto en un solo rol, 0 en los anexos → una escritura.
    tr, esc = agrupar(_tr([
        ("15105-1-10", 15105, 1, D1, D2, "H", 50_000_000, 3000.0),
        ("15105-1-200", 15105, 1, D1, D2, "L", 2_000_000, 0.0),
        ("15105-1-300", 15105, 1, D1, D2, "Z", 3_000_000, 0.0),
    ]))
    assert esc.height == 1
    fila = esc.row(0, named=True)
    assert fila["rol_principal"] == "15105-1-10"
    assert fila["monto_uf"] == 3000.0 and fila["regla_monto"] == "unico"
    assert fila["tipo_grupo"] == "con_anexos" and fila["n_roles"] == 3


def test_monto_repetido_no_se_duplica():
    _, esc = agrupar(_tr([
        ("15105-2-10", 15105, 2, D1, D2, "H", 50_000_000, 3000.0),
        ("15105-2-200", 15105, 2, D1, D2, "Z", 2_000_000, 3000.0),
    ]))
    fila = esc.row(0, named=True)
    assert fila["monto_uf"] == 3000.0 and fila["regla_monto"] == "repetido"


def test_montos_distintos_se_suman():
    _, esc = agrupar(_tr([
        ("15105-3-10", 15105, 3, D1, D2, "H", 50_000_000, 3000.0),
        ("15105-3-200", 15105, 3, D1, D2, "Z", 2_000_000, 300.0),
    ]))
    assert esc.row(0, named=True)["monto_uf"] == 3300.0


def test_varios_habitacionales_son_ventas_separadas():
    tr, esc = agrupar(_tr([
        ("15105-4-10", 15105, 4, D1, D2, "H", 50_000_000, 3000.0),
        ("15105-4-11", 15105, 4, D1, D2, "H", 52_000_000, 3100.0),
        ("15105-4-300", 15105, 4, D1, D2, "Z", 3_000_000, 0.0),
    ]))
    assert esc.height == 2
    assert sorted(esc["monto_uf"].to_list()) == [3000.0, 3100.0]
    assert tr.filter(pl.col("rol_id") == "15105-4-300")["escritura_id"].is_null().all()


def test_fechas_distintas_no_se_agrupan():
    _, esc = agrupar(_tr([
        ("15105-5-10", 15105, 5, D1, D2, "H", 50_000_000, 3000.0),
        ("15105-5-11", 15105, 5, D2, D2, "H", 50_000_000, 3200.0),
    ]))
    assert esc.height == 2
