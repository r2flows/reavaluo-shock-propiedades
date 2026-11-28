"""Tests del producto para dueños: auditor de avalúo, comparables, estimador 2027 y expediente (fixtures sintéticos)."""

from datetime import date

import polars as pl
import pytest

from src.etl.common import MARTS
from src.features.contribucion import aplicar_gradualidad
from src.producto import auditoria_rol as au
from src.producto import comparables as cp
from src.producto import estimador2027 as est
from src.producto import expediente as ex

P26 = {"exento_h": 61_711_570.0, "cambio_tasa": 220_398_435.0, "t1": 0.00893, "t2": 0.01042, "t_no_h": 0.01042, "sobretasa": 0.00025}
VUC = pl.DataFrame({"clase": ["B", "B", "B"], "calidad": ["2", "3", "4"], "vuc": [800_000.0, 600_000.0, 450_000.0]})


def _comp(filas: list[dict]) -> pl.DataFrame:
    base = {"rol_id": "", "cod_comuna": 15105, "manzana": 1, "destino": "H", "avaluo_total": 0, "sup_terreno_m2": 0,
            "copropiedad": False, "avaluo_construccion_teo": 0.0, "terreno_m2_teo": None, "sup_construida_total": 0,
            "clase_calidad_principal": "C3", "anio_construccion_max": 1990, "linea_sin_vuc": False, "bc1_manzana": None, "bc1_predio": None}
    return pl.DataFrame([base | f for f in filas], schema_overrides={"terreno_m2_teo": pl.Float64, "bc1_manzana": pl.Int32, "bc1_predio": pl.Int32})


def _casa(i: int, t_m2: float, manzana: int = 1, sup: int = 200, constr: float = 30e6) -> dict:
    return {"rol_id": f"15105-{manzana}-{i}", "manzana": manzana, "sup_terreno_m2": sup, "avaluo_construccion_teo": constr,
            "terreno_m2_teo": t_m2, "avaluo_total": int(constr + t_m2 * sup), "sup_construida_total": 100}


def _depto(i: int, am2: float, m2: int = 60, cc: str = "B3", anio: int = 2010) -> dict:
    return {"rol_id": f"15105-2-{i}", "manzana": 2, "copropiedad": True, "bc1_manzana": 2, "bc1_predio": 900, "sup_construida_total": m2,
            "avaluo_total": int(am2 * m2), "avaluo_construccion_teo": 0.4 * am2 * m2, "clase_calidad_principal": cc, "anio_construccion_max": anio}


@pytest.fixture
def manzana_casas() -> pl.DataFrame:
    filas = [_casa(i, 100_000 * (1 + 0.002 * (i % 3))) for i in range(12)]   # área homogénea principal
    filas += [_casa(20 + i, 150_000) for i in range(3)]                         # otra calle: 3 casas iguales → no se marca
    filas += [_casa(30, 130_000), _casa(31, 112_000), _casa(32, 104_000)]       # aislada fuerte, aislada revisar, normal
    filas += [_casa(40 + i, 400_000, manzana=9) for i in range(3)]              # manzana con < 5 casas → no se audita
    filas += [{"rol_id": "15105-1-50", "destino": "C", "avaluo_total": 1}, {"rol_id": "15105-1-51", "avaluo_total": 0}]
    return _comp(filas)


@pytest.fixture
def edificio() -> pl.DataFrame:
    filas = [_depto(i, 1_000_000) for i in range(14)]
    filas += [_depto(20, 1_060_000), _depto(21, 1_030_000)]                      # fuerte (6%) y revisar (3%)
    filas += [_depto(30 + i, 1_200_000) for i in range(3)]                       # 3 unidades iguales más caras (p. ej. pisos altos)
    filas += [_depto(40, 1_330_000, cc="B2")]                                    # calidad mejor que la moda (3) del edificio
    filas += [_depto(50 + i, 900_000, cc="B4", anio=1980) for i in range(4)]     # grupo de solo 4 → no se audita
    return _comp(filas)


