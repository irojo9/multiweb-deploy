#!/usr/bin/env python3
"""Sube a R2 una lista de archivos usando la API de Cloudflare directamente.

Más rápido que lanzar «wrangler r2 object put» por archivo (cada llamada arranca
Node) y reanudable: antes de subir, lista lo que ya hay en R2 bajo el prefijo del
cliente y se salta los archivos idénticos (misma huella MD5 y mismo tamaño). Así, si
un despliegue se corta a medias, el siguiente solo sube lo que faltaba.

La API admite unas 1.200 peticiones cada 5 minutos por token: se limita el ritmo a
RITMO peticiones por segundo y se reintenta con espera si responde 429 o 5xx.

Uso: r2-subir.py BUCKET PREFIJO CARPETA LISTA_DE_CLAVES
Variables: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
Sale con 1 si algún archivo no se ha podido subir.
"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get('R2_API', 'https://api.cloudflare.com/client/v4')
RITMO = float(os.environ.get('R2_RITMO', '3.5'))  # peticiones por segundo
HILOS = int(os.environ.get('R2_HILOS', '8'))

TIPOS = {
    'html': 'text/html; charset=utf-8', 'htm': 'text/html; charset=utf-8',
    'css': 'text/css; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'mjs': 'text/javascript; charset=utf-8',
    'json': 'application/json; charset=utf-8', 'map': 'application/json; charset=utf-8',
    'webmanifest': 'application/manifest+json; charset=utf-8', 'xml': 'application/xml; charset=utf-8',
    'txt': 'text/plain; charset=utf-8', 'md': 'text/plain; charset=utf-8',
    'svg': 'image/svg+xml', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif',
    'webp': 'image/webp', 'avif': 'image/avif', 'ico': 'image/x-icon',
    'woff2': 'font/woff2', 'woff': 'font/woff', 'ttf': 'font/ttf', 'otf': 'font/otf',
    'pdf': 'application/pdf', 'mp3': 'audio/mpeg', 'm4a': 'audio/mp4', 'mp4': 'video/mp4', 'webm': 'video/webm',
}


def tipo(clave):
    return TIPOS.get(clave.rsplit('.', 1)[-1].lower() if '.' in clave else '', 'application/octet-stream')


class Ritmo:
    """Reparte las peticiones para no pasar de RITMO por segundo entre todos los hilos."""

    def __init__(self, por_segundo):
        self.intervalo = 1.0 / por_segundo
        self.siguiente = time.monotonic()
        self.cerrojo = threading.Lock()

    def esperar(self):
        with self.cerrojo:
            ahora = time.monotonic()
            turno = max(ahora, self.siguiente)
            self.siguiente = turno + self.intervalo
        if turno > ahora:
            time.sleep(turno - ahora)


def main():
    bucket, prefijo, carpeta, lista = sys.argv[1:5]
    token = os.environ['CLOUDFLARE_API_TOKEN']
    cuenta = os.environ['CLOUDFLARE_ACCOUNT_ID']
    base = f'{API}/accounts/{cuenta}/r2/buckets/{bucket}/objects'
    ritmo = Ritmo(RITMO)

    def peticion(url, metodo='GET', datos=None, cabeceras=None):
        for intento in range(6):
            ritmo.esperar()
            req = urllib.request.Request(url, data=datos, method=metodo,
                                         headers={'Authorization': f'Bearer {token}', **(cabeceras or {})})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and intento < 5:
                    time.sleep(min(60, float(os.environ.get("R2_ESPERA", "5")) * 2 ** intento))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if intento < 5:
                    time.sleep(min(60, float(os.environ.get("R2_ESPERA", "5")) * 2 ** intento))
                    continue
                raise

    claves = [l.rstrip('\n') for l in open(lista, encoding='utf-8') if l.strip()]

    # Lo que ya hay en R2 bajo el prefijo: clave -> (etag, tamaño).
    existentes = {}
    try:
        cursor = ''
        while True:
            q = {'prefix': f'{prefijo}/', 'per_page': '1000'}
            if cursor:
                q['cursor'] = cursor
            r = json.loads(peticion(f'{base}?{urllib.parse.urlencode(q)}'))
            for o in r.get('result') or []:
                existentes[o['key']] = (str(o.get('etag', '')).strip('"'), int(o.get('size', -1)))
            cursor = (r.get('result_info') or {}).get('cursor') or ''
            if not cursor or not (r.get('result_info') or {}).get('is_truncated', True):
                break
        print(f'En R2 ya hay {len(existentes)} archivos de {prefijo}.', flush=True)
    except Exception as e:  # sin lista, se sube todo como antes
        print(f'::warning::No se ha podido listar R2 ({e}); se sube todo.', flush=True)
        existentes = {}

    pendientes = []
    for clave in claves:
        ruta = os.path.join(carpeta, clave)
        previo = existentes.get(f'{prefijo}/{clave}')
        if previo and previo[1] == os.path.getsize(ruta):
            with open(ruta, 'rb') as f:
                if hashlib.md5(f.read()).hexdigest() == previo[0]:
                    continue
        pendientes.append(clave)
    print(f'A subir de verdad: {len(pendientes)} (iguales en R2: {len(claves) - len(pendientes)}).', flush=True)

    hechos = 0
    fallos = []
    cerrojo = threading.Lock()

    def subir(clave):
        nonlocal hechos
        with open(os.path.join(carpeta, clave), 'rb') as f:
            datos = f.read()
        url = f'{base}/{urllib.parse.quote(f"{prefijo}/{clave}", safe="/")}'
        try:
            peticion(url, 'PUT', datos, {'Content-Type': tipo(clave)})
        except Exception as e:
            with cerrojo:
                fallos.append(clave)
            print(f'::error::No se ha podido subir {clave}: {e}', flush=True)
            return
        with cerrojo:
            hechos += 1
            if hechos % 250 == 0 or hechos == len(pendientes):
                print(f'↑ {hechos}/{len(pendientes)}', flush=True)

    with ThreadPoolExecutor(HILOS) as pool:
        list(pool.map(subir, pendientes))
    print(f'Subidos {hechos}, fallidos {len(fallos)}.', flush=True)
    sys.exit(1 if fallos else 0)


if __name__ == '__main__':
    main()
