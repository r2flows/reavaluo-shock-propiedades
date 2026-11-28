"""Servicio privado de pre-informes de títulos (FastAPI). Requiere clave.

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
<p><a href="reclamo">Revisión de avalúo para dueños →</a></p>
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
<p><a href="./">← Pre-informe de títulos</a></p>
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


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def inicio(error: str = "") -> str:
    ops = "".join(f"<option>{html.escape(c)}</option>" for c in comunas())
    return FORM.format(opciones=ops, error=f'<p class="err">{html.escape(error)}</p>' if error else "")


@app.post("/informe", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
async def informe(rol: str = Form(...), comuna: str = Form(...), archivos: list[UploadFile] = File(default=[])) -> HTMLResponse:
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
        datos = [(a.filename, await a.read(cert.MAX_BYTES + 1)) for a in subidos]
        lecturas = cert.leer_archivos(datos)
        del datos
        extra = cert.seccion_html(lecturas, cert.cruzar(lecturas, d["rol_id"], d["transf"]))
        del lecturas
    cuerpo = pi.informe(d, extra).replace("<body>", '<body><p><a href="./">← Otro rol</a></p>', 1)
    return HTMLResponse(cuerpo)


@app.get("/reclamo", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def reclamo_inicio(error: str = "") -> str:
    ops = "".join(f"<option>{html.escape(c)}</option>" for c in comunas())
    return FORM_RECLAMO.format(opciones=ops, error=f'<p class="err">{html.escape(error)}</p>' if error else "")


@app.post("/reclamo", response_class=HTMLResponse, dependencies=[Depends(autenticar)])
def reclamo(rol: str = Form(...), comuna: str = Form(...)) -> HTMLResponse:
    try:
        cands = pi.resolver(rol, comuna)
    except SystemExit as e:
        return HTMLResponse(reclamo_inicio(str(e)), status_code=400)
    d = exp.leer(cands)
    if d is None:
        return HTMLResponse(reclamo_inicio(f"El rol {rol} de {comuna} no está en el catastro 2021–2026 del Gran Santiago."), status_code=404)
    return HTMLResponse(exp.informe(d).replace("<body>", '<body><p><a href="reclamo">← Otro rol</a></p>', 1))


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