def test_terreno_marca_solo_valores_aislados(manzana_casas):
    s = au.senal_terreno(au.base_habitacional(manzana_casas))
    niveles = dict(zip(s["rol_id"], s["nivel"]))
    assert niveles == {"15105-1-30": "fuerte", "15105-1-31": "revisar"}
    fila = s.filter(pl.col("rol_id") == "15105-1-30").row(0, named=True)
    assert fila["exceso_avaluo"] == pytest.approx((130_000 - fila["valor_pares"]) * 200)


def test_edificio_niveles_y_aislamiento(edificio):
    s = au.senal_edificio(au.base_habitacional(edificio))
    assert dict(zip(s["rol_id"], s["nivel"])) == {"15105-2-20": "fuerte", "15105-2-21": "revisar"}
    assert s.filter(pl.col("rol_id") == "15105-2-20")["desvio"][0] == pytest.approx(0.06)


def test_calidad_mejor_que_el_edificio(edificio):
    s = au.senal_calidad(au.base_habitacional(edificio), VUC)
    assert s["rol_id"].to_list() == ["15105-2-40"]
    r = s.row(0, named=True)
    assert (r["valor_rol"], r["valor_pares"]) == (2.0, 3.0)
    assert r["exceso_avaluo"] == pytest.approx(0.4 * 1_330_000 * 60 * (1 - 600_000 / 800_000))


def test_superficie_y_esquema(edificio):
    previo = edificio.select("rol_id", pl.when(pl.col("rol_id") == "15105-2-0").then(40).otherwise(pl.col("sup_construida_total")).alias("sup_construida_total"))
    s = au.senales(edificio, VUC, previo)
    assert s.schema == pl.Schema(au._ESQUEMA)
    sup = s.filter(pl.col("senal") == "superficie_aumento")
    assert sup["rol_id"].to_list() == ["15105-2-0"] and sup["desvio"][0] == pytest.approx(0.5)


def test_ahorro_anual_afecto_y_exento():
    sen = pl.DataFrame({"rol_id": ["a", "b"], "exceso_avaluo": [20e6, 5e6]})
    roles = pl.DataFrame({"rol_id": ["b", "a"], "destino": ["H", "H"], "avaluo_total": [40_000_000, 150_000_000], "avaluo_exento": [40_000_000, 61_711_570]})
    out = au.ahorro_anual(sen, roles, P26)
    assert out["rol_id"].to_list() == ["a", "b"]  # se mantiene el orden de las señales
    assert out["ahorro_anual"][0] == pytest.approx(20e6 * 0.00893, abs=1)  # todo en el tramo 1
    assert out["ahorro_anual"][1] == 0  # ya exento


def test_backtest_precision():
    sen = pl.DataFrame({"rol_id": ["a", "b", "c"], "senal": ["x", "x", "x"], "nivel": ["fuerte"] * 3})
    univ = pl.DataFrame({"rol_id": list("abcdefghij"), "sin_cambio": [True] * 9 + [False], "bajo": [True, False, False, True] + [False] * 6})
    r = au.resultado_backtest(sen, univ)
    assert r["universo_sin_cambio_fisico"] == 9 and r["tasa_base_baja"] == pytest.approx(2 / 9, abs=1e-4)
    assert r["por_senal"]["x:fuerte"]["bajados"] == 1


# --- comparables -------------------------------------------------------------------------------------------------

