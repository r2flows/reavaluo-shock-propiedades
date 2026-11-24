"""Nombres reconocibles para los microbarrios a partir de las calles del catastro SII.

Para cada microbarrio se cuentan los *frentes* por calle: los pares distintos (calle, número) de todos sus roles.
Contar frentes, no roles, evita que un edificio de 500 departamentos domine el nombre. El puntaje de una calle es
frentes × (frentes en el microbarrio / frentes en la comuna)^0,5. Así gana la calle propia del sector y no la avenida
que cruza media comuna. Los pasajes valen un tercio.
nombre = las 2 calles con mayor puntaje (mínimo 3 frentes); si dos microbarrios de una comuna empatan, se agrega
una tercera calle y, si aún empatan, el rango de manzanas.

Ortografía: si existe data/raw/osm/calles_*.csv (nombres de vías de OpenStreetMap), se recuperan tildes y eñes
(VICUNA MACKENNA → Vicuña Mackenna) y se expanden iniciales (M RODRIGUEZ → Manuel Rodríguez) cuando la
coincidencia es única.

Salidas (solo agregados por microbarrio, sin números de casa ni roles):
  data/staging/microbarrio_nombres.parquet  (microbarrio_id, nombre, calles)
  web/data/calles.json                      {cut: {calle: [microbarrio_id, …]}}
Uso: scripts/correr.sh --mem 4G src.presentacion.nombres
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict

import polars as pl

from src.etl.common import RAW, REF, ROOT, STAGING

SALIDA_PQ = STAGING / "microbarrio_nombres.parquet"
SALIDA_JS = ROOT / "web" / "data" / "calles.json"
MIN_FRENTES = 3
# Tokens que marcan el fin del nombre de la calle (unidad, lote, torre, villa…)
CORTE = {"DP", "DPTO", "DEPTO", "DDP", "BX", "BD", "BDB", "OF", "EST", "LC", "LT", "LOTE", "SITIO", "ST", "T", "TORRE", "BK", "BLOCK", "BL", "PC", "PARC", "CASA", "E", "V", "PB", "LOC", "MZ"}
PREFIJOS = {"AV": "Av.", "AVDA": "Av.", "AVENIDA": "Av.", "PJ": "Pje.", "PAJ": "Pje.", "PJE": "Pje.", "PSJ": "Pje.", "PSJE": "Pje.", "PASAJE": "Pje.", "CALLE": "", "CAMINO": "Camino"}
EXPANDE = {"STA": "SANTA", "STO": "SANTO", "GRAL": "GENERAL", "PDTE": "PRESIDENTE", "CAP": "CAPITAN", "NTE": "NORTE", "PTE": "PONIENTE", "OTE": "ORIENTE", "SR": "SEÑOR", "DR": "DOCTOR", "PROF": "PROFESOR", "STGO": "SANTIAGO", "NVA": "NUEVA", "NVO": "NUEVO", "ALTE": "ALMIRANTE", "TTE": "TENIENTE", "CDTE": "COMANDANTE", "CNEL": "CORONEL", "MONS": "MONSEÑOR", "PBRO": "PRESBITERO"}
MINUS = {"de", "del", "la", "las", "los", "y", "el", "e", "a"}


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").upper()


def calle_de(direccion: str | None) -> tuple[str, str, str] | None:
    """(clave, prefijo, número) o None. La clave no lleva prefijo (AV, PJE) ni puntuación."""
    if not direccion:
        return None
    texto = re.sub(r"([A-Z])(\d{2,})", r"\1 \2", re.sub(r"[.,#]", " ", direccion.upper()))  # ROMERO2569 → ROMERO 2569
    toks = texto.split()
    for i, t in enumerate(toks):
        if i > 0 and re.fullmatch(r"\d{1,8}([/-]\d*)?", t):
            nombre = toks[:i]
            for j, x in enumerate(nombre):
                if j > 0 and x in CORTE:
                    nombre = nombre[:j]
                    break
            pref = ""
            if nombre and nombre[0] == "ALAMEDA" and len(nombre) > 1:
                nombre = nombre[1:]
                nombre = ["ALAMEDA"] if re.search(r"HIGGINS", " ".join(nombre)) else nombre
            while nombre and nombre[0] in PREFIJOS and len(nombre) > 1:
                pref = PREFIJOS[nombre[0]] or pref
                nombre = nombre[1:]
            nombre = [EXPANDE.get(x, x) for x in nombre]
            j = " ".join(nombre)
            if re.fullmatch(r"(ALAMEDA )?(LIB(ERTADOR)? )?(BDO |BERNARDO )?O ?HIGGINS", j) and re.match(r"(ALAMEDA|LIB)", j):
                nombre, pref = ["ALAMEDA"], ""
            if not nombre or not re.search(r"[A-Z]{2}", " ".join(nombre)):
                return None
            clave = " ".join(nombre)
            # Restos de numeración pegados al nombre (PJ1, 325/): fuera, salvo ordinales (1A TRANSVERSAL, 4TA AVENIDA)
            if re.search(r"\d{3,}|[A-Z]\d|\d+(?!\d)(?!(A|RA|DA|TA|VA|NA|MA|O)?\b)", clave):
                return None
            return clave, pref, str(int(re.match(r"\d+", t).group()))
    return None


def compatible(corta: list[str], larga: list[str]) -> bool:
    """M RODRIGUEZ ⊂ MANUEL RODRIGUEZ: mismas palabras, donde la corta puede tener iniciales."""
    if len(corta) != len(larga) or corta == larga:
        return False
    return all(a == b or (len(a) == 1 and b.startswith(a)) for a, b in zip(corta, larga))


def misma_calle(a: list[str], b: list[str]) -> bool:
    """Una es prefijo de la otra (palabra a palabra, admitiendo iniciales): A ROJAS ~ A ROJAS JIMENEZ."""
    corta, larga = (a, b) if len(a) <= len(b) else (b, a)
    if len(corta) < 2 and len(larga) > 1:
        return False
    return all(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)) for x, y in zip(corta, larga))


def ortografia() -> dict[str, list[str]]:
    """Clave sin tildes → nombres OSM con esa clave (sin prefijos)."""
    archivos = sorted((RAW / "osm").glob("calles_*.csv")) if (RAW / "osm").exists() else []
    if not archivos:
        return {}
    idx: dict[str, Counter] = defaultdict(Counter)
    for linea in archivos[-1].read_text(encoding="utf8").splitlines():
        nombre = linea.strip().strip('"')
        if not nombre:
            continue
        toks = nombre.split()
        while len(toks) > 1 and sin_tildes(toks[0]).rstrip(".") in PREFIJOS:
            toks = toks[1:]
        idx[sin_tildes(" ".join(toks))][" ".join(toks)] += 1
    return {k: [n for n, _ in c.most_common()] for k, c in idx.items()}


def bonito(clave: str, pref: str, osm: dict[str, list[str]]) -> str:
    if clave in osm:
        base = osm[clave][0]
    else:
        toks = clave.split()
        cands = [k for k in osm if len(k.split()) == len(toks) and compatible(toks, k.split())] if any(len(t) == 1 for t in toks) else []
        if len(cands) == 1:
            base = osm[cands[0]][0]
        else:
            base = " ".join(w.lower() if (i and w.lower() in MINUS) else (w if len(w) == 1 else w.capitalize()) for i, w in enumerate(clave.split()))
    return f"{pref} {base}".strip() if pref else base


def main() -> None:
    mb = pl.read_parquet(STAGING / "map_barrio.parquet", columns=["cod_comuna", "manzana", "microbarrio_id"])
    r = pl.read_parquet(STAGING / "catastro" / "roles_2026_2.parquet", columns=["cod_comuna", "manzana", "direccion"]).join(mb, on=["cod_comuna", "manzana"], how="inner")
    n_in = r.height
    filas, sin_calle = [], 0
    for mid, mz, d in zip(r["microbarrio_id"].to_list(), r["manzana"].to_list(), r["direccion"].to_list()):
        p = calle_de(d)
        if p is None:
            sin_calle += 1
            continue
        filas.append((mid, mid.split("-")[0], mz, p[0], p[1], p[2]))
    del r
    f = pl.DataFrame(filas, schema=["microbarrio_id", "cod", "manzana", "clave", "pref", "numero"], orient="row")
    del filas
    # Une variantes con iniciales dentro de la comuna (M RODRIGUEZ → MANUEL RODRIGUEZ)
    por_cod = f.group_by("cod", "clave").agg(pl.col("numero").n_unique().alias("n"))
    remap = {}
    for (cod,), g in por_cod.group_by(["cod"]):
        claves = sorted(zip(g["clave"].to_list(), g["n"].to_list()), key=lambda x: -x[1])
        for k, _ in claves:
            if any(len(t) == 1 for t in k.split()):
                destino = [k2 for k2, _ in claves if compatible(k.split(), k2.split())]
                if len(destino) == 1:
                    remap[(cod, k)] = destino[0]
    if remap:
        f = f.with_columns(pl.struct("cod", "clave").map_elements(lambda s: remap.get((s["cod"], s["clave"]), s["clave"]), return_dtype=pl.Utf8).alias("clave"))
    # Frentes por microbarrio y calle; prefijo más frecuente
    g = f.group_by("microbarrio_id", "cod", "clave").agg(
        pl.struct("numero", "pref").n_unique().alias("frentes"),
        pl.col("manzana").n_unique().alias("manzanas"),
        pl.col("pref").mode().first().alias("pref"),
    )
    tot = g.group_by("cod", "clave").agg(pl.col("frentes").sum().alias("frentes_comuna"))
    g = g.join(tot, on=["cod", "clave"]).with_columns(
        (pl.col("frentes") * (pl.col("frentes") / pl.col("frentes_comuna")).sqrt() * pl.when(pl.col("pref") == "Pje.").then(1 / 3).otherwise(1.0)).alias("puntaje")
    ).filter(pl.col("frentes") >= MIN_FRENTES)
    osm = ortografia()
    rango = mb.group_by("microbarrio_id").agg(pl.col("manzana").min().alias("a"), pl.col("manzana").max().alias("b"))
    rango = dict(zip(rango["microbarrio_id"].to_list(), zip(rango["a"].to_list(), rango["b"].to_list())))
    calles_mb: dict[str, list[tuple[str, float]]] = {}
    cod_de: dict[str, str] = {}
    for (mid,), x in g.sort("puntaje", descending=True).group_by(["microbarrio_id"], maintain_order=True):
        tot_fr = x["frentes"].sum()
        # Variantes de una misma calle en el microbarrio (A ROJAS / A ROJAS JIMENEZ) se suman a la de mayor puntaje
        kept: list[list] = []
        for k, p, fr in zip(x["clave"].to_list(), x["pref"].to_list(), x["frentes"].to_list()):
            t = k.split()
            dup = next((e for e in kept if misma_calle(t, e[0].split())), None)
            if dup:
                dup[2] += fr
            else:
                kept.append([k, p, fr])
        calles_mb[mid] = [(bonito(k, p, osm), fr / tot_fr) for k, p, fr in kept]
        cod_de[mid] = x["cod"][0]
    # Nombres únicos por comuna
    nombres: dict[str, str] = {}
    por_comuna: dict[str, list[str]] = defaultdict(list)
    for mid in calles_mb:
        por_comuna[cod_de[mid]].append(mid)
    for cod, mids in por_comuna.items():
        prop = {m: " · ".join(c for c, _ in calles_mb[m][:2]) for m in mids}
        rep = Counter(prop.values())
        for m in mids:
            if rep[prop[m]] > 1 and len(calles_mb[m]) > 2:
                prop[m] = " · ".join(c for c, _ in calles_mb[m][:3])
        rep = Counter(prop.values())
        for m in mids:
            nombres[m] = prop[m] + (f" (mz {rango[m][0]}–{rango[m][1]})" if rep[prop[m]] > 1 else "")
    out = pl.DataFrame({
        "microbarrio_id": list(nombres),
        "nombre": list(nombres.values()),
        "calles": [json.dumps([[c, round(s * 100)] for c, s in calles_mb[m][:6]], ensure_ascii=False) for m in nombres],
    })
    out.write_parquet(SALIDA_PQ)
    # Índice calle → microbarrios (las 8 calles principales de cada microbarrio, con ≥ MIN_FRENTES frentes)
    cuts = pl.read_csv(REF / "comunas_cut.csv", separator=";", schema={"cod_comuna": pl.Int32, "cut": pl.Utf8, "nombre_mapa": pl.Utf8})
    cod2cut = dict(zip(map(str, cuts["cod_comuna"].to_list()), cuts["cut"].to_list()))
    idx: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for m, cs in calles_mb.items():
        for c, _ in cs[:8]:
            idx[cod2cut[cod_de[m]]][c].append(m)
    SALIDA_JS.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    total_mb = mb["microbarrio_id"].n_unique()
    print(f"[nombres] roles: {n_in} entrada, {sin_calle} sin calle/número legible; {len(remap)} variantes con iniciales unidas; ortografía OSM: {'sí' if osm else 'no'} ({len(osm)} nombres)")
    print(f"[nombres] {len(nombres)}/{total_mb} microbarrios con nombre ({total_mb - len(nombres)} quedan con rango de manzanas) → {SALIDA_PQ.relative_to(ROOT)}")
    print(f"[nombres] índice de calles: {sum(len(v) for v in idx.values())} calles → {SALIDA_JS.relative_to(ROOT)} ({SALIDA_JS.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
