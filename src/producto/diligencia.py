"""Debida diligencia de un terreno: lo que el vendedor podría omitir, con datos públicos por rol.

Semáforo por categoría + lista de documentos que exigir al vendedor. Cada alerta dice su fuente y lo que no prueba:
estos son INDICIOS a partir del catastro del SII y del F2890 (enajenaciones informadas por notarios y conservadores),
no un estudio de títulos. Ver la matriz de cobertura y el protocolo de evaluación en docs/diligencia_terrenos.md.

Reglas (etapa 1, solo datos que ya tenemos):
  herencia_probable      la última transferencia (desde 2015, no en bloque) se informó sin monto: herencia, donación,
                         aporte o un registro sin monto. Señal débil: antes de 2010 casi ningún registro trae monto,
                         y aún en 2020–2024 el 6–19% de las ventas individuales viene sin monto. Nivel "revisar".
  transferencias_sin_monto  otras transferencias sin monto desde 2015 (no en bloque)
  cuotas_mismo_dia       2 o más enajenaciones del mismo rol el mismo día (típico de cuotas de una comunidad)
  precio_bajo_avaluo     una venta desde 2022 con precio < 50% del avalúo fiscal en UF (cuota, relacionados, subvaluación)
  rotacion_alta          3 o más transferencias en los últimos 5 años
  subdivision_rural      ubicación R o E, serie no agrícola, terreno entre 1 y 4.999 m² (mínimo DL 3.516: 0,5 ha)
  rol_nuevo              el rol tiene rol padre o apareció después de 2021-2S (subdivisión, loteo o copropiedad)
  extension_urbana       código de ubicación E (sin definición publicada; probable área de extensión urbana)
  suelo_riego            el predio agrícola tiene hectáreas de riego (1R–4R): su valor depende de los derechos de agua
  superficie_aumento     la superficie construida subió ≥ 10% desde 2022 (auditor de avalúo)
  contribuciones_2027    rango de contribución anual 2027 (estimador), si hay estimación
Siempre se listan como "no cubierto con datos públicos": hipotecas y gravámenes, deuda de contribuciones, litigios,
zonificación, afectaciones de utilidad pública, riesgos naturales y ocupación.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field

import polars as pl

from src.titulos import preinforme as pi

CATEGORIAS = [
    ("dominio", "Dominio, herencias y cuotas"),
    ("gravamenes", "Hipotecas, gravámenes, deudas y litigios"),
    ("urbanismo", "Urbanismo, subdivisión y expropiación"),
    ("agua", "Agua"),
    ("construcciones", "Construcciones"),
    ("costos", "Contribuciones"),
    ("riesgos", "Riesgos naturales y ocupación"),
]
NIVELES = {"alerta": 0, "revisar": 1, "info": 2}
DESDE_MONTO = dt.date(2015, 1, 1)  # antes, la mayoría de los registros del F2890 no trae monto
SIN_COBERTURA = {  # categorías que hoy no se pueden verificar con datos públicos por rol
    "gravamenes": "No verificado: requiere el certificado de hipotecas, gravámenes, interdicciones y prohibiciones del Conservador y el certificado de deuda de la Tesorería.",
    "riesgos": "No verificado: inundación, remoción en masa, fallas geológicas, incendios y ocupaciones no se cruzan todavía con el predio.",
    "urbanismo": "La zonificación, el uso de suelo permitido y las afectaciones de utilidad pública no se cruzan todavía: los da el Certificado de Informaciones Previas.",
}
DOCS_BASE = [
    "Copia de inscripción de dominio con vigencia (Conservador de Bienes Raíces)",
    "Certificado de hipotecas, gravámenes, interdicciones y prohibiciones de 30 años (Conservador)",
    "Certificado de deuda de contribuciones (Tesorería, tgr.cl)",
    "Certificado de Informaciones Previas (Dirección de Obras de la municipalidad)",
    "Certificados de no expropiación municipal y del SERVIU",
]


@dataclass
class Alerta:
    regla: str
    categoria: str
    nivel: str  # alerta | revisar | info
    texto: str
    documentos: list[str] = field(default_factory=list)


def _clp(x: float) -> str:
    return pi.clp(x)


def _ent(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _ha(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def evaluar(d: dict, hoy: dt.date | None = None) -> list[Alerta]:
    """d: ficha (src.producto.terreno.ficha) + 'transf' (F2890 del rol), 'uf_avaluo', 'sup_aumento' (dict|None),
    'r27' (dict|None), 'linaje_alta' (bool). Función pura: no lee archivos."""
    hoy = hoy or dt.date.today()
    r = d["rol"]
    out: list[Alerta] = []
    t = d.get("transf")
    if t is not None and t.height:
        t = t.filter(pl.col("fecha_escritura") <= hoy).sort("fecha_escritura")
    if t is not None and t.height:
        en_bloque = set(d.get("fechas_en_bloque") or ())
        sin_monto = (pl.col("monto_uf_norm").fill_null(0) <= 0) & (pl.col("fecha_escritura") >= DESDE_MONTO) & ~pl.col("fecha_escritura").is_in(list(en_bloque))
        ult = t.row(-1, named=True)
        hace10, hace5 = hoy.replace(year=hoy.year - 10), hoy.replace(year=hoy.year - 5)
        ult_sin = t.tail(1).filter(sin_monto).height == 1
        if ult_sin:
            out.append(Alerta("herencia_probable", "dominio", "revisar",
                f"La última transferencia ({ult['fecha_escritura']:%d-%m-%Y}) se informó al SII sin precio. Puede ser una herencia, una donación, un aporte a sociedad o un registro sin monto. "
                "Si fue herencia, los herederos deben haber inscrito la posesión efectiva y firmar todos la venta (o haber hecho la partición).",
                ["Posesión efectiva e inscripción especial de herencia (si hubo herencia)", "Escritura de partición o firma de todos los herederos (si hubo herencia)"]))
        otras = t.head(t.height - 1).filter(sin_monto).height if t.height > 1 else 0
        if otras:
            out.append(Alerta("transferencias_sin_monto", "dominio", "info",
                f"Hay {otras} transferencia(s) anterior(es) sin precio desde {DESDE_MONTO.year} (herencia, donación, aporte o registro sin monto). Revise en la cadena de títulos que estén bien resueltas.",
                ["Inscripciones de dominio de los últimos 10 años"]))
        mismo_dia = t.filter(pl.col("fecha_escritura") >= hace10).group_by("fecha_escritura").len().filter(pl.col("len") >= 2)
        if mismo_dia.height:
            f = mismo_dia.sort("fecha_escritura")["fecha_escritura"][-1]
            out.append(Alerta("cuotas_mismo_dia", "dominio", "alerta",
                f"El {f:%d-%m-%Y} hubo {int(mismo_dia['len'].max())} enajenaciones del mismo rol el mismo día. Es típico de la venta de cuotas o derechos de una comunidad: "
                "verifique que quien vende sea dueño del 100% o que firmen todos los comuneros.",
                ["Inscripciones de cada cuota y su dueño actual"]))
        if d.get("uf_avaluo") and r.get("avaluo_total"):
            av_uf = r["avaluo_total"] / d["uf_avaluo"]
            bajas = t.filter((pl.col("fecha_escritura") >= dt.date(2022, 1, 1)) & (pl.col("monto_uf_norm") > 0) & (pl.col("monto_uf_norm") < 0.5 * av_uf))
            if bajas.height:
                b = bajas.row(-1, named=True)
                out.append(Alerta("precio_bajo_avaluo", "dominio", "revisar",
                    f"La venta del {b['fecha_escritura']:%d-%m-%Y} se informó en {_ent(b['monto_uf_norm'])} UF, menos de la mitad del avalúo fiscal ({_ent(av_uf)} UF). "
                    "Puede ser la venta de una cuota, una venta entre relacionados o una subvaluación (riesgo de lesión enorme o de revisión tributaria)."))
        rec = t.filter(pl.col("fecha_escritura") >= hace5).height
        if rec >= 3:
            out.append(Alerta("rotacion_alta", "dominio", "revisar",
                f"El rol tuvo {rec} transferencias en los últimos 5 años. Una rotación alta puede indicar ventas sucesivas de derechos o problemas con el predio."))
    ub = r.get("cod_ubicacion")
    sup = r.get("sup_terreno_m2") or 0
    if d["serie"] == "No agrícola" and ub in ("R", "E") and 0 < sup < 5000:
        out.append(Alerta("subdivision_rural", "urbanismo", "alerta",
            f"Predio fuera del área urbana según el SII (código {ub}) con {_ent(sup)} m², bajo el mínimo de 0,5 ha que exige el DL 3.516 para subdividir predios rústicos. "
            "Puede venir de un loteo irregular o de una venta de «derechos»; construir vivienda puede requerir autorización (art. 55 de la Ley General de Urbanismo y Construcciones).",
            ["Plano de subdivisión aprobado y certificado del SAG", "Informe favorable para construcción (art. 55 LGUC), si se va a construir"]))
    padre = (r.get("padre_predio") or 0) > 0
    if padre or d.get("linaje_alta"):
        txt = f"rol matriz {r.get('padre_comuna')}-{r.get('padre_manzana')}-{r.get('padre_predio')}" if padre else "apareció en el catastro después de 2021-2S"
        out.append(Alerta("rol_nuevo", "urbanismo", "revisar",
            f"El rol es nuevo o derivado ({txt}): viene de una subdivisión, un loteo o una copropiedad. Revise que esté aprobada y recibida por la municipalidad.",
            ["Plano de subdivisión o loteo aprobado, o reglamento de copropiedad", "Inscripción del predio matriz"]))
    if ub == "E":
        out.append(Alerta("extension_urbana", "urbanismo", "revisar",
            "El SII lo clasifica con el código E, sin definición publicada (probablemente área de extensión urbana). El uso de suelo permitido lo fija el plan regulador metropolitano: confírmelo en el Certificado de Informaciones Previas."))
    s = d.get("suelos")
    if s is not None and s.height:
        riego = s.filter(pl.col("cod_suelo").str.ends_with("R"))
        if riego.height:
            ha = float(riego["sup_ha"].sum())
            out.append(Alerta("suelo_riego", "agua", "revisar",
                f"{_ha(ha)} ha están clasificadas como suelo de riego. Ese valor supone agua: sin derechos de agua inscritos, el predio vale bastante menos.",
                ["Inscripción de los derechos de agua en el Registro de Aguas del Conservador", "Consulta en el Catastro Público de Aguas de la DGA"]))
    sa = d.get("sup_aumento")
    if sa:
        out.append(Alerta("superficie_aumento", "construcciones", "revisar",
            f"La superficie construida registrada subió de {sa['antes']:.0f} m² a {sa['despues']:.0f} m² desde 2022. Verifique que las construcciones tengan permiso y recepción final.",
            ["Permiso de edificación y certificado de recepción final (Dirección de Obras)"]))
    r27 = d.get("r27")
    if r27 and max(r27["max"], r27["hoy"]) <= 0:
        out.append(Alerta("contribuciones_2027", "costos", "info", "Exento de contribuciones hoy y en los tres escenarios del reavalúo 2027 (estimación no oficial)."))
    elif r27:
        out.append(Alerta("contribuciones_2027", "costos", "info",
            f"Contribución anual estimada para 2027 (reavalúo, no oficial): entre {_clp(r27['min'])} y {_clp(r27['max'])}, frente a {_clp(r27['hoy'])} hoy según la fórmula del SII."))
    return out


def documentos(alertas: list[Alerta]) -> list[str]:
    docs = list(DOCS_BASE)
    for a in alertas:
        for x in a.documentos:
            if x not in docs:
                docs.append(x)
    return docs


def semaforo(alertas: list[Alerta]) -> list[tuple[str, str, str]]:
    """(categoría, estado, detalle) con estado: alerta | revisar | sin alertas | no verificado."""
    out = []
    for k, nombre in CATEGORIAS:
        a = [x for x in alertas if x.categoria == k and x.nivel in ("alerta", "revisar")]
        if a:
            est = min((x.nivel for x in a), key=NIVELES.get)
            out.append((nombre, est, f"{len(a)} indicio(s)"))
        elif k in SIN_COBERTURA and k != "urbanismo":
            out.append((nombre, "no verificado", SIN_COBERTURA[k]))
        else:
            out.append((nombre, "sin alertas", "Sin indicios con estos datos" + (f". {SIN_COBERTURA[k]}" if k in SIN_COBERTURA else "")))
    return out


def cargar(d: dict) -> dict:
    """Completa la ficha de terreno con lo que necesitan las reglas (lecturas por rol, livianas)."""
    rid = d["rol_id"]
    cod = int(rid.split("-")[0])
    x = dict(d)
    x["transf"] = (pl.scan_parquet(pi.STAGING / "f2890.parquet").filter((pl.col("cod_comuna") == cod) & (pl.col("rol_id") == rid))
                   .select("fecha_escritura", "fecha_inscripcion", "monto_uf_norm").collect())
    uf = pl.scan_parquet(pi.STAGING / "uf.parquet").filter(pl.col("fecha") == dt.date(2026 if d["semestre"] == "2026-2S" else 2022, 7 if d["semestre"] == "2026-2S" else 1, 1)).collect()
    x["uf_avaluo"] = float(uf["uf"][0]) if uf.height else None
    g = (pl.scan_parquet(pi.STAGING / "fct_transferencia.parquet").filter((pl.col("cod_comuna") == cod) & (pl.col("rol_id") == rid) & (pl.col("n_roles_grupo") > 1))
         .select("fecha_escritura").collect())
    x["fechas_en_bloque"] = g["fecha_escritura"].to_list()  # depto + bodega + estacionamiento: el monto va en otro rol
    x["sup_aumento"] = None
    x["linaje_alta"] = False
    x["r27"] = None
    if d["serie"] == "No agrícola" and d["semestre"] == "2026-2S":
        a = pl.scan_parquet(pi.MARTS / "auditoria_roles_2026_2.parquet").filter((pl.col("rol_id") == rid) & (pl.col("senal") == "superficie_aumento")).collect()
        if a.height:
            x["sup_aumento"] = {"antes": a["valor_pares"][0], "despues": a["valor_rol"][0]}
        lj = pl.scan_parquet(pi.STAGING / "map_rol_linaje.parquet").filter((pl.col("rol_id") == rid) & (pl.col("tipo") == "alta")).collect()
        x["linaje_alta"] = lj.height > 0
        r27 = pi.leer_r27(rid, d["rol"])
        if r27.height:
            q = r27.row(0, named=True)
            v = [2 * float(q.get(f"contrib_27_{k}") or 0) for k in ("S0", "S2", "S1")]
            x["r27"] = {"min": min(v), "max": max(v), "hoy": 2 * float(q.get("contrib_teo") or 0)}
    return x


def html_seccion(alertas: list[Alerta]) -> str:
    e = html.escape
    color = {"alerta": "#b42318", "revisar": "#b54708", "sin alertas": "#067647", "no verificado": "#475467", "info": "#175cd3"}
    filas = "".join(f"<tr><td>{e(n)}</td><td><span class='niv' style='background:{color[s]}'>{e(s)}</span></td><td class=nota>{e(det)}</td></tr>" for n, s, det in semaforo(alertas))
    orden = sorted(alertas, key=lambda a: NIVELES[a.nivel])
    items = "".join(f"<li><span class='niv' style='background:{color[a.nivel]}'>{e(a.nivel)}</span> {e(a.texto)}</li>" for a in orden) or "<li>Sin indicios con los datos disponibles.</li>"
    docs = "".join(f"<li>{e(x)}</li>" for x in documentos(alertas))
    return (f"<h2>Riesgos que el vendedor podría omitir</h2><table><thead><tr><th>Categoría</th><th>Estado</th><th>Detalle</th></tr></thead><tbody>{filas}</tbody></table>"
            f"<ul class=al>{items}</ul>"
            "<p class=nota>Son indicios a partir del catastro del SII y de las enajenaciones informadas al SII (F2890), no un estudio de títulos. «Sin alertas» significa que estos datos no muestran problemas, no que no existan.</p>"
            f"<h2>Documentos que conviene exigir al vendedor</h2><ul>{docs}</ul>")
