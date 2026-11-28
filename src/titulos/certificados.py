"""Lector de certificados del Conservador que sube el abogado (servicio privado de títulos).

Regla (CLAUDE.md, cambio del 24-11-2026): el texto de los certificados, con nombres y cédulas, se procesa SOLO EN
MEMORIA dentro de la petición, se muestra en pantalla y se descarta. Este módulo no escribe archivos, no registra
el texto en logs y no guarda nada.

Qué extrae (heurísticas sobre el texto del PDF; el abogado debe verificar):
  - inscripciones citadas: fojas, número y año (marca las «anteriores»)
  - roles de avalúo mencionados
  - personas con cédula (nombre aproximado + RUT), para que el abogado arme la cadena de dueños
  - montos en UF o pesos
  - en certificados de hipotecas y gravámenes: menciones de hipoteca, prohibición, embargo, etc., o constancia de que no hay
Cruces con el F2890 del rol: años de inscripción sin certificado, montos distintos, rol distinto al consultado.
"""

from __future__ import annotations

import html
import io
import re
import datetime as dt
from dataclasses import dataclass, field

import polars as pl

MAX_ARCHIVOS = 8
MAX_BYTES = 12 * 1024 * 1024

UNIDADES = {"cero": 0, "uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
RE_INSC = re.compile(
    r"f(?:ojas|s\.?|js\.?)\s*(?:n[°º]\s*)?([\d\.]{1,7})\s*(?:vta\.?|vuelta)?\s*[,;]?\s*(?:bajo\s+el\s+)?(?:n(?:ú|u)mero|n[°º]|nro\.?)\s*([\d\.]{1,7})\s*[,;]?"
    r"(?:\s*del?\s+registro\s+de\s+(?:propiedad|hipotecas(?:\s+y\s+gravámenes)?|interdicciones(?:\s+y\s+prohibiciones(?:\s+de\s+enajenar)?)?))?"
    r"\s*(?:,\s*)?(?:del?\s+|correspondiente\s+al\s+)?(?:año\s+)?(\d{4}|(?:dos\s+mil|mil\s+novecientos)[a-zé\s]{0,30})",
    re.I)
RE_ROL = re.compile(r"\brol(?:\s+de\s+avalúo(?:\s+fiscal)?)?(?:\s+(?:n[°º]|número|nro)\.?)?\s*:?\s*(\d{1,5})\s*-\s*(\d{1,4})\b", re.I)
RE_RUT = re.compile(r"\b(\d{1,2}\.?\d{3}\.?\d{3}\s*-\s*[\dkK])\b")
RE_UF = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*(?:unidades\s+de\s+fomento|u\.\s?f\.|uf\b)", re.I)
RE_CLP = re.compile(r"\$\s*(\d{1,3}(?:\.\d{3})+)")
# En singular: «Registro de Hipotecas y Gravámenes» o «Interdicciones y Prohibiciones» son nombres de registros, no cargas
CARGAS = [r"\bhipoteca\b", r"\bprohibici[óo]n\b", r"\bembargo\b", r"\binterdicci[óo]n\b", r"\blitigio\b", r"\bservidumbre\b", r"\busufructo\b", r"medida precautoria", r"bien familiar"]
RE_NEG = re.compile(r"(no\s+(registra|existe[n]?|tiene|hay|aparece[n]?|se\s+encuentra[n]?)|sin|ninguna?)\s+[a-záéíóúñ\s]{0,25}$")
MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], 1)}
RE_FECHA_TXT = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES) + r"|setiembre)\s+(?:de|del)\s+(\d{4})\b", re.I)
RE_FECHA_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
RE_CODIGO = re.compile(r"c[óo]digo\s+(?:de\s+)?verificaci[óo]n\s*(?:n[°º]\.?)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-]{5,40})", re.I)


def fechas(texto: str) -> list[dt.date]:
    out = []
    for d, m, a in RE_FECHA_TXT.findall(texto):
        mes = 9 if m.lower() == "setiembre" else MESES[m.lower()]
        try:
            out.append(dt.date(int(a), mes, int(d)))
        except ValueError:
            pass
    for d, m, a in RE_FECHA_NUM.findall(texto):
        try:
            out.append(dt.date(int(a), int(m), int(d)))
        except ValueError:
            pass
    return out


RE_SIN = re.compile(r"no\s+(?:se\s+encuentra|registra|tiene|existe[n]?|aparece[n]?|hay)\s+(?:inscrit[ao]s?\s+)?(?:ninguna?\s+)?(?:hipotecas?|gravámenes|prohibiciones|embargos)", re.I)


def anio_de(s: str) -> int | None:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    base = 2000 if s.startswith("dos mil") else 1900 if s.startswith("mil novecientos") else None
    if base is None:
        return None
    resto = re.sub(r"^(dos mil|mil novecientos)\s*", "", s).replace(" y ", " ").split()
    n = 0
    for w in resto:
        if w in UNIDADES:
            n += UNIDADES[w]
        else:
            break
    return base + n


def num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


