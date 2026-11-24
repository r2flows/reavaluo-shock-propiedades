"""Hitos reales de OpenStreetMap para ubicar los microbarrios: barrio, Metro más cercano y plazas o parques.

Descarga (una sola vez, autorizada por el usuario; uso justo de Overpass): dos consultas sobre el bbox del Gran
Santiago, que se guardan inmutables en data/raw/osm/:
  calles_<fecha>.csv   nombres de vías (way[highway][name]), para la ortografía en src.presentacion.nombres
  hitos_<fecha>.json   place=neighbourhood|quarter, leisure=park, place=square, station=subway, railway=station
Datos © colaboradores de OpenStreetMap, licencia ODbL.

Asignación al centro del microbarrio (punto representativo de su polígono aproximado):
  barrio = nodo neighbourhood/quarter más cercano a ≤ 700 m
  metro  = estación de Metro (o tren) más cercana, con distancia
  plazas = hasta 2 parques o plazas con nombre a ≤ 400 m
Salida: data/staging/microbarrio_hitos.parquet
Uso: scripts/correr.sh --mem 2G src.presentacion.hitos_osm [--descargar]
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import urllib.parse
import urllib.request

import polars as pl
from shapely.geometry import shape

from src.etl.common import RAW, ROOT, STAGING

DIR = RAW / "osm"
URL = "https://overpass-api.de/api/interpreter"
UA = "atlas-avaluo-santiago/0.1 (investigacion academica)"
BBOX = "-33.75,-70.95,-33.25,-70.30"
Q_CALLES = f'[out:csv(name;false)][timeout:180];way["highway"]["name"]({BBOX});out tags;'
Q_HITOS = f"""[out:json][timeout:180];
(
  nwr["place"~"^(neighbourhood|quarter)$"]["name"]({BBOX});
  nwr["leisure"="park"]["name"]({BBOX});
  nwr["place"="square"]["name"]({BBOX});
  nwr["station"="subway"]["name"]({BBOX});
  nwr["railway"="station"]["name"]({BBOX});
);
out center tags;"""
KX = math.cos(math.radians(33.5))
SAL = STAGING / "microbarrio_hitos.parquet"


def bajar(q: str, destino) -> None:
    datos = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(URL, data=datos, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        cuerpo = r.read()
    destino.write_bytes(cuerpo)
    print(f"[hitos_osm] descargado {destino.relative_to(ROOT)} ({len(cuerpo) / 1024:.0f} KB)", flush=True)


def m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111_320 * KX, (a[1] - b[1]) * 110_570)


def ultimo(patron: str):
    xs = sorted(DIR.glob(patron))
    return xs[-1] if xs else None


def main() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    if "--descargar" in sys.argv:
        hoy = dt.date.today().isoformat()
        for q, nombre in ((Q_CALLES, f"calles_{hoy}.csv"), (Q_HITOS, f"hitos_{hoy}.json")):
            if not (DIR / nombre).exists():  # data/raw es inmutable: nunca se sobrescribe
                bajar(q, DIR / nombre)
    fh = ultimo("hitos_*.json")
    if fh is None:
        sys.exit("[hitos_osm] falta data/raw/osm/hitos_*.json; correr con --descargar")
    els = json.loads(fh.read_text(encoding="utf8"))["elements"]
    barrios, metros, plazas = [], [], []
    for e in els:
        t = e.get("tags", {})
        p = (e["lon"], e["lat"]) if "lon" in e else ((e["center"]["lon"], e["center"]["lat"]) if "center" in e else None)
        if p is None or not t.get("name"):
            continue
        if t.get("place") in ("neighbourhood", "quarter"):
            barrios.append((t["name"], p))
        elif t.get("station") == "subway" or t.get("railway") == "station":
            es_metro = t.get("station") == "subway" or "metro" in (t.get("network", "") + t.get("operator", "")).lower()
            metros.append((t["name"], p, "Metro" if es_metro else "Tren"))
        elif t.get("leisure") == "park" or t.get("place") == "square":
            plazas.append((t["name"], p))
    # Una estación aparece como varios elementos (andenes, nodos): se deduplican por nombre y cercanía
    uniq = []
    for n, p, tipo in metros:
        if not any(n == u[0] and m(p, u[1]) < 400 for u in uniq):
            uniq.append((n, p, tipo))
    metros = uniq
    feats = json.loads((ROOT / "web" / "data" / "microbarrios.geojson").read_text())["features"]
    filas = []
    for f in feats:
        c = shape(f["geometry"]).representative_point()
        c = (c.x, c.y)
        b = min(((m(c, p), n) for n, p in barrios), default=(1e9, None))
        mt = min(((m(c, p), n, tipo) for n, p, tipo in metros), default=(1e9, None, None))
        cerca = sorted((m(c, p), n) for n, p in plazas if m(c, p) <= 400)
        nombres_pl = list(dict.fromkeys(n for _, n in cerca))[:2]
        filas.append({
            "microbarrio_id": f["properties"]["id"],
            "barrio": b[1] if b[0] <= 700 else None,
            "metro": (f"{mt[2]} {mt[1]}" if mt[2] == "Tren" or not mt[1].lower().startswith("metro") else mt[1]) if mt[1] else None,
            "metro_m": round(mt[0], -1) if mt[1] else None,
            "plazas": " · ".join(nombres_pl) or None,
        })
    d = pl.DataFrame(filas)
    d.write_parquet(SAL)
    print(f"[hitos_osm] OSM: {len(barrios)} barrios, {len(metros)} estaciones, {len(plazas)} parques/plazas (de {fh.name})")
    print(f"[hitos_osm] {d.height} microbarrios: {d['barrio'].is_not_null().sum()} con barrio, {(d['metro_m'] <= 1000).sum()} con estación a ≤ 1 km, {d['plazas'].is_not_null().sum()} con plaza/parque a ≤ 400 m → {SAL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
