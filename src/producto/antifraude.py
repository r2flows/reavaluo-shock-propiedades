"""Controles antifraude sobre los certificados del Conservador que sube el corredor (solo en memoria).

Regla (CLAUDE.md): el RUT del vendedor que ingresa el corredor y los nombres o RUT de los certificados se procesan en
memoria dentro de la petición y se descartan. No se guardan ni se registran. En pantalla, el RUT se muestra enmascarado.

Controles:
  rut_valido           dígito verificador (módulo 11) del RUT del vendedor
  vendedor_es_dueno    el RUT del vendedor aparece en un certificado de dominio vigente subido
  vigencia_30_dias     la fecha más reciente del certificado de dominio y del de gravámenes no tiene más de 30 días
                       (los bancos suelen exigir menos de 30 días); sin fecha legible → revisar a mano
  codigo_verificacion  el certificado trae un código de verificación: hay que validarlo en el sitio del Conservador
                       (un PDF editado conserva el código viejo, pero no pasa la validación)
  certificados_faltan  no se subió el dominio vigente o el de hipotecas y gravámenes
"""

from __future__ import annotations

import datetime as dt
import re

MAX_DIAS = 30


def normalizar_rut(rut: str) -> str | None:
    s = re.sub(r"[^0-9kK]", "", rut or "").upper()
    if len(s) < 2:
        return None
    return f"{int(s[:-1])}-{s[-1]}" if s[:-1].isdigit() else None


def rut_valido(rut: str) -> bool:
    n = normalizar_rut(rut)
    if not n:
        return False
    cuerpo, dv = n.split("-")
    suma, factor = 0, 2
    for c in reversed(cuerpo):
        suma += int(c) * factor
        factor = 2 if factor == 7 else factor + 1
    r = 11 - suma % 11
    return dv == {11: "0", 10: "K"}.get(r, str(r))


def enmascarar(rut: str) -> str:
    n = normalizar_rut(rut) or ""
    cuerpo = n.split("-")[0]
    return (cuerpo[:2] + "." + "*" * 3 + "." + "*" * 3 + "-*") if len(cuerpo) >= 7 else "RUT ingresado"


def controles(lecturas: list, rut_vendedor: str | None, hoy: dt.date | None = None) -> list[tuple[str, str]]:
    """lecturas: src.titulos.certificados.Lectura. Devuelve (nivel, texto) con nivel alta | media | ok | info."""
    hoy = hoy or dt.date.today()
    out: list[tuple[str, str]] = []
    dominio = [L for L in lecturas if "dominio" in L.tipo or L.vigente]
    gp = [L for L in lecturas if "hipotecas" in L.tipo]
    if not dominio:
        out.append(("media", "No se subió la copia de inscripción de dominio con vigencia: no se puede verificar quién es el dueño."))
    if not gp:
        out.append(("media", "No se subió el certificado de hipotecas, gravámenes, interdicciones y prohibiciones."))
    if rut_vendedor:
        if not rut_valido(rut_vendedor):
            out.append(("alta", "El RUT del vendedor ingresado no es válido (dígito verificador incorrecto)."))
        elif dominio:
            r = normalizar_rut(rut_vendedor)
            en_cert = {normalizar_rut(p[1]) for L in dominio for p in L.personas}
            if r in en_cert:
                out.append(("ok", f"El RUT del vendedor ({enmascarar(rut_vendedor)}) aparece en el certificado de dominio. Confirme en el certificado que figure como dueño actual y por el 100%."))
            else:
                out.append(("alta", f"El RUT del vendedor ({enmascarar(rut_vendedor)}) NO aparece en el certificado de dominio subido. Puede no ser el dueño, vender por poder o el certificado puede no corresponder: no avance sin aclararlo."))
    for L in dominio + [g for g in gp if g not in dominio]:
        if not L.con_texto:
            continue
        if L.fecha_emision is None:
            out.append(("media", f"{L.archivo}: no se encontró una fecha legible; verifique a mano que tenga menos de {MAX_DIAS} días."))
        elif (hoy - L.fecha_emision).days > MAX_DIAS:
            out.append(("media", f"{L.archivo}: la fecha más reciente del certificado es {L.fecha_emision:%d-%m-%Y} ({(hoy - L.fecha_emision).days} días). Pida uno nuevo: los bancos suelen exigir menos de {MAX_DIAS} días."))
        if L.codigo_verificacion:
            out.append(("info", f"{L.archivo}: código de verificación {L.codigo_verificacion}. Valídelo en el sitio del Conservador: un PDF alterado no pasa esa validación."))
        else:
            out.append(("media", f"{L.archivo}: no se encontró un código de verificación. Pida el certificado con firma electrónica o valídelo directamente en el Conservador."))
    return out
