"""Carpeta de la propiedad (corredores): antifraude en memoria y trámites por organismo."""

import datetime as dt

import pytest

from src.producto import antifraude as af
from src.producto import carpeta as ca
from src.producto import diligencia as dg
from src.titulos import certificados as cert

HOY = dt.date(2026, 11, 28)
DOMINIO = ("CERTIFICADO DE DOMINIO VIGENTE. El Conservador certifica que la inscripción de fojas 1234 número 567 del Registro de "
           "Propiedad del año 2019 se encuentra vigente a nombre de JUAN PEREZ SOTO, cédula nacional de identidad número 12.345.678-5, "
           "rol de avalúo 1045-159. Santiago, {fecha}. Código de verificación: ABC123XYZ9")
GP = ("CERTIFICADO DE HIPOTECAS Y GRAVÁMENES, INTERDICCIONES Y PROHIBICIONES. Revisados los registros por 30 años, no se encuentra inscrita "
      "ninguna hipoteca ni gravamen sobre el inmueble. Santiago, 25/11/2026.")


@pytest.mark.parametrize("rut,ok", [("12.345.678-5", True), ("12345678-5", True), ("12.345.678-4", False), ("7.654.321-6", True), ("1.000.005-k", True), ("abc", False), ("", False)])
def test_rut_valido(rut, ok):
    assert af.rut_valido(rut) is ok


def test_enmascarar_no_muestra_el_rut():
    m = af.enmascarar("12.345.678-5")
    assert "345" not in m and "678" not in m and m.startswith("12.")


def test_fecha_y_codigo_del_certificado():
    L = cert.leer_texto("d.pdf", DOMINIO.format(fecha="20 de noviembre de 2026"))
    assert L.fecha_emision == dt.date(2026, 11, 20) and L.codigo_verificacion == "ABC123XYZ9"
    assert cert.leer_texto("g.pdf", GP).fecha_emision == dt.date(2026, 11, 25)


def test_vendedor_es_dueno_y_vigente():
    ls = [cert.leer_texto("d.pdf", DOMINIO.format(fecha="20 de noviembre de 2026")), cert.leer_texto("g.pdf", GP)]
    c = af.controles(ls, "12.345.678-5", HOY)
    niveles = [n for n, _ in c]
    assert "ok" in niveles and "alta" not in niveles
    assert not any("días" in t for _, t in c)  # vigentes (< 30 días)


def test_vendedor_no_es_dueno():
    ls = [cert.leer_texto("d.pdf", DOMINIO.format(fecha="20 de noviembre de 2026"))]
    c = af.controles(ls, "7.654.321-6", HOY)
    assert any(n == "alta" and "NO aparece" in t for n, t in c)
    assert any("hipotecas" in t for n, t in c)  # falta el GP


def test_certificado_vencido_y_sin_codigo():
    ls = [cert.leer_texto("d.pdf", DOMINIO.format(fecha="3 de agosto de 2026").replace("Código de verificación: ABC123XYZ9", ""))]
    c = af.controles(ls, None, HOY)
    assert any("117 días" in t for _, t in c) and any("no se encontró un código" in t for _, t in c)


def test_sin_certificados_pide_ambos():
    c = af.controles([], "12.345.678-5", HOY)
    assert sum("No se subió" in t for _, t in c) == 2


def test_tramites_segun_alertas():
    base = {t[0] for t in ca.tramites([], copropiedad=False)}
    assert base == {"dominio", "gp", "tgr", "sii", "cip", "numero", "expro"}
    al = [dg.Alerta("herencia_probable", "dominio", "revisar", ""), dg.Alerta("suelo_riego", "agua", "revisar", "")]
    ids = {t[0] for t in ca.tramites(al, copropiedad=True)}
    assert {"pe", "ieh", "agua", "dga", "gc"} <= ids and "sag" not in ids
