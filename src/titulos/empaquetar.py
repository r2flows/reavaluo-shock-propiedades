"""Empaqueta los datos por rol que necesita el servicio privado de títulos (solo Gran Santiago y solo columnas usadas).

Los archivos se ordenan por rol, así las consultas por rol leen pocos grupos de filas. Comprimidos con zstd.
Salida: privado/servicio/datos/{staging,marts}/…  (en .gitignore; se sube solo al servicio privado de Railway)
Uso: scripts/correr.sh --mem 5G src.titulos.empaquetar
"""

from __future__ import annotations

import shutil

import polars as pl

from src.etl.common import GRAN_SANTIAGO, MARTS, ROOT, STAGING

DEST = ROOT / "privado" / "servicio" / "datos"
BC = [f"bc{i}_{p}" for i in (1, 2) for p in ("comuna", "manzana", "predio")]
PADRE = ["padre_comuna", "padre_manzana", "padre_predio"]
TABLAS = {
    **{f"staging/catastro/roles_{s}.parquet": (STAGING / "catastro" / f"roles_{s}.parquet", ["rol_id", "cod_comuna", "destino", "avaluo_total", "direccion"], "rol_id")
       for s in ("2021_2", "2022_1")},
    "staging/catastro/roles_2026_2.parquet": (STAGING / "catastro" / "roles_2026_2.parquet", ["rol_id", "cod_comuna", "destino", "avaluo_total", "avaluo_exento", "contrib_semestral", "direccion", "sup_terreno_m2", *PADRE, *BC], "rol_id"),
    "staging/avaluo_componentes_2026_2.parquet": (STAGING / "avaluo_componentes_2026_2.parquet", ["rol_id", "cod_comuna", "sup_construida_total", "anio_construccion_max", "clase_calidad_principal", "copropiedad"], "rol_id"),
    "staging/contribucion_2026_2.parquet": (STAGING / "contribucion_2026_2.parquet", ["rol_id", "cod_comuna", "exencion_especial", "rebaja_obs", "exento_h_semestre"], "rol_id"),
    "marts/reavaluo2027_roles.parquet": (MARTS / "reavaluo2027_roles.parquet", ["rol_id", "cod_comuna", "contrib_teo", "contrib_neta_teo"] + [f"{p}_{e}" for e in ("S0", "S2", "S1") for p in ("avaluo_27", "contrib_27", "neta_27")], "rol_id"),
    # Producto para dueños (src.producto.expediente)
    "marts/auditoria_roles_2026_2.parquet": (MARTS / "auditoria_roles_2026_2.parquet", None, "rol_id"),
    "staging/catastro/lineas_2026_2.parquet": (STAGING / "catastro" / "lineas_2026_2.parquet", ["rol_id", "cod_comuna", "linea", "material", "calidad", "anio_construccion", "sup_construida", "condicion_especial"], "rol_id"),
    "staging/uf.parquet": (STAGING / "uf.parquet", None, None),
    "staging/map_rol_linaje.parquet": (STAGING / "map_rol_linaje.parquet", None, "rol_id"),
    "staging/map_barrio.parquet": (STAGING / "map_barrio.parquet", ["cod_comuna", "manzana", "microbarrio_id", "barrio_id"], "cod_comuna"),
    "staging/f2890.parquet": (STAGING / "f2890.parquet", ["rol_id", "cod_comuna", "fecha_escritura", "fecha_inscripcion", "monto_uf_norm", "flag_inscripcion_antes_escritura"], "rol_id"),
    "staging/fct_transferencia.parquet": (STAGING / "fct_transferencia.parquet", ["rol_id", "cod_comuna", "fecha_escritura", "n_roles_grupo", "primera_venta_obra_nueva"], "rol_id"),
    "marts/fct_venta.parquet": (MARTS / "fct_venta.parquet", ["rol_principal", "cod_comuna", "fecha_escritura", "microbarrio_id", "barrio_id", "anio", "ratio_ia", "uf_m2", "outlier_precio", "primera_venta_obra_nueva",
                                                          "destino_principal", "copropiedad", "sup_construida_total", "monto_uf", "residuo_prop"], "rol_principal"),
}


