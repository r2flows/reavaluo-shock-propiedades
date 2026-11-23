"""Casos de la guía oficial del SII para calcular la contribución (reavalúo 2022)."""

import polars as pl
import pytest

from src.features.contribucion import CUOTA_MIN_GRADUAL_2022, aplicar_gradualidad, contribucion_teorica

P22 = {"exento_h": 47_360_490, "cambio_tasa": 169_144_585, "t1": 0.00893, "t2": 0.01042, "t_no_h": 0.01042, "sobretasa": 0.00025}


def _calc(total, exento, destino="H"):
    df = pl.DataFrame({"avaluo_total": [total], "avaluo_exento": [exento], "destino": [destino]})
    return contribucion_teorica(df, P22).row(0, named=True)


@pytest.mark.parametrize(
    "total,exento,neta_anual",
    [
        (29_439_418, 29_439_418, 0),  # casa exenta
        (100_486_104, 47_360_490, 474_412),  # depto, tramo 1
        (179_793_163, 47_360_490, 1_198_490),  # casa, dos tramos
        (163_000_922, 81_500_461, 727_800),  # DFL2 (exención 50%)
    ],
)
def test_ejemplos_guia_sii(total, exento, neta_anual):
    r = _calc(total, exento)
    assert r["contrib_neta_teo"] * 2 == pytest.approx(neta_anual, abs=2)


def test_sobretasa_fiscal_habitacional():
    r = _calc(200_000_000, 47_360_490)
    assert r["sobretasas_teo"] * 2 == pytest.approx(7_714, abs=1)


def test_no_habitacional():
    r = _calc(100_000_000, 0, "C")
    assert r["contrib_neta_teo"] * 2 == pytest.approx(1_042_000)
    assert r["sobretasas_teo"] * 2 == pytest.approx(25_000)


def test_gradualidad_ejemplo_guia():
    # Cuota trimestral 10.000 → 30.000: el 1S-2022 paga 12.500 (+25%).
    df = pl.DataFrame({"nueva": [60_000.0], "base": [20_000.0]})
    out = df.select(aplicar_gradualidad(pl.col("nueva"), pl.col("base")).alias("x"))["x"][0]
    assert out / 2 == pytest.approx(12_500)


def test_gradualidad_exento_a_afecto_y_cuota_baja():
    df = pl.DataFrame({"nueva": [100_000.0, 15_000.0], "base": [0.0, 0.0]})
    out = df.select(aplicar_gradualidad(pl.col("nueva"), pl.col("base")).alias("x"))["x"].to_list()
    assert out[0] / 2 == CUOTA_MIN_GRADUAL_2022  # pasa a afecto: tope 9.415 por cuota
    assert out[1] == 15_000.0  # cuota ≤ 9.415: paga todo
