"""Estimador "¿cuánto pagaré en 2027?" para un rol, a partir de data/marts/reavaluo2027_roles.parquet (Fase 7).

Montos en $ del 2S-2026 (sin el reajuste IPC del 1S-2027). Tres escenarios de nivel del reavalúo:
  S0 leve (mantiene la razón precio/avalúo de 2022), S2 moderado (cierra la mitad de la brecha), S1 fuerte (repite 2022).
Alza gradual del primer semestre (regla de 2022, con la cuota mínima reajustada por IPC):
  si la cuota trimestral nueva > cuota mínima y > 1,25 × la actual, en el 1S-2027 paga max(1,25 × actual, cuota mínima).
  La gradualidad afecta la contribución neta; las sobretasas se pagan completas.
El pago observado incluye el aseo municipal y los beneficios (p. ej. adulto mayor); el estimado no los incluye.
"""

from __future__ import annotations

CUOTA_MIN_2022 = 9_415  # $ por cuota trimestral, 1-1-2022
EXENTO_2022 = 47_360_490
ESCENARIOS = {"S0": "Leve", "S2": "Moderado", "S1": "Fuerte"}


def cuota_minima(exento_h_actual: float) -> float:
    """Cuota mínima del alza gradual llevada a pesos del semestre actual con el mismo IPC del exento."""
    return CUOTA_MIN_2022 * exento_h_actual / EXENTO_2022


def neta_gradual(nueva_sem: float, base_sem: float, cuota_min: float) -> float:
    """Contribución neta semestral del 1S con alza gradual (misma regla que src.features.contribucion.aplicar_gradualidad)."""
    nq, bq = nueva_sem / 2, base_sem / 2
    if nq > cuota_min and nq > 1.25 * bq:
        return 2 * (cuota_min if bq <= 0 else max(1.25 * bq, cuota_min))
    return nueva_sem


def estimar(r27: dict, exento_h_actual: float) -> dict:
    """r27: fila de reavaluo2027_roles (contrib_teo, contrib_neta_teo, avaluo_27_*, contrib_27_*, neta_27_*)."""
    cmin = cuota_minima(exento_h_actual)
    base_sem = float(r27.get("contrib_teo") or 0)
    base_neta = float(r27.get("contrib_neta_teo") or 0)
    out = {"actual_anual_teo": 2 * base_sem, "escenarios": {}}
    for k, nombre in ESCENARIOS.items():
        total = float(r27.get(f"contrib_27_{k}") or 0)
        neta = float(r27.get(f"neta_27_{k}") or 0)
        sobretasas = total - neta
        primer = neta_gradual(neta, base_neta, cmin) + sobretasas
        out["escenarios"][k] = {
            "nombre": nombre,
            "avaluo": float(r27.get(f"avaluo_27_{k}") or 0),
            "anual": 2 * total,
            "cambio_anual": 2 * (total - base_sem),
            "cuota_trimestral_1s": primer / 2,
            "con_alza_gradual": primer < total - 1,
        }
    return out