@pytest.fixture
def ventas() -> pl.DataFrame:
    f = []
    for i in range(30):  # microbarrio M1: 30 ventas válidas de deptos de 55–65 m²
        f.append(("r%d" % i, date(2025, 1 + i % 12, 1), "M1", 55 + i % 11, 3000.0 + 10 * i, 0.0))
    f += [("obj", date(2025, 5, 1), "M1", 60, 3000.0, 0.0)]                 # venta del propio rol
    f += [("fm%d" % i, date(2025, 6, 1), "M1", 60, 900.0, -1.2) for i in range(4)]   # fuera de mercado
    f += [("gr%d" % i, date(2025, 6, 1), "M1", 120, 6000.0, 0.0) for i in range(5)]  # superficie distinta
    f += [("vj%d" % i, date(2019, 6, 1), "M1", 60, 2500.0, 0.0) for i in range(5)]   # antiguas
    f += [("b%d" % i, date(2025, 3, 1), "M2", 60, 3200.0, 0.0) for i in range(6)]    # otro microbarrio del barrio
    df = pl.DataFrame(f, schema=["rol_principal", "fecha_escritura", "microbarrio_id", "sup_construida_total", "monto_uf", "residuo_prop"], orient="row")
    return df.with_columns(
        pl.col("fecha_escritura").dt.year().alias("anio"), pl.lit("B1").alias("barrio_id"), pl.lit("H").alias("destino_principal"),
        pl.lit(True).alias("copropiedad"), (pl.col("monto_uf") / pl.col("sup_construida_total")).alias("uf_m2"),
        pl.lit(2.0).alias("ratio_ia"), pl.lit(False).alias("outlier_precio"), pl.lit(False).alias("primera_venta_obra_nueva"),
    )


def test_comparables_descartes(ventas):
    obj = {"rol_id": "obj", "microbarrio_id": "M1", "barrio_id": "B1", "copropiedad": True, "sup_construida_total": 60}
    c, n = cp.seleccionar(ventas, obj, n=10, hoy=date(2026, 11, 1))
    assert c.height == 10 and n["ambito"] == "microbarrio"
    assert (n["venta_del_mismo_rol"], n["fuera_de_mercado"], n["superficie_distinta"]) == (1, 4, 5)
    assert set(c["microbarrio_id"]) == {"M1"} and "obj" not in c["rol_principal"].to_list()
    assert c["sup_construida_total"].is_between(55, 65).all()


def test_comparables_amplia_al_barrio(ventas):
    obj = {"rol_id": "obj", "microbarrio_id": "M9", "barrio_id": "B1", "copropiedad": True, "sup_construida_total": 60}
    c, n = cp.seleccionar(ventas, obj, n=50, hoy=date(2026, 11, 1))
    assert n["ambito"] == "barrio" and c.height == 36


def test_resumen_avaluo_sobre_precio(ventas):
    r = cp.resumen(ventas.head(10), avaluo_uf=1500.0, sup=60)
    assert r["avaluo_sobre_precio"] == pytest.approx(1500 / (r["uf_m2_mediana"] * 60))


# --- estimador 2027 ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("nueva,base", [(100_000.0, 0.0), (100_000.0, 60_000.0), (100_000.0, 90_000.0), (10_000.0, 0.0), (2e6, 1e6)])
def test_gradualidad_igual_a_la_del_pipeline(nueva, base):
    pol = pl.DataFrame({"n": [nueva], "b": [base]}).select(aplicar_gradualidad(pl.col("n"), pl.col("b")))[0, 0]
    assert est.neta_gradual(nueva, base, est.CUOTA_MIN_2022) == pytest.approx(pol)


def test_estimar_escenarios():
    r27 = {"contrib_teo": 100_000.0, "contrib_neta_teo": 95_000.0}
    for k, f in (("S0", 1.0), ("S2", 1.5), ("S1", 2.0)):
        r27 |= {f"avaluo_27_{k}": 1e8 * f, f"contrib_27_{k}": 100_000.0 * f, f"neta_27_{k}": 95_000.0 * f}
    x = est.estimar(r27, est.EXENTO_2022)
    assert x["actual_anual_teo"] == 200_000
    s1 = x["escenarios"]["S1"]
    assert s1["con_alza_gradual"] and s1["cuota_trimestral_1s"] == pytest.approx((1.25 * 95_000 + 10_000) / 2)
    assert not x["escenarios"]["S0"]["con_alza_gradual"] and x["escenarios"]["S0"]["cambio_anual"] == 0


# --- expediente --------------------------------------------------------------------------------------------------

