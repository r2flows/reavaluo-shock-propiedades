"""Arma la carpeta de despliegue del servicio privado de títulos (Railway): código mínimo + datos empaquetados.

Salida: privado/servicio/build/ (en .gitignore). Requiere haber corrido src.titulos.empaquetar.
Despliegue: cd privado/servicio/build && railway up --ci --service preinforme-titulos
"""

from __future__ import annotations

import shutil

from src.etl.common import REF, ROOT

DIR = ROOT / "privado" / "servicio"
BUILD = DIR / "build"
REQ = """polars==2.1.0
fastapi==0.115.6
uvicorn==0.32.1
python-multipart==0.0.20
pypdf==5.1.0
"""
DOCKERFILE = """FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PREINFORME_DATOS=/app/datos
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY datos/ datos/
USER nobody
CMD ["python", "-m", "src.titulos.app"]
"""


def main() -> None:
    datos = DIR / "datos"
    if not datos.exists():
        raise SystemExit("Faltan los datos: correr src.titulos.empaquetar")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "src" / "etl" / "ref").mkdir(parents=True)
    (BUILD / "src" / "titulos").mkdir()
    for f in ("src/__init__.py", "src/etl/__init__.py", "src/etl/common.py"):
        src = ROOT / f
        (BUILD / f).write_bytes(src.read_bytes() if src.exists() else b"")
    for f in ("comunas_cut.csv", "cbr_por_comuna.csv", "comunas.csv"):
        shutil.copy(REF / f, BUILD / "src" / "etl" / "ref" / f)
    for f in ("__init__.py", "app.py", "preinforme.py", "certificados.py"):
        shutil.copy(ROOT / "src" / "titulos" / f, BUILD / "src" / "titulos" / f)
    shutil.copytree(datos, BUILD / "datos")
    (BUILD / "requirements.txt").write_text(REQ)
    (BUILD / "Dockerfile").write_text(DOCKERFILE)
    tam = sum(p.stat().st_size for p in BUILD.rglob("*") if p.is_file()) / 1e6
    print(f"[servicio] {BUILD.relative_to(ROOT)} listo ({tam:.0f} MB)")


if __name__ == "__main__":
    main()