@dataclass
class Lectura:
    archivo: str
    tipo: str = "desconocido"
    con_texto: bool = True
    inscripciones: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    personas: list[tuple[str, str]] = field(default_factory=list)
    montos_uf: list[float] = field(default_factory=list)
    montos_clp: list[float] = field(default_factory=list)
    cargas: list[str] = field(default_factory=list)
    sin_cargas: bool = False
    vigente: bool = False
    fecha_emision: "dt.date | None" = None  # la fecha más reciente del texto (≤ hoy): aproxima la emisión
    codigo_verificacion: str | None = None


def texto_pdf(datos: bytes) -> str:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(datos))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def leer_texto(archivo: str, texto: str) -> Lectura:
    L = Lectura(archivo=archivo)
    t = re.sub(r"[ \t]+", " ", texto)
    plano = re.sub(r"\s+", " ", t)
    low = plano.lower()
    if len(plano.strip()) < 80:
        L.con_texto = False
        return L
    if "hipotecas" in low and ("gravámenes" in low or "gravamenes" in low) and "certific" in low:
        L.tipo = "hipotecas, gravámenes y prohibiciones"
    if "vigencia" in low or "vigente" in low:
        L.vigente = True
        L.tipo = "dominio vigente" if L.tipo == "desconocido" else L.tipo + " + vigencia"
    if "estudio de títulos" in low or "estudio de titulos" in low:
        L.tipo = "carpeta de estudio de títulos"
    for m in RE_INSC.finditer(plano):
        a = anio_de(m.group(3))
        if not a or not 1850 <= a <= 2100:
            continue
        previo = low[max(0, m.start() - 90):m.start()]
        L.inscripciones.append({"fojas": m.group(1).strip("."), "numero": m.group(2).strip("."), "anio": a, "anterior": "anterior" in previo,
                                "registro": "hipotecas" if "hipoteca" in m.group(0).lower() else "prohibiciones" if "interdicc" in m.group(0).lower() else "propiedad"})
    L.roles = list(dict.fromkeys(f"{int(a)}-{int(b)}" for a, b in RE_ROL.findall(plano)))
    for m in RE_RUT.finditer(plano):
        antes = plano[max(0, m.start() - 160):m.start()]
        # Quita la etiqueta que precede al RUT («, cédula nacional de identidad número») y toma el tramo anterior
        antes = re.sub(r"(?i)[,\s]*(?:c[ée]dula(?:\s+nacional)?(?:\s+de)?(?:\s+identidad)?|rut|r\.u\.t\.?)?\s*(?:n[°º]\.?|número|nro\.?)?\s*:?\s*$", "", antes)
        antes = re.split(r"[,;:]|\.\s", antes)[-1]
        antes = re.sub(r"(?i)\b(don|doña|señora?|sr\.?|sra\.?)\s+", " ", antes)
        palabras = [w for w in antes.split() if not w.isdigit()]
        # En los certificados los nombres van en mayúsculas; si no hay, se usan las palabras con inicial mayúscula
        mayus = [w for w in palabras if w.isupper() and len(w) > 1 or w in ("Y", "E")]
        nombre = " ".join(mayus or [w for w in palabras if w[:1].isupper()])[-60:].strip(" ,.")
        rut = re.sub(r"\s", "", m.group(1))
        if rut not in [p[1] for p in L.personas]:
            L.personas.append((nombre or "(nombre no detectado)", rut))
    L.montos_uf = [num(x) for x in RE_UF.findall(plano) if 1 <= num(x) <= 1_000_000]
    L.montos_clp = [num(x) for x in RE_CLP.findall(plano) if num(x) >= 100_000]
    for c in CARGAS:
        for m in re.finditer(c, low):
            if RE_NEG.search(low[max(0, m.start() - 45):m.start()]):
                continue
            L.cargas.append(plano[max(0, m.start() - 40):m.end() + 110].strip())
            break
    L.sin_cargas = bool(RE_SIN.search(plano))
    hoy = dt.date.today()
    fs = [f for f in fechas(plano) if f <= hoy]
    L.fecha_emision = max(fs) if fs else None
    m = RE_CODIGO.search(plano)
    L.codigo_verificacion = m.group(1) if m else None
    return L


def leer_archivos(archivos: list[tuple[str, bytes]]) -> list[Lectura]:
    out = []
    for nombre, datos in archivos[:MAX_ARCHIVOS]:
        if len(datos) > MAX_BYTES:
            out.append(Lectura(archivo=nombre, tipo="demasiado grande (máx. 12 MB)", con_texto=False))
            continue
        try:
            txt = texto_pdf(datos) if datos[:5] == b"%PDF-" else datos.decode("utf8", "ignore")
        except Exception:
            out.append(Lectura(archivo=nombre, tipo="no se pudo leer el PDF", con_texto=False))
            continue
        out.append(leer_texto(nombre, txt))
    return out


