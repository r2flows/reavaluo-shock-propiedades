"""Utilidades compartidas del ETL: rutas, comunas y reporte de filas por paso."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"
MARTS = ROOT / "data" / "marts"
REPORTES = STAGING / "_reportes"
REF = Path(__file__).resolve().parent / "ref"

# Comunas piloto (código SII).
PILOTO = (15105, 15103, 14109)  # Ñuñoa, Providencia, Maipú


def comunas() -> pl.DataFrame:
    """Tabla de comunas: código SII, nombre en el PDF del SII y nombre usado en el F2890."""
    return pl.read_csv(
        REF / "comunas.csv",
        separator=";",
        schema={"cod_comuna": pl.Int32, "nombre_sii": pl.Utf8, "nombre_f2890": pl.Utf8},
    )


@dataclass
class Reporte:
    """Registra filas de entrada, descartes por motivo y filas de salida de un paso."""

    paso: str
    entrada: int = 0
    descartes: Counter = field(default_factory=Counter)
    salida: int = 0
    notas: dict = field(default_factory=dict)

    def descartar(self, motivo: str, n: int = 1) -> None:
        if n:
            self.descartes[motivo] += n

    def cerrar(self, salida: int) -> None:
        self.salida = salida
        total = sum(self.descartes.values())
        if self.entrada and self.entrada != self.salida + total:
            self.notas["advertencia"] = (
                f"entrada ({self.entrada}) != salida ({self.salida}) + descartes ({total})"
            )
        REPORTES.mkdir(parents=True, exist_ok=True)
        (REPORTES / f"{self.paso}.json").write_text(
            json.dumps(
                {
                    "paso": self.paso,
                    "entrada": self.entrada,
                    "descartes": dict(self.descartes),
                    "salida": self.salida,
                    "notas": self.notas,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        print(f"[{self.paso}] entrada={self.entrada:,} salida={self.salida:,}")
        for motivo, n in self.descartes.most_common():
            print(f"  descarte {motivo}: {n:,}")
        for k, v in self.notas.items():
            print(f"  {k}: {v}")