ESC = ("S0", "S2", "S1")


def compactar_reavaluo(df: pl.DataFrame) -> pl.DataFrame:
    """Reduce el mart 2027 para caber en el límite de subida de Railway (sin perder información):
    - el avalúo 2027 es avalúo 2026-2S × un factor uniforme por comuna y escenario (verificado: error relativo < 1e-15),
      así que se guarda el factor en marts/reavaluo2027_factores.parquet y no el avalúo por rol;
    - se omiten los roles sin contribución hoy ni en ningún escenario (exentos): el lector los completa con 0;
    - las contribuciones se guardan como diferencias (ver abajo).
    El lector es src.titulos.preinforme.leer_r27."""
    av = pl.scan_parquet(STAGING / "catastro" / "roles_2026_2.parquet").select("rol_id", "avaluo_total").collect()
    x = df.join(av, on="rol_id", how="left").filter(pl.col("avaluo_total") > 0)
    fac = x.group_by("cod_comuna").agg([(pl.col(f"avaluo_27_{e}") / pl.col("avaluo_total")).median().alias(f"factor_{e}") for e in ESC])
    out = DEST / "marts" / "reavaluo2027_factores.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    fac.write_parquet(out)
    c = [f"{p}_{e}" for e in ESC for p in ("contrib_27", "neta_27")] + ["contrib_teo", "contrib_neta_teo"]
    df = df.drop([f"avaluo_27_{e}" for e in ESC]).filter(pl.any_horizontal([pl.col(k) > 0 for k in c]))
    # Codificación por diferencias (comprime ~35% mejor): sobretasas = contribución − neta; S0 − hoy; S1 − S2
    return df.select(
        "rol_id", "cod_comuna", "contrib_teo", "contrib_27_S2",
        (pl.col("contrib_27_S0") - pl.col("contrib_teo")).alias("d_27_S0"),
        (pl.col("contrib_27_S1") - pl.col("contrib_27_S2")).alias("d_27_S1"),
        (pl.col("contrib_teo") - pl.col("contrib_neta_teo")).cast(pl.Int32).alias("sob_teo"),
        *[(pl.col(f"contrib_27_{e}") - pl.col(f"neta_27_{e}")).cast(pl.Int32).alias(f"sob_27_{e}") for e in ESC],
    )


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    total = 0
    for rel, (src, cols, orden) in TABLAS.items():
        lf = pl.scan_parquet(src)
        if cols:
            lf = lf.select(cols)
        if orden:
            lf = lf.filter(pl.col("cod_comuna").is_in(GRAN_SANTIAGO))
        df = lf.collect()
        df = df.sort(orden) if orden else df
        # Montos en pesos: enteros (se comprimen mucho mejor que los flotantes)
        df = df.with_columns([pl.col(c).round(0).cast(pl.Int64) for c, t in df.schema.items() if t == pl.Float64 and c.startswith(("avaluo_27", "contrib_27", "neta_27", "contrib_teo", "contrib_neta_teo"))])
        if rel == "marts/reavaluo2027_roles.parquet":
            df = compactar_reavaluo(df)
        if rel == "staging/fct_transferencia.parquet":
            # Solo las transferencias con algo que informar (venta en bloque u obra nueva); el resto da lo mismo que no estar
            df = df.filter((pl.col("n_roles_grupo") > 1) | pl.col("primera_venta_obra_nueva")).unique(["rol_id", "fecha_escritura"], keep="first", maintain_order=True)
        out = DEST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out, compression="zstd", compression_level=15, row_group_size=50_000, statistics=True)
        mb = out.stat().st_size / 1e6
        total += mb
        print(f"[empaquetar] {rel}: {df.height} filas, {mb:.1f} MB")
        del df
    print(f"[empaquetar] total {total:.0f} MB → {DEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
