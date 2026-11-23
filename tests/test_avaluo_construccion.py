import polars as pl
import pytest

from src.features.avaluo_construccion import valorar_lineas


def _lineas(filas):
    schema = {
        "rol_id": pl.Utf8,
        "cod_comuna": pl.Int32,
        "material": pl.Utf8,
        "calidad": pl.Utf8,
        "anio_construccion": pl.Int32,
        "sup_construida": pl.Int64,
        "condicion_especial": pl.Utf8,
    }
    return pl.DataFrame(filas, schema=schema, orient="row")


def test_hormigon_calidad3_depreciado():
    # B3 2022: 603.660 $/m2; edad 2021-2001 = 20 años x 0,8% = 16% → DP 0,84; FC Ñuñoa 1,0
    df = valorar_lineas(_lineas([("r", 15105, "B", "3", 2001, 100, None)]), "2022", 1.0)
    assert df["avaluo_linea"][0] == pytest.approx(603_660 * 100 * 0.84)


def test_tope_depreciacion_y_factor_comunal_maipu():
    # C4 1900: depreciación topada en 60% → DP 0,4; FC Maipú 0,9; subterráneo 0,7
    df = valorar_lineas(_lineas([("r", 14109, "C", "4", 1900, 50, "SB")]), "2022", 1.051)
    assert df["avaluo_linea"][0] == pytest.approx(259_264 * 50 * 0.4 * 0.9 * 0.7 * 1.051)


def test_madera_y_reavaluo_2018():
    # E3 2018: 337.858 $/m2; edad 2017-2007 = 10 x 1,5% → 0,85; FC Maipú 2018 = 0,8
    df = valorar_lineas(_lineas([("r", 14109, "E", "3", 2007, 60, None)]), "2018", 1.0)
    assert df["avaluo_linea"][0] == pytest.approx(337_858 * 60 * 0.85 * 0.8)


def test_obra_complementaria_sin_depreciacion():
    df = valorar_lineas(_lineas([("r", 15103, "W", None, 1990, 30, None)]), "2022", 1.0)
    assert df["avaluo_linea"][0] == pytest.approx(164_608 * 30)
