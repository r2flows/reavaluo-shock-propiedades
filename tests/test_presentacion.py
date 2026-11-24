import json
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web" / "data"
pytestmark = pytest.mark.skipif(not (WEB / "comunas.json").exists(), reason="agregados no generados")


def _datos():
    return json.loads((WEB / "comunas.json").read_text(encoding="utf8")), json.loads((WEB / "comunas.geojson").read_text(encoding="utf8"))


def test_todas_las_comunas_tienen_poligono_y_datos():
    d, g = _datos()
    cuts_geo = {f["properties"]["cut"] for f in g["features"]}
    cuts_dat = {c["cut"] for c in d["comunas"]}
    assert len(cuts_geo) == 34 and cuts_geo == cuts_dat


def test_sin_datos_por_rol():
    texto = (WEB / "comunas.json").read_text(encoding="utf8")
    assert "rol_id" not in texto and "rol_principal" not in texto


def test_supresion_n_minimo():
    d, _ = _datos()
    for c in d["comunas"]:
        if (c.get("n_ventas_2426") or 0) < d["n_min"]:
            assert c["rec_aval_precio_mediano"] is None and c["mer_ret_22_25_pct"] is None


def test_viviendas_cuadran_con_gran_santiago():
    d, _ = _datos()
    total = sum(c["viviendas"] for c in d["comunas"])
    assert 2_100_000 < total < 2_300_000  # 2,18 MM viviendas en el mart de reavalúo 2027


def _micro():
    d = json.loads((WEB / "microbarrios.json").read_text(encoding="utf8"))
    return [dict(zip(d["campos"], r)) for filas in d["comunas"].values() for r in filas]


def test_micro_supresion_y_rangos():
    for r in _micro():
        assert "rol" not in str(r["id"]).lower()
        if (r["n_ventas_2426"] or 0) < 30:
            assert r["rec_aval_precio_mediano"] is None and r["uf_m2_mediano_2426"] is None and r["bre_cambio_pct"] is None
        if r["uf_m2_mediano_2426"] is not None:
            assert 3 < r["uf_m2_mediano_2426"] < 400


def test_micro_nombres_unicos_y_sin_numeros():
    import re
    from collections import Counter

    filas = _micro()
    con_nombre = [r for r in filas if r["nombre"]]
    assert len(con_nombre) / len(filas) > 0.95
    por_comuna = Counter((r["id"].split("-")[0], r["nombre"]) for r in con_nombre)
    assert max(por_comuna.values()) == 1, "nombres repetidos dentro de una comuna"
    for r in con_nombre:
        assert not re.search(r"\d{3,}|[A-Za-z]\d", r["nombre"].split(" (mz")[0]), r["nombre"]  # sin números de casa (sí "21 de Mayo")
        assert all(0 <= p <= 100 for _, p in r["calles"])
        if r["rotacion_anual_pct"] is not None:
            assert 0 <= r["rotacion_anual_pct"] < 50


def test_indice_calles_sin_numeros_ni_roles():
    import re

    idx = json.loads((WEB / "calles.json").read_text(encoding="utf8"))
    ids = {r["id"] for r in _micro()}
    for cut, cs in idx.items():
        for calle, mids in cs.items():
            assert not re.search(r"\d{3,}|[A-Za-z]\d", calle), calle
            assert set(mids) <= ids
