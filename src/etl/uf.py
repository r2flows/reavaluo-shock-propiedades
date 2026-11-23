"""UF diaria desde las tablas anuales públicas del SII.

Descarga (una vez) https://www.sii.cl/valores_y_fechas/uf/uf{AAAA}.htm a data/raw/uf/
y genera data/staging/uf.parquet con columnas (fecha: Date, uf: Float64).

Uso: python -m src.etl.uf [AÑO_DESDE] [AÑO_HASTA]
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from datetime import date

import polars as pl

from .common import RAW, STAGING, Reporte

URLS = (
    "https://www.sii.cl/valores_y_fechas/uf/uf{anio}.htm",  # 2013 en adelante
    "https://www.sii.cl/pagina/valores/uf/uf{anio}.htm",  # años anteriores
)
_FILA = re.compile(r"<tr>\s*<th[^>]*>\s*(\d{1,2})\s*</th>(.*?)</tr>", re.S)
_CELDA = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def parse_html(html: str, anio: int) -> list[tuple[date, float]]:
    """Extrae (fecha, uf) de la tabla `table_export` (filas = día, columnas = mes)."""
    i = html.find("table_export")
    if i < 0:
        i = html.find("<table")
    if i < 0:
        raise ValueError(f"tabla de UF no encontrada para {anio}")
    tabla = html[i : html.find("</table>", i)]
    out: list[tuple[date, float]] = []
    for dia, resto in _FILA.findall(tabla):
        for mes, celda in enumerate(_CELDA.findall(resto), start=1):
            txt = re.sub(r"<[^>]+>|&nbsp;", "", celda).strip()
            if not txt:
                continue
            try:
                f = date(anio, mes, int(dia))
            except ValueError:
                continue
            out.append((f, float(txt.replace(".", "").replace(",", "."))))
    return out


def descargar(anio: int) -> str:
    destino = RAW / "uf" / f"uf{anio}.htm"
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        for url in URLS:
            req = urllib.request.Request(url.format(anio=anio), headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    destino.write_bytes(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        else:
            raise FileNotFoundError(f"UF {anio} no disponible en el SII")
    return destino.read_bytes().decode("latin1")


def main(desde: int = 1990, hasta: int = date.today().year) -> pl.DataFrame:
    rep = Reporte("uf")
    filas: list[tuple[date, float]] = []
    for anio in range(desde, hasta + 1):
        filas += parse_html(descargar(anio), anio)
    rep.entrada = len(filas)
    df = pl.DataFrame(filas, schema={"fecha": pl.Date, "uf": pl.Float64}, orient="row")
    df = df.unique("fecha").sort("fecha")
    rep.descartar("fecha_duplicada", rep.entrada - df.height)
    STAGING.mkdir(parents=True, exist_ok=True)
    df.write_parquet(STAGING / "uf.parquet")
    rep.notas["rango"] = f"{df['fecha'].min()} → {df['fecha'].max()}"
    rep.cerrar(df.height)
    return df


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    main(*args)
