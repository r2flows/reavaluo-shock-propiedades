"""Arma la página del atlas: inyecta la geometría y los agregados en web/mapa.html → web/build/mapa.html.

Uso: python -m src.presentacion.construir_pagina   (después de geometria y agregados)
"""

from __future__ import annotations

from src.etl.common import ROOT

WEB = ROOT / "web"


def main() -> None:
    plantilla = (WEB / "mapa.html").read_text(encoding="utf8")
    geo = (WEB / "data" / "comunas.geojson").read_text(encoding="utf8")
    datos = (WEB / "data" / "comunas.json").read_text(encoding="utf8")
    for marca in ("/*__GEO__*/null", "/*__DATA__*/null"):
        if plantilla.count(marca) != 1:
            raise ValueError(f"la plantilla debe tener exactamente una marca {marca}")
    html = plantilla.replace("/*__GEO__*/null", geo).replace("/*__DATA__*/null", datos)
    salida = WEB / "build" / "mapa.html"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(html, encoding="utf8")
    # Archivo de apoyo (se publica junto a la página como data/microbarrios.json)
    (salida.parent / "data").mkdir(exist_ok=True)
    for nombre in ("microbarrios.json", "microbarrios.geojson", "calles.json"):
        origen = WEB / "data" / nombre
        if origen.exists():
            (salida.parent / "data" / nombre).write_bytes(origen.read_bytes())
    # Sitio para Railway: index.html + Dockerfile/Caddyfile (web/deploy/)
    (salida.parent / "index.html").write_text(html, encoding="utf8")
    for nombre in ("Dockerfile", "Caddyfile"):
        (salida.parent / nombre).write_bytes((WEB / "deploy" / nombre).read_bytes())
    # Copia de data/ con otro nombre: `railway up` respeta el .gitignore del repo, que excluye "data/"
    (salida.parent / "sitio_datos").mkdir(exist_ok=True)
    for f in (salida.parent / "data").iterdir():
        (salida.parent / "sitio_datos" / f.name).write_bytes(f.read_bytes())
    print(f"[pagina] {salida.relative_to(ROOT)} ({salida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
