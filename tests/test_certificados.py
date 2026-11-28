"""Lector de certificados: texto sintético (personas y RUT ficticios), sin datos reales."""

import datetime as dt
import os

import polars as pl
import pytest

from src.titulos import certificados as cert

DOMINIO = """CONSERVADOR DE BIENES RAÍCES DE SANTIAGO
Fojas 12.345 Número 6.789 Año 2018. Santiago, quince de marzo de dos mil dieciocho. DON PEDRO FICTICIO EJEMPLO,
cédula nacional de identidad número 11.111.111-1, es dueño del departamento número 504 del edificio de calle Galileo
4750, comuna de San Joaquín, Rol de avalúo número 4819-25. Lo adquirió por compra a doña ANA PRUEBA MODELO, cédula
de identidad 22.222.222-2, por escritura de fecha 2 de febrero de 2018. El precio fue la suma de 2.300 Unidades de
Fomento. La inscripción anterior rola a fojas 5.678 número 9.012 del Registro de Propiedad del año dos mil tres.
CERTIFICO que la inscripción precedente se encuentra vigente."""

GP = """CERTIFICADO DE HIPOTECAS Y GRAVÁMENES, INTERDICCIONES Y PROHIBICIONES DE ENAJENAR. Revisados los registros por
30 años, la propiedad inscrita a fojas 12.345 número 6.789 del año 2018 registra: Hipoteca a fojas 4.321 número 2.468
del Registro de Hipotecas y Gravámenes del año 2018 a favor de BANCO EJEMPLO. No registra embargos."""


def test_lee_inscripciones_roles_personas_y_montos():
    L = cert.leer_texto("dominio.pdf", DOMINIO)
    assert L.con_texto and L.vigente and L.tipo == "dominio vigente"
    ins = [(i["fojas"], i["numero"], i["anio"], i["anterior"]) for i in L.inscripciones]
    assert ("12.345", "6.789", 2018, False) in ins
    assert ("5.678", "9.012", 2003, True) in ins
    assert L.roles == ["4819-25"]
    assert [r for _, r in L.personas] == ["11.111.111-1", "22.222.222-2"]
    assert "PEDRO FICTICIO EJEMPLO" in L.personas[0][0]
    assert L.montos_uf == [2300.0]


def test_gp_detecta_hipoteca():
    L = cert.leer_texto("gp.pdf", GP)
    assert L.tipo.startswith("hipotecas")
    assert any("Hipoteca" in c for c in L.cargas)
    assert any(i["registro"] == "hipotecas" and i["anio"] == 2018 for i in L.inscripciones)


def test_anio_en_palabras():
    assert cert.anio_de("dos mil tres") == 2003
    assert cert.anio_de("dos mil veintitrés") == 2023
    assert cert.anio_de("mil novecientos noventa y ocho") == 1998


def test_cruce_con_f2890():
    L = cert.leer_texto("dominio.pdf", DOMINIO)
    anio = dt.date.today().year - 2
    transf = pl.DataFrame({"fecha_inscripcion": [dt.date(2018, 4, 1), dt.date(anio, 5, 1)], "monto_uf_norm": [3000.0, 4000.0]})
    al = cert.cruzar([L], "16163-4819-25", transf)
    textos = " ".join(t for _, t in al)
    assert str(anio) in textos  # inscripción reciente sin certificado
    assert "3.000 UF" in textos  # monto distinto (2.300 vs 3.000)
    al2 = cert.cruzar([L], "16163-4819-99", transf)
    assert any(n == "alta" and "no el consultado" in t for n, t in al2)


def test_pdf_sin_texto_y_tamano():
    out = cert.leer_archivos([("x.pdf", b"%PDF-1.4 basura"), ("grande.pdf", b"0" * (cert.MAX_BYTES + 1))])
    assert not out[0].con_texto and not out[1].con_texto


def test_servicio_abierto_cabeceras(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PREINFORME_USUARIO", "prueba")
    monkeypatch.setenv("PREINFORME_CLAVE", "clave-de-prueba-larga-123")
    import importlib

    from src.titulos import app as modapp

    importlib.reload(modapp)
    c = TestClient(modapp.app)
    assert c.get("/salud").text == "ok"
    r = c.get("/")  # abierto desde el 28-11-2026
    assert r.status_code == 200 and "Pre-informe" in r.text
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    r = c.post("/informe", data={"rol": "abc", "comuna": "Santiago"})
    assert r.status_code == 400


def test_rutas_abiertas_con_limite(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PREINFORME_USUARIO", "prueba")
    monkeypatch.setenv("PREINFORME_CLAVE", "clave-de-prueba-larga-123")
    import importlib

    from src.titulos import app as modapp

    importlib.reload(modapp)
    c = TestClient(modapp.app)
    r = c.get("/reclamo")  # abierta: sin clave
    assert r.status_code == 200 and "Revisión de avalúo" in r.text
    for _ in range(modapp.MAX_CONSULTAS - 1):
        c.get("/reclamo")
    assert c.get("/reclamo").status_code == 429
