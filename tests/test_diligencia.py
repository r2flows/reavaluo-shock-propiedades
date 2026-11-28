"""Reglas de debida diligencia de terrenos: un caso positivo y uno negativo por regla (roles sintéticos)."""

import datetime as dt

import polars as pl
import pytest

from src.producto import diligencia as dg

HOY = dt.date(2026, 11, 28)
D = dt.date


def _transf(filas):
    return pl.DataFrame(filas, schema={"fecha_escritura": pl.Date, "fecha_inscripcion": pl.Date, "monto_uf_norm": pl.Float64}, orient="row")


def _caso(**kw):
    rol = {"cod_comuna": 14109, "avaluo_total": 100_000_000, "cod_ubicacion": "U", "sup_terreno_m2": 300, "padre_predio": 0}
    rol |= kw.pop("rol", {})
    base = {"rol_id": "14109-1-1", "serie": "No agrícola", "semestre": "2026-2S", "rol": rol, "suelos": pl.DataFrame(),
            "transf": _transf([(D(2019, 5, 2), D(2019, 6, 1), 4000.0)]), "uf_avaluo": 40_000.0, "fechas_en_bloque": [],
            "sup_aumento": None, "r27": None, "linaje_alta": False}
    return base | kw


def reglas(d):
    return {a.regla: a.nivel for a in dg.evaluar(d, HOY)}


# (caso, regla esperada o None si la regla NO debe aparecer, regla vigilada)
CASOS = [
    (_caso(transf=_transf([(D(2018, 1, 1), None, 3000.0), (D(2023, 3, 1), None, 0.0)])), "herencia_probable", True),
    (_caso(transf=_transf([(D(2023, 3, 1), None, 0.0)]), fechas_en_bloque=[D(2023, 3, 1)]), "herencia_probable", False),  # en bloque: el monto va en otro rol
    (_caso(transf=_transf([(D(2008, 3, 1), None, 0.0)])), "herencia_probable", False),  # antes de 2015 casi nunca hay monto
    (_caso(transf=_transf([(D(2023, 3, 1), None, 2500.0)])), "herencia_probable", False),
    (_caso(transf=_transf([(D(2017, 1, 1), None, 0.0), (D(2023, 3, 1), None, 2500.0)])), "transferencias_sin_monto", True),
    (_caso(transf=_transf([(D(2021, 4, 9), None, 900.0), (D(2021, 4, 9), None, 900.0)])), "cuotas_mismo_dia", True),
    (_caso(transf=_transf([(D(2010, 4, 9), None, 900.0), (D(2010, 4, 9), None, 900.0)])), "cuotas_mismo_dia", False),  # hace más de 10 años
    (_caso(transf=_transf([(D(2024, 2, 1), None, 1000.0)])), "precio_bajo_avaluo", True),  # avalúo 2.500 UF, precio 1.000 UF
    (_caso(transf=_transf([(D(2024, 2, 1), None, 1300.0)])), "precio_bajo_avaluo", False),
    (_caso(transf=_transf([(D(2020, 2, 1), None, 1000.0)])), "precio_bajo_avaluo", False),  # antes del reavalúo 2022
    (_caso(transf=_transf([(D(2022, 2, 1), None, 3000.0), (D(2023, 2, 1), None, 3100.0), (D(2025, 2, 1), None, 3200.0)])), "rotacion_alta", True),
    (_caso(transf=_transf([(D(2023, 2, 1), None, 3100.0), (D(2025, 2, 1), None, 3200.0)])), "rotacion_alta", False),
    (_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 2500}), "subdivision_rural", True),
    (_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 5000}), "subdivision_rural", False),
    (_caso(rol={"cod_ubicacion": "U", "sup_terreno_m2": 2500}), "subdivision_rural", False),
    (_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 0}), "subdivision_rural", False),  # sin superficie: no se afirma nada
    (_caso(serie="Agrícola", rol={"cod_ubicacion": "R", "sup_terreno_m2": 2500}), "subdivision_rural", False),
    (_caso(rol={"padre_predio": 77, "padre_comuna": 14109, "padre_manzana": 1}), "rol_nuevo", True),
    (_caso(linaje_alta=True), "rol_nuevo", True),
    (_caso(), "rol_nuevo", False),
    (_caso(rol={"cod_ubicacion": "E"}), "extension_urbana", True),
    (_caso(serie="Agrícola", suelos=pl.DataFrame({"cod_suelo": ["2R", "6"], "sup_ha": [3.5, 10.0]})), "suelo_riego", True),
    (_caso(serie="Agrícola", suelos=pl.DataFrame({"cod_suelo": ["6", "8"], "sup_ha": [3.5, 10.0]})), "suelo_riego", False),
    (_caso(sup_aumento={"antes": 90.0, "despues": 140.0}), "superficie_aumento", True),
    (_caso(r27={"min": 100_000.0, "max": 180_000.0, "hoy": 95_000.0}), "contribuciones_2027", True),
    (_caso(transf=None), "herencia_probable", False),
]


@pytest.mark.parametrize("caso,regla,debe", CASOS)
def test_reglas(caso, regla, debe):
    assert (regla in reglas(caso)) is debe


def test_niveles_y_textos():
    r = reglas(_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 2500}, transf=_transf([(D(2023, 3, 1), None, 0.0)])))
    assert r["subdivision_rural"] == "alerta" and r["herencia_probable"] == "revisar"
    a = dg.evaluar(_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 2500}), HOY)
    assert "2.500 m²" in a[0].texto and "DL 3.516" in a[0].texto


def test_semaforo_y_documentos():
    al = dg.evaluar(_caso(serie="Agrícola", suelos=pl.DataFrame({"cod_suelo": ["1R"], "sup_ha": [2.0]})), HOY)
    sem = dict((n, e) for n, e, _ in dg.semaforo(al))
    assert sem["Agua"] == "revisar"
    assert sem["Hipotecas, gravámenes, deudas y litigios"] == "no verificado"  # nunca "sin alertas" sin certificados
    assert sem["Dominio, herencias y cuotas"] == "sin alertas"
    docs = dg.documentos(al)
    assert docs[: len(dg.DOCS_BASE)] == dg.DOCS_BASE and any("derechos de agua" in x for x in docs)


def test_html_no_dice_sin_problemas():
    h = dg.html_seccion(dg.evaluar(_caso(), HOY))
    assert "no un estudio de títulos" in h and "no que no existan" in h


def test_formato_de_numeros():
    t = {a.regla: a.texto for a in dg.evaluar(_caso(rol={"cod_ubicacion": "R", "sup_terreno_m2": 2500}), HOY)}
    assert "con 2.500 m², bajo el mínimo de 0,5 ha" in t["subdivision_rural"]
    t = {a.regla: a.texto for a in dg.evaluar(_caso(serie="Agrícola", suelos=pl.DataFrame({"cod_suelo": ["2R"], "sup_ha": [1234.5]})), HOY)}
    assert t["suelo_riego"].startswith("1.234,50 ha") and "inscritos, el predio" in t["suelo_riego"]
    t = {a.regla: a.texto for a in dg.evaluar(_caso(r27={"min": 0.0, "max": 0.0, "hoy": 0.0}), HOY)}
    assert t["contribuciones_2027"].startswith("Exento")
