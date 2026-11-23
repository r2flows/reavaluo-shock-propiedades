from pathlib import Path

import polars as pl

from src.etl import catastro
from src.etl.common import Reporte

FIX = Path(__file__).parent / "fixtures"


def _lineas(nombre: str) -> list[str]:
    return FIX.joinpath(nombre).read_bytes().decode("latin1").splitlines(keepends=True)


def test_roles_esquema_y_filtro_comuna():
    rep = Reporte("test_roles")
    df = catastro.parse_roles(_lineas("catastro_N_2022_1.txt"), {15105}, rep)
    assert rep.entrada == 49
    assert rep.descartes["n_campos_4"] == 1
    assert rep.descartes["fuera_de_comunas_seleccionadas"] == 25
    assert df.height == 23
    assert rep.entrada == df.height + sum(rep.descartes.values())
    assert df.schema["avaluo_total"] == pl.Int64
    assert df.schema["contrib_semestral"] == pl.Int64
    assert set(df["cod_comuna"].unique()) == {15105}
    # Campos de la estructura vigente no existen en el histórico
    assert df["padre_predio"].is_null().all()
    assert df["rol_id"].str.starts_with("15105-").all()
    # El avalúo exento nunca supera al total
    assert (df["avaluo_exento"] <= df["avaluo_total"]).all()


def test_roles_sin_filtro():
    rep = Reporte("test_roles_todas")
    df = catastro.parse_roles(_lineas("catastro_N_2022_1.txt"), None, rep)
    assert df.height == 48
    assert df.filter(pl.col("cod_comuna") == 1101).height == 25


def test_lineas_esquema():
    rep = Reporte("test_lineas")
    df = catastro.parse_lineas(_lineas("catastro_NL_2022_1.txt"), None, rep)
    assert df.height == 48 and not rep.descartes
    assert df.schema["anio_construccion"] == pl.Int32
    assert df["calidad"].drop_nulls().is_in(["1", "2", "3", "4", "5"]).all()
    assert df["pisos"].is_null().all()
    assert (df["sup_construida"] >= 0).all()


def test_estructura_vigente_con_rol_padre():
    rep = Reporte("test_roles_vigente")
    df = catastro.parse_roles(_lineas("catastro_N_vigente.txt"), None, rep)
    assert not rep.descartes and df.height == 25
    assert df["cod_ubicacion"].is_not_null().all()
    assert df.filter(pl.col("padre_predio") > 0).height >= 5
    rep = Reporte("test_lineas_vigente")
    li = catastro.parse_lineas(_lineas("catastro_NL_vigente.txt"), None, rep)
    assert not rep.descartes and li.height == 25
    assert li["pisos"].is_not_null().all()
