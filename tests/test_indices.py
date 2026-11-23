import numpy as np
import polars as pl

from src.features.indices import indice, semestres


def test_ventas_repetidas_recupera_indice_conocido():
    rng = np.random.default_rng(0)
    per = semestres()
    verdadero = {p: 0.05 * i for i, p in enumerate(per)}  # +5% log por año
    filas = []
    for k in range(3000):
        b = f"15105-B{k % 3:02d}"
        i0, i1 = sorted(rng.choice(len(per), 2, replace=False))
        d = verdadero[per[i1]] - verdadero[per[i0]] + rng.normal(0, 0.05)
        filas.append((f"r{k}", 15105, b, per[i0], per[i1], d))
    pp = pl.DataFrame(filas, schema=["rol_principal", "cod_comuna", "barrio_id", "s0", "s1", "dlogp"], orient="row")
    ic, ib = indice(pp)
    est = dict(zip(ic["semestre"], ic["indice_log"]))
    assert abs(est[per[-1]] - verdadero[per[-1]]) < 0.02
    # Sin diferencias entre barrios, la desviación por barrio queda ~0 (ridge)
    dev = ib.join(ic.select("semestre", pl.col("indice_log").alias("c")), on="semestre")
    assert (dev["indice_log"] - dev["c"]).abs().max() < 0.03
