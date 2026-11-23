from datetime import date
from pathlib import Path

import polars as pl

from src.etl import f2890
from src.etl.common import Reporte

FIX = Path(__file__).parent / "fixtures" / "f2890_muestra.txt"


def _uf() -> pl.DataFrame:
    # UF sintética constante: basta para probar la normalización.
    fechas = pl.date_range(date(1990, 1, 1), date(2026, 12, 31), "1d", eager=True)
    return pl.DataFrame({"fecha": fechas, "uf": [30000.0] * len(fechas)})


def _procesar():
    raw = f2890.leer_texto(FIX.read_bytes().decode("latin1"))
    rep = Reporte("test_f2890")
    df = f2890.transformar(raw, _uf(), date(2026, 10, 30), rep)
    return raw, df, rep


def test_esquema_y_columnas():
    raw = f2890.leer_texto(FIX.read_bytes().decode("latin1"))
    assert raw.columns == f2890.COLUMNAS
    assert raw.height == 50  # 51 líneas menos el encabezado


def test_conservacion_de_filas():
    raw, df, rep = _procesar()
    assert rep.entrada == raw.height
    assert rep.entrada == df.height + sum(rep.descartes.values())


def test_descartes_por_motivo():
    _, df, rep = _procesar()
    assert rep.descartes["comuna_desconocida"] == 1
    assert rep.descartes["fecha_escritura_fuera_de_rango"] >= 3  # escrituras con año 2099
    assert rep.descartes["duplicado_exacto"] == 1
    assert df["fecha_escritura"].max() <= date(2026, 10, 30)


def test_codigo_comuna_y_rol():
    _, df, _ = _procesar()
    assert set(df["cod_comuna"].unique()) <= {15105, 15103, 14109}
    fila = df.filter(pl.col("cod_comuna") == 15103).row(0, named=True)
    assert fila["rol_id"] == f"15103-{fila['manzana']}-{fila['predio']}"


def test_normalizacion_uf():
    _, df, _ = _procesar()
    clp = df.filter(pl.col("unidad_origen") == "CLP")
    assert clp.height > 0
    assert (clp["monto_uf_norm"] - clp["monto_pesos"] / 30000.0).abs().max() < 1e-9
    uf = df.filter(pl.col("unidad_origen") == "UF")
    assert (uf["monto_uf_norm"] == uf["monto_uf"]).all()
    sin = df.filter(pl.col("unidad_origen") == "sin_monto")
    assert sin.height > 0 and sin["monto_uf_norm"].is_null().all()
