"""Servicio de pre-informes de títulos (FastAPI).

Acceso (decisión del usuario, 28-11-2026): todas las rutas son abiertas, con un límite de consultas por IP para impedir
la extracción masiva (60 cada 10 minutos) y uno más estricto para la lectura de certificados (20 cada 10 minutos).
Los certificados del Conservador que sube el usuario se siguen procesando solo en memoria (CLAUDE.md). Las credenciales
PREINFORME_* y `autenticar` se conservan para volver a cerrar una ruta si hace falta.

Variables de entorno:
  PREINFORME_USUARIO, PREINFORME_CLAVE   credenciales de acceso (HTTP Basic sobre HTTPS). Sin ellas el servicio no parte.
  PREINFORME_DATOS                       carpeta con los datos empaquetados (src.titulos.empaquetar)
Privacidad (CLAUDE.md): los certificados subidos se procesan en memoria y se descartan; no hay base de datos, no se
escriben archivos y el registro de accesos está desactivado. Respuestas con no-store y noindex.
Local: PREINFORME_USUARIO=u PREINFORME_CLAVE=c PREINFORME_DATOS=privado/servicio/datos .venv/bin/python -m src.titulos.app
"""

from __future__ import annotations

import html
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.etl.common import REF
from src.titulos import certificados as cert
from src.producto import expediente as exp
from src.producto import carpeta as car
from src.producto import diligencia as dil
from src.producto import terreno as ter
from src.titulos import preinforme as pi

USUARIO = os.environ.get("PREINFORME_USUARIO", "")
CLAVE = os.environ.get("PREINFORME_CLAVE", "")
if len(CLAVE) < 16 or not USUARIO:
    raise RuntimeError("Faltan PREINFORME_USUARIO y PREINFORME_CLAVE (mínimo 16 caracteres)")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
basic = HTTPBasic(realm="Pre-informe de titulos")
FALLOS: dict[str, deque] = defaultdict(deque)
VENTANA, MAX_FALLOS = 900, 10


def ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")).split(",")[0].strip()


CONSULTAS: dict[str, deque] = defaultdict(deque)
VENTANA_PUBLICA, MAX_CONSULTAS = 600, 60  # 60 consultas cada 10 minutos por IP en las rutas abiertas


def limitar(req: Request) -> None:
    """Rutas abiertas: limita las consultas por IP (sin registrar nada) para que no se pueda extraer la base."""
    q, ahora = CONSULTAS[ip(req)], time.time()
    while q and ahora - q[0] > VENTANA_PUBLICA:
        q.popleft()
    if len(q) >= MAX_CONSULTAS:
        raise HTTPException(429, "Demasiadas consultas; espere unos minutos.")
    q.append(ahora)
    if len(CONSULTAS) > 50_000:  # evita que el diccionario crezca sin límite
        CONSULTAS.clear()


SUBIDAS: dict[str, deque] = defaultdict(deque)
MAX_SUBIDAS = 20  # lecturas de certificados cada 10 minutos por IP (leer PDF es lo más caro del servicio)


def limitar_subidas(req: Request) -> None:
    q, ahora = SUBIDAS[ip(req)], time.time()
    while q and ahora - q[0] > VENTANA_PUBLICA:
        q.popleft()
    if len(q) >= MAX_SUBIDAS:
        raise HTTPException(429, "Demasiadas lecturas de certificados; espere unos minutos.")
    q.append(ahora)
    if len(SUBIDAS) > 50_000:
        SUBIDAS.clear()


def autenticar(req: Request, cred: HTTPBasicCredentials = Depends(basic)) -> None:
    q, ahora = FALLOS[ip(req)], time.time()
    while q and ahora - q[0] > VENTANA:
        q.popleft()
    if len(q) >= MAX_FALLOS:
        raise HTTPException(429, "Demasiados intentos fallidos; espera 15 minutos.")
    ok = secrets.compare_digest(cred.username.encode(), USUARIO.encode()) & secrets.compare_digest(cred.password.encode(), CLAVE.encode())
    if not ok:
        q.append(ahora)
        raise HTTPException(401, "Credenciales inválidas", headers={"WWW-Authenticate": 'Basic realm="Pre-informe de titulos"'})


@app.middleware("http")
async def cabeceras(request: Request, call_next):
    r = await call_next(request)
    r.headers.update({
        "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
        "Strict-Transport-Security": "max-age=31536000",
    })
    return r


