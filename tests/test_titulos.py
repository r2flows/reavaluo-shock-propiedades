import polars as pl
import pytest

from src.etl.common import STAGING
from src.titulos import preinforme as pi


def test_resolver_formatos():
    assert pi.resolver("13101-0152-0779", None) == ["13101-152-779"]
    assert set(pi.resolver("152-779", "santiago")) == {"13101-152-779", "13134-152-779", "13135-152-779"}
    with pytest.raises(SystemExit):
        pi.resolver("152-779", None)
    with pytest.raises(SystemExit):
        pi.resolver("152-779", "Valparaíso")


def test_tipico_exige_30_ventas():
    ref = pl.DataFrame({"anio": [2024] * 29, "ratio_ia": [1.0] * 29, "uf_m2": [50.0] * 29})
    assert pi.tipico(ref, 2024, "ratio_ia") == (None, 29)
    ref = pl.concat([ref, ref])
    assert pi.tipico(ref, 2025, "ratio_ia") == (1.0, 58)
    assert pi.tipico(ref, 2027, "ratio_ia")[0] is None  # fuera de ±1 año


@pytest.mark.skipif(not (STAGING / "f2890.parquet").exists(), reason="datos no generados")
def test_informe_sin_datos_personales(tmp_path):
    rid = pl.scan_parquet(STAGING / "f2890.parquet").filter(pl.col("cod_comuna") == 16163).select("rol_id").head(1).collect()["rol_id"][0]
    d = pi.leer([rid])
    h = pi.informe(d)
    assert rid in h and "Cadena de transferencias" in h
    assert "RUT" not in h.upper().replace("RUTA", "")  # no hay RUT ni campos de personas
    assert d["transf"]["fecha_escritura"].dt.year().min() >= pi.ANIO_MIN
