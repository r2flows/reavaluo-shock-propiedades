from pathlib import Path

import polars as pl

from src.etl import catastro_agricola as ca
from src.etl.common import Reporte

FIX = Path(__file__).parent / "fixtures"


def _lineas(nombre: str) -> list[str]:
    return FIX.joinpath(nombre).read_bytes().decode("latin1").splitlines(keepends=True)


def test_roles_agricolas_vigente():
    rep = Reporte("test_agricola_roles")
    df = ca.parse_roles(_lineas("catastro_A_vigente.txt"), None, rep)
    assert rep.entrada == 25 and rep.descartes["n_campos_4"] == 1 and df.height == 24
    assert dict(df.group_by("cod_ubicacion").len().iter_rows()) == {"U": 8, "R": 12, "E": 4}
    assert df.schema["avaluo_total"] == pl.Int64 and df["destino"].is_in(["A", "B", "F"]).all()
    assert df["rol_id"].str.starts_with("14109-").all()
    assert (df["avaluo_exento"] <= df["avaluo_total"]).all()


def test_roles_agricolas_historico_sin_ubicacion():
    linea = "01101|00675|00010|SANTA ROSA                              |000001189252018|0000002987628|A|000000026751232\n"
    df = ca.parse_roles([linea], None, Reporte("t"))
    assert df["cod_ubicacion"][0] is None and df["rol_id"][0] == "1101-675-10"


def test_suelos_y_construcciones():
    rep = Reporte("test_agricola_lineas")
    suelos, constr = ca.parse_lineas(_lineas("catastro_AL_vigente.txt"), None, rep)
    assert rep.entrada == 25
    assert suelos.height == 18 and constr.height == 6
    assert rep.descartes["linea_sin_suelo_ni_construccion"] == 1
    assert rep.entrada == suelos.height + constr.height + sum(rep.descartes.values())
    # Superficie en hectáreas con 2 decimales implícitos: 00000001520 → 15,20 ha
    assert suelos.filter(pl.col("rol_id") == "14109-925-17")["sup_ha"][0] == 15.20
    assert set(suelos["cod_suelo"]) <= set(ca.clases_suelo()["cod_suelo"])
    assert (constr["linea"] > 0).all() and constr["pisos"].is_not_null().all()


def test_tabla_de_clases_completa():
    cs = ca.clases_suelo()
    assert cs["cod_suelo"].n_unique() == cs.height == 22
    assert {"1R", "2R", "3R", "4R", "1", "8", "20", "29"} <= set(cs["cod_suelo"])