def test_equidad_quintiles():
    v = pl.DataFrame({"monto_uf": [float(1000 + 10 * i) for i in range(200)], "ratio_ia": [1.25] * 40 + [2.0] * 160})
    q = ex.equidad(v)
    assert q["q"].to_list() == [1, 2, 3, 4, 5] and q["n"].to_list() == [40] * 5
    assert q["a_p"][0] == pytest.approx(0.8) and q["a_p"][-1] == pytest.approx(0.5)
    assert ex.equidad(v.head(50)).height == 0


@pytest.mark.skipif(not (MARTS / "auditoria_roles_2026_2.parquet").exists(), reason="datos no generados")
def test_expediente_real_sin_datos_personales():
    a = pl.scan_parquet(MARTS / "auditoria_roles_2026_2.parquet").filter(pl.col("nivel") == "fuerte").head(1).collect()
    d = ex.leer([a["rol_id"][0]])
    h = ex.informe(d)
    assert "indicio fuerte" in h and "Cuánto pagará en 2027" in h and "no constituye asesoría legal" in h
    assert "RUT" not in h.upper().replace("RUTA", "")


# --- terreno: búsqueda por dirección ------------------------------------------------------------------------------

from src.producto import terreno as ter  # noqa: E402


@pytest.fixture
def direcciones() -> pl.DataFrame:
    d = ["LOS HEROES PC 39", "LOS HEROES ST 23", "LOTE 1 -A PC 50 -B LOS HEROES", "CAM INT SARA EL CARMEN", "AVDA. IRARRAZAVAL 1989 BD 366",
         "IRARRAZAVAL 366 376", "AV IRARRAZAVAL 3785 BD 366", "PJE EL PUEBLO 5875", "LS CATURRAS 01155", "STA ESTER ST 3",
         "HJ 5 CAM EL BOSQUE LT 2", "PARCELA SANTA MARTA HIJUELA 4", "J MANUEL INFANTE 2270 A BD 26", "M PEREIRA 3350 DP 302", None]
    return pl.DataFrame({"rol_id": [f"1-1-{i}" for i in range(len(d))], "direccion": d})


@pytest.mark.parametrize("q,esperado", [
    ("Los Héroes parcela 39", ["LOS HEROES PC 39"]),
    ("los heroes 50", ["LOTE 1 -A PC 50 -B LOS HEROES"]),
    ("camino sara el carmen", ["CAM INT SARA EL CARMEN"]),
    ("pasaje el pueblo 5875", ["PJE EL PUEBLO 5875"]),
    ("caturras 1155", ["LS CATURRAS 01155"]),                  # ceros a la izquierda
    ("santa ester sitio 3", ["STA ESTER ST 3"]),
    ("hijuela 5 camino el bosque lote 2", ["HJ 5 CAM EL BOSQUE LT 2"]),
    ("Manuel Infante 2270", ["J MANUEL INFANTE 2270 A BD 26"]),
    ("pereira 335", []),                                        # el número debe calzar entero
])
def test_busqueda_por_direccion(direcciones, q, esperado):
    assert ter.buscar_en(direcciones, q)["direccion"].to_list() == esperado


def test_busqueda_ordena_la_direccion_exacta_primero(direcciones):
    r = ter.buscar_en(direcciones, "avenida irarrazaval 366")["direccion"].to_list()
    assert len(r) == 2 and "IRARRAZAVAL 366 376" not in r  # "AV" exigido: la dirección sin avenida no calza
    r = ter.buscar_en(direcciones, "irarrazaval 366")["direccion"].to_list()
    assert r[0] == "IRARRAZAVAL 366 376" and len(r) == 3


def test_consulta_vacia_no_devuelve_todo(direcciones):
    assert ter.buscar_en(direcciones, "calle de la").height == 0


def test_tablas_de_ubicacion_y_textos():
    assert ter.ubicacion("R")[0] == "Rural (código R)" and "Informaciones Previas" in ter.ubicacion("U")[1]
    assert ter.ubicacion("E")[0].startswith("Probable extensión urbana")
    assert ter.ubicacion(None)[0].startswith("Sin dato")