def comunas() -> list[str]:
    import polars as pl

    return sorted(pl.read_csv(REF / "comunas_cut.csv", separator=";")["nombre_mapa"].unique().to_list())


FORM = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-informe de títulos</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#d0d5dd;--bg:#fff;--soft:#f9fafb;--acc:#1849a9}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26;--acc:#84adff}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:640px;margin:0 auto;padding:28px 16px}}
h1{{font-size:1.4rem}} label{{display:block;font-weight:600;margin:14px 0 4px}} small{{color:var(--ink2);font-weight:400}}
input,select{{font:inherit;width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--soft);color:var(--ink)}}
button{{margin-top:18px;font:inherit;font-weight:600;padding:10px 18px;border:0;border-radius:8px;background:var(--acc);color:#fff;cursor:pointer}}
.caja{{background:var(--soft);border:1px solid var(--rule);border-radius:8px;padding:10px 14px;font-size:.88rem;color:var(--ink2)}}
.err{{color:#b42318;font-weight:600}}
</style></head><body>
<p><a href="reclamo">Revisión de avalúo para dueños →</a> · <a href="terreno">Ficha de terreno y búsqueda por dirección →</a> · <a href="carpeta">Carpeta para corredores →</a></p>
<h1>Pre-informe de títulos</h1>
<p class="caja">Ingresa un rol del Gran Santiago. Opcional: sube los certificados del Conservador (PDF) para cruzarlos con las transferencias informadas al SII. <b>Los certificados se procesan en memoria y no se guardan.</b></p>
{error}
<form method="post" action="informe" enctype="multipart/form-data">
<label for="comuna">Comuna</label>
<select id="comuna" name="comuna" required>{opciones}</select>
<label for="rol">Rol <small>(manzana-predio, por ejemplo 152-779)</small></label>
<input id="rol" name="rol" required pattern="\\d{{1,5}}-\\d{{1,5}}" inputmode="numeric" autocomplete="off">
<label for="pdf">Certificados del Conservador <small>(opcional, hasta 8 PDF de 12 MB)</small></label>
<input id="pdf" name="archivos" type="file" accept="application/pdf" multiple>
<button type="submit">Generar pre-informe</button>
</form></body></html>"""


FORM_RECLAMO = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisión de avalúo</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#d0d5dd;--bg:#fff;--soft:#f9fafb;--acc:#1849a9}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26;--acc:#84adff}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:640px;margin:0 auto;padding:28px 16px}}
h1{{font-size:1.4rem}} label{{display:block;font-weight:600;margin:14px 0 4px}} small{{color:var(--ink2);font-weight:400}}
input,select{{font:inherit;width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--soft);color:var(--ink)}}
button{{margin-top:18px;font:inherit;font-weight:600;padding:10px 18px;border:0;border-radius:8px;background:var(--acc);color:#fff;cursor:pointer}}
.caja{{background:var(--soft);border:1px solid var(--rule);border-radius:8px;padding:10px 14px;font-size:.88rem;color:var(--ink2)}}
.err{{color:#b42318;font-weight:600}}
</style></head><body>
<p><a href="terreno">Ficha de terreno →</a></p>
<h1>Revisión de avalúo y contribuciones 2027</h1>
<p class="caja">Para dueños: cuánto pagaría en 2027 en tres escenarios, si hay indicios de error técnico en su avalúo (superficie, clasificación o cálculo), ventas comparables y cómo reclamar.</p>
{error}
<form method="post" action="reclamo">
<label for="comuna">Comuna</label>
<select id="comuna" name="comuna" required>{opciones}</select>
<label for="rol">Rol <small>(manzana-predio, por ejemplo 152-779)</small></label>
<input id="rol" name="rol" required pattern="\\d{{1,5}}-\\d{{1,5}}" inputmode="numeric" autocomplete="off">
<button type="submit">Revisar avalúo</button>
</form></body></html>"""


@app.get("/salud", response_class=PlainTextResponse)
def salud() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def inicio(error: str = "") -> str:
    ops = "".join(f"<option>{html.escape(c)}</option>" for c in comunas())
    return FORM.format(opciones=ops, error=f'<p class="err">{html.escape(error)}</p>' if error else "")


@app.post("/informe", response_class=HTMLResponse, dependencies=[Depends(limitar)])
async def informe(request: Request, rol: str = Form(...), comuna: str = Form(...), archivos: list[UploadFile] = File(default=[])) -> HTMLResponse:
    try:
        cands = pi.resolver(rol, comuna)
    except SystemExit as e:
        return HTMLResponse(inicio(str(e)), status_code=400)
    d = pi.leer(cands)
    if d is None:
        return HTMLResponse(inicio(f"El rol {rol} de {comuna} no está en el catastro 2021–2026 del Gran Santiago."), status_code=404)
    extra = ""
    subidos = [a for a in archivos if a.filename][: cert.MAX_ARCHIVOS]
    if subidos:
        limitar_subidas(request)
        datos = [(a.filename, await a.read(cert.MAX_BYTES + 1)) for a in subidos]
        lecturas = cert.leer_archivos(datos)
        del datos
        extra = cert.seccion_html(lecturas, cert.cruzar(lecturas, d["rol_id"], d["transf"]))
        del lecturas
    cuerpo = pi.informe(d, extra).replace("<body>", '<body><p><a href="./">← Otro rol</a></p>', 1)
    return HTMLResponse(cuerpo)


@app.get("/reclamo", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def reclamo_inicio(error: str = "") -> str:
    ops = "".join(f"<option>{html.escape(c)}</option>" for c in comunas())
    return FORM_RECLAMO.format(opciones=ops, error=f'<p class="err">{html.escape(error)}</p>' if error else "")


@app.post("/reclamo", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def reclamo(rol: str = Form(...), comuna: str = Form(...)) -> HTMLResponse:
    try:
        cands = pi.resolver(rol, comuna)
    except SystemExit as e:
        return HTMLResponse(reclamo_inicio(str(e)), status_code=400)
    d = exp.leer(cands)
    if d is None:
        return HTMLResponse(reclamo_inicio(f"El rol {rol} de {comuna} no está en el catastro 2021–2026 del Gran Santiago."), status_code=404)
    return HTMLResponse(exp.informe(d).replace("<body>", '<body><p><a href="reclamo">← Otro rol</a></p>', 1))


PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo}</title><meta name="robots" content="noindex">
<style>
:root{{--ink:#101828;--ink2:#475467;--rule:#d0d5dd;--bg:#fff;--soft:#f9fafb;--acc:#1849a9}}
@media (prefers-color-scheme:dark){{:root{{--ink:#f2f4f7;--ink2:#98a2b3;--rule:#344054;--bg:#0c111d;--soft:#161b26;--acc:#84adff}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg);max-width:760px;margin:0 auto;padding:28px 16px}}
h1{{font-size:1.4rem}} h2{{font-size:1.05rem;margin:1.6em 0 .4em;border-bottom:1px solid var(--rule);padding-bottom:4px}}
label{{display:block;font-weight:600;margin:14px 0 4px}} small{{color:var(--ink2);font-weight:400}}
input,select{{font:inherit;width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--soft);color:var(--ink)}}
button{{font:inherit;font-weight:600;padding:8px 14px;border:0;border-radius:8px;background:var(--acc);color:#fff;cursor:pointer}}
form.inline{{display:inline}} form.inline button{{padding:4px 10px;font-size:.85rem}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--rule);vertical-align:top}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:.9rem}} dt{{color:var(--ink2)}}
.caja{{background:var(--soft);border:1px solid var(--rule);border-radius:8px;padding:10px 14px;font-size:.88rem;color:var(--ink2)}}
.nota{{font-size:.82rem;color:var(--ink2)}} .err{{color:#b42318;font-weight:600}}
.niv{{display:inline-block;color:#fff;font-size:.7rem;text-transform:uppercase;padding:1px 6px;border-radius:4px;margin-right:4px;white-space:nowrap}} ul.al li{{margin:.4em 0}}
</style></head><body><p><a href="terreno">Ficha de terreno</a> · <a href="carpeta">Carpeta para corredores</a> · <a href="reclamo">Revisión de avalúo 2027</a></p>{cuerpo}</body></html>"""


def _comunas_terreno() -> list[tuple[int, str]]:
    c = ter.comunas_con_datos()
    return [(int(k), str(n).title()) for k, n in zip(c["cod_comuna"], c["nombre_sii"])]


def _form_terreno(error: str = "", cod: int | None = None, q: str = "") -> str:
    ops = "".join(f'<option value="{k}"{" selected" if k == cod else ""}>{html.escape(n)}</option>' for k, n in _comunas_terreno())
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return (f"<h1>Ficha de terreno</h1><p class='caja'>Busque por rol (manzana-predio) o por dirección. Muestra si el predio es urbano o rural según el SII, "
            f"sus clases de suelo si es agrícola, superficie, avalúo y contribución. Gran Santiago: catastro 2026-2S; resto de la Región Metropolitana: predios agrícolas del catastro 2022-1S.</p>{err}"
            f'<form method="post" action="terreno"><label for="cod">Comuna</label><select id="cod" name="cod" required>{ops}</select>'
            f'<label for="q">Rol o dirección <small>(por ejemplo 1035-64, o «Los Héroes parcela 39»)</small></label>'
            f'<input id="q" name="q" required maxlength="120" value="{html.escape(q)}" autocomplete="off"><p><button type="submit">Buscar</button></p></form>')


@app.get("/terreno", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def terreno_inicio() -> str:
    return PAGINA.format(titulo="Ficha de terreno", cuerpo=_form_terreno())


@app.post("/terreno", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def terreno(cod: int = Form(...), q: str = Form(...)) -> HTMLResponse:
    import re

    nombres = dict(_comunas_terreno())
    if cod not in nombres:
        return HTMLResponse(PAGINA.format(titulo="Ficha de terreno", cuerpo=_form_terreno("Comuna sin datos.", None, q)), status_code=400)
    q = q.strip()[:120]
    if re.fullmatch(r"\d{1,5}-\d{1,5}", q):
        m, p = q.split("-")
        d = ter.ficha(f"{cod}-{int(m)}-{int(p)}")
        if d is None:
            return HTMLResponse(PAGINA.format(titulo="Ficha de terreno", cuerpo=_form_terreno(f"El rol {q} no está en los datos de {nombres[cod]}.", cod, q)), status_code=404)
        extra = ""
        import polars as pl

        gs = pl.read_csv(REF / "comunas_cut.csv", separator=";")
        cut = gs.filter(pl.col("cod_comuna") == cod)["nombre_mapa"].to_list()
        if cut and gs.filter(pl.col("nombre_mapa") == cut[0]).height > 1:
            cut = []  # Santiago tiene 3 códigos SII: el formulario por nombre de comuna podría abrir otro rol
        if cut and d["semestre"] == "2026-2S":
            campos = f'<input type="hidden" name="comuna" value="{html.escape(cut[0])}"><input type="hidden" name="rol" value="{int(m)}-{int(p)}">'
            extra = (f'<form class="inline" method="post" action="informe">{campos}<button>Pre-informe de títulos</button></form> '
                     f'<form class="inline" method="post" action="reclamo">{campos}<button>Revisión de avalúo 2027</button></form>')
        boton = (f'<form class="inline" method="post" action="carpeta" enctype="multipart/form-data"><input type="hidden" name="cod" value="{cod}">'
                 f'<input type="hidden" name="rol" value="{int(m)}-{int(p)}"><button>Carpeta para corredores (PDF)</button></form> ')
        extra = "<h2>Más sobre este rol</h2>" + boton + extra
        return HTMLResponse(PAGINA.format(titulo=f"Terreno · rol {d['rol_id']}", cuerpo=ter.html_ficha(d, nombres[cod]) + dil.html_seccion(dil.evaluar(dil.cargar(d))) + extra))
    res = ter.buscar(cod, q)
    if not res.height:
        return HTMLResponse(PAGINA.format(titulo="Ficha de terreno", cuerpo=_form_terreno(f"Sin resultados para «{q}» en {nombres[cod]}. Pruebe con menos palabras o solo el nombre de la calle y el número.", cod, q)), status_code=404)
    filas = "".join(
        f'<tr><td>{html.escape(r["direccion"] or "—")}</td><td>{html.escape(r["rol_id"])}</td><td>{html.escape(pi.DESTINOS.get(r["destino"], r["destino"] or "—"))}</td><td>{html.escape(ter.ubicacion(r["cod_ubicacion"])[0].split(" (")[0])}</td>'
        f'<td><form class="inline" method="post" action="terreno"><input type="hidden" name="cod" value="{cod}"><input type="hidden" name="q" value="{html.escape(r["rol_id"].split("-", 1)[1])}"><button>Ver ficha</button></form></td></tr>'
        for r in res.iter_rows(named=True)
    )
    cuerpo = _form_terreno("", cod, q) + (f"<h2>{res.height} resultado(s){' (se muestran los primeros 30)' if res.height >= ter.MAX_RESULTADOS else ''}</h2>"
                                           f"<table><thead><tr><th>Dirección</th><th>Rol</th><th>Destino</th><th>Ubicación SII</th><th></th></tr></thead><tbody>{filas}</tbody></table>")
    return HTMLResponse(PAGINA.format(titulo="Ficha de terreno", cuerpo=cuerpo))


def _form_carpeta(error: str = "", cod: int | None = None, rol: str = "", corredora: str = "") -> str:
    ops = "".join(f'<option value="{k}"{" selected" if k == cod else ""}>{html.escape(n)}</option>' for k, n in _comunas_terreno())
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return (f"<h1>Carpeta de la propiedad</h1><p class='caja'>Para corredores y brokers: identificación, antifraude, historia de transferencias, valor, riesgos y trámites por organismo de un rol, "
            f"en un documento que se imprime o guarda como PDF. Si no sabe el rol, búsquelo por dirección en la <a href='terreno'>ficha de terreno</a>.</p>{err}"
            f'<form method="post" action="carpeta" enctype="multipart/form-data"><label for="cod">Comuna</label><select id="cod" name="cod" required>{ops}</select>'
            f'<label for="rol">Rol <small>(manzana-predio, por ejemplo 1035-64)</small></label><input id="rol" name="rol" required pattern="\\d{{1,5}}-\\d{{1,5}}" value="{html.escape(rol)}" autocomplete="off">'
            f'<label for="corredora">Preparado por <small>(opcional: nombre de la corredora, aparece en el encabezado)</small></label><input id="corredora" name="corredora" maxlength="80" value="{html.escape(corredora)}">'
            f'<label for="rut">RUT del vendedor <small>(opcional: se compara con el certificado de dominio, en memoria; no se guarda)</small></label><input id="rut" name="rut" maxlength="14" autocomplete="off">'
            f'<label for="pdf">Certificados del Conservador <small>(opcional: dominio vigente y gravámenes, hasta 8 PDF de 12 MB; se procesan en memoria y no se guardan)</small></label>'
            f'<input id="pdf" name="archivos" type="file" accept="application/pdf" multiple><p><button type="submit">Armar carpeta</button></p></form>')


@app.get("/carpeta", response_class=HTMLResponse, dependencies=[Depends(limitar)])
def carpeta_inicio() -> str:
    return PAGINA.format(titulo="Carpeta de la propiedad", cuerpo=_form_carpeta())


@app.post("/carpeta", response_class=HTMLResponse, dependencies=[Depends(limitar)])
async def carpeta(request: Request, cod: int = Form(...), rol: str = Form(...), corredora: str = Form(""), rut: str = Form(""),
                  archivos: list[UploadFile] = File(default=[])) -> HTMLResponse:
    import re

    nombres = dict(_comunas_terreno())
    rol = rol.strip()
    if cod not in nombres or not re.fullmatch(r"\d{1,5}-\d{1,5}", rol):
        return HTMLResponse(PAGINA.format(titulo="Carpeta de la propiedad", cuerpo=_form_carpeta("Revise la comuna y el rol (manzana-predio).", cod, rol, corredora)), status_code=400)
    m, p = rol.split("-")
    lecturas = None
    subidos = [a for a in archivos if a.filename][: cert.MAX_ARCHIVOS]
    if subidos:
        limitar_subidas(request)
        datos = [(a.filename, await a.read(cert.MAX_BYTES + 1)) for a in subidos]
        lecturas = cert.leer_archivos(datos)
        del datos
    cuerpo = car.armar(f"{cod}-{int(m)}-{int(p)}", nombres[cod], corredora.strip()[:80], lecturas, rut.strip() or None)
    del lecturas, rut
    if cuerpo is None:
        return HTMLResponse(PAGINA.format(titulo="Carpeta de la propiedad", cuerpo=_form_carpeta(f"El rol {rol} no está en los datos de {nombres[cod]}.", cod, rol, corredora)), status_code=404)
    return HTMLResponse(cuerpo)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
