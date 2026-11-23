"""Polígonos comunales del Gran Santiago para el mapa.

Fuente: chilemapas (pachadotdev), data_geojson/comunas/r13.geojson (límites comunales con código CUT),
guardado en data/raw/geo/comunas_r13.geojson. Se filtran las 34 comunas del estudio (las comunas SII
Santiago Centro/Oeste/Sur se representan en el polígono único de Santiago, CUT 13101) y las coordenadas
se redondean a 4 decimales (~11 m), lo que basta para una vista comunal.

Salida: web/data/comunas.geojson   (properties: cut, nombre)
Uso: python -m src.presentacion.geometria
"""

from __future__ import annotations

import csv
import json

from src.etl.common import RAW, REF, ROOT

SALIDA = ROOT / "web" / "data" / "comunas.geojson"


def mapa_cut() -> dict[str, str]:
    with open(REF / "comunas_cut.csv", encoding="utf8") as f:
        return {r["cut"]: r["nombre_mapa"] for r in csv.DictReader(f, delimiter=";")}


def _redondear(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 4), round(c[1], 4)]
    out = [_redondear(x) for x in c]
    # quita vértices repetidos consecutivos que deja el redondeo
    if out and isinstance(out[0][0], float):
        dedup = [out[0]] + [p for i, p in enumerate(out[1:], 1) if p != out[i - 1]]
        return dedup if len(dedup) >= 4 else out
    return out


def main() -> None:
    nombres = mapa_cut()
    g = json.loads((RAW / "geo" / "comunas_r13.geojson").read_text(encoding="utf8"))
    feats = []
    for f in g["features"]:
        cut = f["properties"]["codigo_comuna"].lstrip("0")
        if cut in nombres:
            feats.append({
                "type": "Feature",
                "properties": {"cut": cut, "nombre": nombres[cut]},
                "geometry": {"type": f["geometry"]["type"], "coordinates": _redondear(f["geometry"]["coordinates"])},
            })
    faltan = set(nombres) - {f["properties"]["cut"] for f in feats}
    if faltan:
        raise ValueError(f"comunas sin polígono: {faltan}")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf8")
    print(f"[geometria] {len(feats)} comunas → {SALIDA.relative_to(ROOT)} ({SALIDA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
