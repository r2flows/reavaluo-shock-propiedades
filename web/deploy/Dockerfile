# Sitio estático del atlas (Railway). Se construye desde web/build/ (ver src/presentacion/construir_pagina.py).
FROM caddy:2.8.4-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html /srv/index.html
COPY sitio_datos/ /srv/data/