def cruzar(lecturas: list[Lectura], rol_id: str, transf: pl.DataFrame) -> list[tuple[str, str]]:
    """Alertas (nivel, texto) del cruce certificados ↔ F2890 del rol consultado."""
    al: list[tuple[str, str]] = []
    _, mz, pr = rol_id.split("-")
    rol_corto = f"{int(mz)}-{int(pr)}"
    roles_cert = {r for L in lecturas for r in L.roles}
    if roles_cert and rol_corto not in roles_cert:
        al.append(("alta", f"Los certificados mencionan el/los rol(es) {', '.join(sorted(roles_cert))}, pero no el consultado ({rol_corto}). Puede ser un rol antiguo o matriz: verificar."))
    anios_cert = {i["anio"] for L in lecturas for i in L.inscripciones if i["registro"] == "propiedad"}
    if transf.height:
        anios_f = {d.year for d in transf["fecha_inscripcion"].drop_nulls()}
        import datetime as dt

        hace10 = dt.date.today().year - 10
        faltan = sorted(a for a in anios_f if a >= hace10 and a not in anios_cert)
        if anios_cert and faltan:
            al.append(("media", f"El SII registra inscripciones en {', '.join(map(str, faltan))} que no aparecen citadas en los certificados subidos: pedir esas inscripciones al Conservador."))
        sobran = sorted(a for a in anios_cert if a >= hace10 and a not in anios_f)
        if sobran:
            al.append(("info", f"Los certificados citan inscripciones de {', '.join(map(str, sobran))} sin transferencia en el F2890 de ese año (pueden ser herencias, adjudicaciones o rectificaciones)."))
        montos = [m for L in lecturas for m in L.montos_uf]
        for r in transf.iter_rows(named=True):
            if r.get("monto_uf_norm") and r["fecha_inscripcion"] and r["fecha_inscripcion"].year in anios_cert and montos:
                cerca = min(montos, key=lambda m: abs(m - r["monto_uf_norm"]))
                if abs(cerca - r["monto_uf_norm"]) / r["monto_uf_norm"] > 0.1:
                    al.append(("media", f"Inscripción de {r['fecha_inscripcion'].year}: el F2890 informa {r['monto_uf_norm']:,.0f} UF y el monto en UF más cercano en los certificados es {cerca:,.0f} UF. Revisar el precio de la escritura.".replace(",", ".")))
    if any(L.cargas for L in lecturas):
        al.append(("alta", "Los certificados mencionan cargas o gravámenes (ver detalle): revisar si están vigentes o alzados."))
    if any(not L.con_texto for L in lecturas):
        al.append(("media", "Algún archivo no tiene texto legible (PDF escaneado o dañado): revisarlo a mano."))
    return al


def seccion_html(lecturas: list[Lectura], alertas: list[tuple[str, str]]) -> str:
    e = html.escape
    col = {"alta": "#b42318", "media": "#b54708", "baja": "#475467", "info": "#175cd3"}
    partes = ['<h2>Certificados del Conservador (procesados en memoria; no se guardan)</h2>']
    partes.append("<ul class=al>" + ("".join(f'<li><span class="niv" style="background:{col[n]}">{n}</span> {e(t)}</li>' for n, t in alertas) or "<li>Sin observaciones del cruce.</li>") + "</ul>")
    for L in lecturas:
        partes.append(f"<h3 style='font-size:.95rem;margin:1em 0 .3em'>{e(L.archivo)} · <span style='font-weight:400'>{e(L.tipo)}</span></h3>")
        if not L.con_texto:
            partes.append("<p>Sin texto legible.</p>")
            continue
        if L.inscripciones:
            filas = "".join(f"<tr><td>{e(i['registro'])}{' (anterior)' if i['anterior'] else ''}</td><td class=n>{e(i['fojas'])}</td><td class=n>{e(i['numero'])}</td><td class=n>{i['anio']}</td></tr>" for i in L.inscripciones)
            partes.append(f"<table><thead><tr><th>Inscripción</th><th class=n>Fojas</th><th class=n>Número</th><th class=n>Año</th></tr></thead><tbody>{filas}</tbody></table>")
        det = []
        if L.roles:
            det.append(f"<dt>Roles citados</dt><dd>{e(', '.join(L.roles))}</dd>")
        if L.personas:
            det.append("<dt>Personas</dt><dd>" + "<br>".join(f"{e(n)} · {e(r)}" for n, r in L.personas[:12]) + "</dd>")
        if L.montos_uf or L.montos_clp:
            det.append("<dt>Montos</dt><dd>" + e(", ".join([f"{m:,.2f} UF".replace(",", "X").replace(".", ",").replace("X", ".") for m in L.montos_uf[:6]] + [f"${m:,.0f}".replace(",", ".") for m in L.montos_clp[:6]])) + "</dd>")
        det.append(f"<dt>Cargas</dt><dd>{'<br>'.join('…' + e(c) + '…' for c in L.cargas) if L.cargas else ('Constancia de que no hay' if L.sin_cargas else 'No se detectaron menciones')}</dd>")
        det.append(f"<dt>Vigencia</dt><dd>{'Menciona vigencia' if L.vigente else 'No menciona vigencia'}</dd>")
        partes.append("<dl>" + "".join(det) + "</dl>")
    partes.append("<p style='font-size:.8rem;color:var(--ink2)'>Lectura automática del texto del PDF: los datos extraídos son una ayuda y deben verificarse contra el certificado.</p>")
    return "".join(partes)
