"""Geocodificación de muestra: hasta 3 direcciones por microbarrio (Nominatim / OpenStreetMap).

Se envían solo dirección (calle y número) y comuna de propiedades del catastro público del SII; ningún dato de dueños.
Política de Nominatim: ≤ 1 consulta por segundo, User-Agent propio, caché local (no se repiten consultas).

Selección: por microbarrio se eligen direcciones de viviendas en 3 manzanas repartidas por su rango (mínima,
mediana y máxima), prefiriendo casas (sin "DP") con número.
Salida (retomable): data/raw/geo/geocode_cache.jsonl  — una línea por consulta.
Uso (segundo plano): scripts/correr.sh --mem 2G src.presentacion.geocodificar
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

import polars as pl

from src.etl.common import RAW, REF, STAGING

CACHE = RAW / "geo" / "geocode_cache.jsonl"
URL = "https://nominatim.openstreetmap.org/search"
UA = "atlas-avaluo-santiago/0.1 (investigacion academica; contacto via repositorio publico)"
VIEWBOX = "-70.95,-33.25,-70.30,-33.75"
ABREV = [
    (r"^(PJ|PJE|PSJE|PSJ)\.? ", "PASAJE "),
    (r"^(AV|AVDA)\.? ", "AVENIDA "),
    (r"^V\.? ?MACKENNA", "VICUNA MACKENNA"),
    (r"^STA\.? ", "SANTA "),
    (r"^STO\.? ", "SANTO "),
    (r"^GRAL\.? ", "GENERAL "),
    (r"^PDTE\.? ", "PRESIDENTE "),
    (r"^CAP\.? ", "CAPITAN "),
]


def parsear(direccion: str | None) -> tuple[str, str] | None:
    if not direccion:
        return None
    tokens = direccion.strip().split()
    for i, t in enumerate(tokens):
        if i > 0 and re.fullmatch(r"\d{1,5}", t):
            calle = " ".join(tokens[:i])
            for pat, rep in ABREV:
                calle = re.sub(pat, rep, calle)
            return calle, str(int(t))
    return None


def muestra() -> pl.DataFrame:
    mb = pl.read_parquet(STAGING / "map_barrio.parquet", columns=["cod_comuna", "manzana", "microbarrio_id"])
    r = pl.read_parquet(STAGING / "catastro" / "roles_2026_2.parquet", columns=["cod_comuna", "manzana", "destino", "direccion"]).filter(pl.col("destino") == "H")
    r = r.join(mb, on=["cod_comuna", "manzana"], how="inner").with_columns(pl.col("direccion").str.contains(r"\bDP\b").alias("es_depto"))
    nombres = pl.read_csv(REF / "comunas_cut.csv", separator=";", schema={"cod_comuna": pl.Int32, "cut": pl.Utf8, "nombre_mapa": pl.Utf8})
    r = r.join(nombres.select("cod_comuna", "nombre_mapa"), on="cod_comuna")
    filas = []
    for (mid,), g in r.group_by(["microbarrio_id"]):
        mzs = sorted(g["manzana"].unique().to_list())
        objetivo = [mzs[0], mzs[len(mzs) // 2], mzs[-1]]
        usadas = set()
        for mz in dict.fromkeys(objetivo):
            cand = g.filter(pl.col("manzana") == mz).sort("es_depto")
            for d in cand["direccion"].to_list():
                p = parsear(d)
                if p and p not in usadas:
                    usadas.add(p)
                    filas.append((mid, mz, p[0], p[1], cand["nombre_mapa"][0]))
                    break
    return pl.DataFrame(filas, schema=["microbarrio_id", "manzana", "calle", "numero", "comuna"], orient="row")


def consultar(calle: str, numero: str, comuna: str) -> dict:
    q = {"street": f"{numero} {calle}", "city": comuna, "country": "Chile", "format": "jsonv2", "limit": 1, "viewbox": VIEWBOX, "bounded": 1}
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(q), headers={"User-Agent": UA, "Accept-Language": "es"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf8"))
    if not res:
        return {"ok": False}
    x = res[0]
    return {"ok": True, "lat": float(x["lat"]), "lon": float(x["lon"]), "tipo": x.get("addresstype") or x.get("type"), "rank": x.get("place_rank")}


def main() -> None:
    m = muestra()
    hechos = set()
    if CACHE.exists():
        for linea in CACHE.read_text(encoding="utf8").splitlines():
            hechos.add(json.loads(linea)["clave"])
    pend = [r for r in m.iter_rows(named=True) if f"{r['comuna']}|{r['calle']}|{r['numero']}" not in hechos]
    print(f"[geocodificar] {m.height} direcciones ({m['microbarrio_id'].n_unique()} microbarrios); pendientes {len(pend)}", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf8") as f:
        for i, r in enumerate(pend, 1):
            clave = f"{r['comuna']}|{r['calle']}|{r['numero']}"
            t0 = time.time()
            try:
                res = consultar(r["calle"], r["numero"], r["comuna"])
            except Exception as e:  # red o HTTP: se registra y se sigue; se puede reintentar luego
                res = {"ok": False, "error": str(e)[:120]}
                time.sleep(5)
            f.write(json.dumps({"clave": clave, "microbarrio_id": r["microbarrio_id"], "manzana": r["manzana"]} | res, ensure_ascii=False) + "\n")
            f.flush()
            if i % 200 == 0:
                print(f"[geocodificar] {i}/{len(pend)}", flush=True)
            time.sleep(max(0.0, 1.1 - (time.time() - t0)))
    print("[geocodificar] listo", flush=True)


if __name__ == "__main__":
    main()
