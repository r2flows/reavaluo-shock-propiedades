"""Geometría APROXIMADA de microbarrios (hasta recibir la cartografía de manzanas del SII).

1. Puntos: direcciones geocodificadas (data/raw/geo/geocode_cache.jsonl). Se descartan los puntos fuera de su comuna
   y los que están a más de 1,5 km de la mediana de su microbarrio.
2. Centro del microbarrio = mediana de sus puntos válidos ("geocodificado"). Si no tiene puntos, se interpola entre
   los microbarrios vecinos por número de manzana dentro de la comuna ("interpolado").
3. Polígono = celda de Voronoi del centro entre los centros de su comuna (en coordenadas escaladas por cos(lat)),
   recortada al límite comunal y a un radio de 2 km del centro.

Salida: web/data/microbarrios.geojson (properties: id, cut, ubicacion, n_puntos)
Uso: scripts/correr.sh --mem 3G src.presentacion.microgeo
"""

from __future__ import annotations

import json
import math
from statistics import median

import polars as pl
from shapely import affinity, voronoi_polygons
from shapely.geometry import MultiPoint, Point, mapping, shape

from src.etl.common import RAW, REF, ROOT, STAGING

SALIDA = ROOT / "web" / "data" / "microbarrios.geojson"
KX = math.cos(math.radians(33.5))  # escala este-oeste a la latitud de Santiago
RADIO_KM, OUTLIER_KM = 2.0, 1.5


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.32 * KX, (a[1] - b[1]) * 110.57)


def main() -> None:
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";", schema={"cod_comuna": pl.Int32, "cut": pl.Utf8, "nombre_mapa": pl.Utf8})
    cod2cut = dict(zip(cuts["cod_comuna"].to_list(), cuts["cut"].to_list()))
    comunas = {f["properties"]["cut"]: shape(f["geometry"]) for f in json.loads((ROOT / "web" / "data" / "comunas.geojson").read_text())["features"]}

    mb = pl.read_parquet(STAGING / "map_barrio.parquet", columns=["cod_comuna", "manzana", "microbarrio_id"])
    orden = mb.group_by("microbarrio_id", "cod_comuna").agg(pl.col("manzana").min().alias("mz_min")).sort("cod_comuna", "mz_min")

    pts: dict[str, list[tuple[float, float]]] = {}
    for linea in (RAW / "geo" / "geocode_cache.jsonl").read_text(encoding="utf8").splitlines():
        r = json.loads(linea)
        if not r.get("ok"):
            continue
        cut = cod2cut[int(r["microbarrio_id"].split("-")[0])]
        p = (r["lon"], r["lat"])
        if comunas[cut].contains(Point(p)):
            pts.setdefault(r["microbarrio_id"], []).append(p)

    centros: dict[str, tuple[tuple[float, float], str, int]] = {}
    for mid, ps in pts.items():
        m = (median(x for x, _ in ps), median(y for _, y in ps))
        buenos = [p for p in ps if km(p, m) <= OUTLIER_KM] or ps
        centros[mid] = ((median(x for x, _ in buenos), median(y for _, y in buenos)), "geocodificado", len(buenos))

    # Interpolación por orden de manzana dentro de la comuna
    for cod, g in orden.group_by("cod_comuna", maintain_order=True):
        ids = g["microbarrio_id"].to_list()
        for i, mid in enumerate(ids):
            if mid in centros:
                continue
            prev = next((centros[ids[j]][0] for j in range(i - 1, -1, -1) if ids[j] in centros), None)
            nxt = next((centros[ids[j]][0] for j in range(i + 1, len(ids)) if ids[j] in centros), None)
            if prev and nxt:
                c = ((prev[0] + nxt[0]) / 2, (prev[1] + nxt[1]) / 2)
            elif prev or nxt:
                c = prev or nxt
            else:
                continue
            centros[mid] = (c, "interpolado", 0)

    feats = []
    por_cut: dict[str, list[str]] = {}
    for mid in centros:
        por_cut.setdefault(cod2cut[int(mid.split("-")[0])], []).append(mid)
    for cut, ids in por_cut.items():
        poly = comunas[cut]
        # Desplaza levemente centros duplicados (dos microbarrios interpolados al mismo punto)
        vistos: dict[tuple[float, float], int] = {}
        semillas = []
        for mid in ids:
            (x, y), _, _ = centros[mid]
            k = (round(x, 6), round(y, 6))
            vistos[k] = vistos.get(k, 0) + 1
            if vistos[k] > 1:
                x += 0.0003 * vistos[k]
                y += 0.0002 * vistos[k]
            semillas.append((mid, Point(x * KX, y)))
        polyk = affinity.scale(poly, xfact=KX, yfact=1, origin=(0, 0))
        celdas = voronoi_polygons(MultiPoint([p for _, p in semillas]), extend_to=polyk.envelope.buffer(0.05))
        for mid, p in semillas:
            celda = next((c for c in celdas.geoms if c.contains(p)), None)
            if celda is None:
                continue
            g = celda.intersection(polyk).intersection(p.buffer(RADIO_KM / 110.57))
            if g.is_empty:
                continue
            g = affinity.scale(g, xfact=1 / KX, yfact=1, origin=(0, 0)).simplify(0.0002, preserve_topology=True)
            _, ubic, n = centros[mid]
            geo = json.loads(json.dumps(mapping(g), default=float))

            def r5(c):
                return [round(c[0], 5), round(c[1], 5)] if isinstance(c[0], (int, float)) else [r5(x) for x in c]

            geo["coordinates"] = r5(geo["coordinates"])
            feats.append({"type": "Feature", "properties": {"id": mid, "cut": cut, "ubicacion": ubic, "n_puntos": n}, "geometry": geo})

    SALIDA.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf8")
    total = orden.height
    geoc = sum(1 for v in centros.values() if v[1] == "geocodificado")
    print(f"[microgeo] {len(feats)}/{total} microbarrios con polígono ({geoc} geocodificados, {len(centros) - geoc} interpolados) → {SALIDA.relative_to(ROOT)} ({SALIDA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
