#!/usr/bin/env python3
"""Enlaza al Worker multi-web los dominios de un cliente (con y sin www).

Los dominios salen de clientes.json (la entrada cuyo «repositorio» es
irojo9/CLIENTE) o, si no hay entrada, del propio nombre del repositorio, que
coincide con el dominio: CLIENTE y www.CLIENTE.

Cada dominio se enlaza como Custom Domain del Worker: Cloudflare crea el
registro DNS y el certificado. Si ya tiene un registro DNS (lo habitual en
www, un CNAME al dominio), se enlaza con una ruta hostname/* en su lugar. Se
salta el dominio si ya llega al Worker (por Custom Domain o por una ruta) y
nunca se borra ni sobrescribe nada: si algo lo impide (otro Worker, zona fuera
de la cuenta…) solo avisa. Nunca hace fallar el despliegue.

Con --todos, en vez de un cliente, enlaza el www de todos los dominios de la
cuenta que ya llegan al Worker (lo lanza cada hora «Enlazar dominios www»).

Uso: enlazar-dominios.py CLIENTE [clientes.json]
     enlazar-dominios.py --todos
Entorno: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, WORKER (multi-web)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CUENTA = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
WORKER = os.environ.get("WORKER") or "multi-web"
DOMINIO_VALIDO = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

PERMISOS = (
    "El token CF_API_TOKEN necesita: Zone › Zone › Read y "
    "Zone › Workers Routes › Edit en todas las zonas, y "
    "Account › Workers Scripts › Edit."
)


class ErrorApi(Exception):
    def __init__(self, estado, errores):
        self.estado = estado
        self.errores = errores
        super().__init__("; ".join(f"{e.get('code')}: {e.get('message')}" for e in errores) or f"HTTP {estado}")


def api(metodo, ruta, consulta=None, cuerpo=None):
    url = API + ruta
    if consulta:
        url += "?" + urllib.parse.urlencode(consulta)
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return json.load(respuesta)["result"]
    except urllib.error.HTTPError as e:
        try:
            errores = json.load(e).get("errors") or []
        except Exception:
            errores = []
        raise ErrorApi(e.code, errores) from None


def aviso(mensaje):
    print(f"::warning::{mensaje}")


def dominios_del_cliente(cliente, ruta_clientes):
    try:
        with open(ruta_clientes, encoding="utf-8") as f:
            clientes = json.load(f)
    except (OSError, ValueError):
        clientes = {}
    for datos in clientes.values():
        if datos.get("repositorio", "").lower() == f"irojo9/{cliente}".lower() and datos.get("dominios"):
            return [d.strip().lower() for d in datos["dominios"]]
    dominio = cliente.lower().removeprefix("www.")
    if not DOMINIO_VALIDO.match(dominio):
        return []
    return [dominio, f"www.{dominio}"]


zonas = {}


def zona_de(hostname):
    """Zona de la cuenta que contiene el hostname (la más específica)."""
    partes = hostname.split(".")
    for i in range(len(partes) - 1):
        nombre = ".".join(partes[i:])
        if nombre not in zonas:
            resultado = api("GET", "/zones", {"name": nombre, "account.id": CUENTA})
            zonas[nombre] = resultado[0]["id"] if resultado else None
        if zonas[nombre]:
            return zonas[nombre]
    return None


def ruta_cubre(patron, hostname):
    host = patron.split("/", 1)[0].lower()
    if host.startswith("*"):
        return hostname.endswith(host[1:])
    return host == hostname


def enlazar(hostname, zona=None):
    zona = zona or zona_de(hostname)
    if not zona:
        aviso(
            f"{hostname}: el token no ve su zona. O el dominio no está en la cuenta de Cloudflare, "
            f"o al token le falta Zone › Zone › Read (Cloudflare no da error, solo no la muestra)."
        )
        return

    existentes = api("GET", f"/accounts/{CUENTA}/workers/domains", {"hostname": hostname})
    for d in existentes:
        if d.get("hostname") == hostname:
            if d.get("service") == WORKER:
                print(f"✓ {hostname}: ya enlazado.")
            else:
                aviso(f"{hostname}: enlazado a otro Worker ({d.get('service')}). No se toca.")
            return

    for r in api("GET", f"/zones/{zona}/workers/routes"):
        if ruta_cubre(r.get("pattern", ""), hostname):
            if r.get("script") == WORKER:
                print(f"✓ {hostname}: ya llega al Worker por la ruta {r['pattern']}.")
            else:
                aviso(f"{hostname}: la ruta {r['pattern']} lo envía a {r.get('script') or 'ningún Worker'}. No se toca.")
            return

    try:
        api("PUT", f"/accounts/{CUENTA}/workers/domains", cuerpo={
            "hostname": hostname,
            "service": WORKER,
            "zone_id": zona,
            "environment": "production",
        })
        print(f"+ {hostname}: enlazado al Worker {WORKER}.")
        return
    except ErrorApi as e:
        error_dominio = e

    # Lo normal es que ya exista un registro DNS (p. ej. CNAME www → dominio.com)
    # y Cloudflare no deje crear el Custom Domain encima. Sin borrar el registro,
    # una ruta hostname/* envía igualmente las peticiones al Worker.
    try:
        api("POST", f"/zones/{zona}/workers/routes", cuerpo={"pattern": f"{hostname}/*", "script": WORKER})
        print(f"+ {hostname}: enlazado al Worker {WORKER} con la ruta {hostname}/* (ya tenía registro DNS).")
        print(f"  Su registro DNS debe estar «Redirigido mediante proxy» (nube naranja).")
    except ErrorApi as e:
        aviso(f"{hostname}: no se ha podido enlazar (dominio: {error_dominio}; ruta: {e}).")


def dominios_del_worker():
    """{dominio: zona} de cada dominio raíz que ya llega al Worker (Custom Domain o ruta)."""
    dominios = {}
    for d in api("GET", f"/accounts/{CUENTA}/workers/domains", {"service": WORKER}):
        if d.get("service") == WORKER and d.get("hostname") == d.get("zone_name"):
            dominios[d["hostname"]] = d["zone_id"]

    # Dominios servidos por una ruta «dominio.com/*» en vez de Custom Domain.
    pagina = 1
    while True:
        zonas_pagina = api("GET", "/zones", {"account.id": CUENTA, "per_page": 50, "page": pagina})
        for z in zonas_pagina:
            if z["name"] in dominios:
                continue
            for r in api("GET", f"/zones/{z['id']}/workers/routes"):
                if r.get("script") == WORKER and r.get("pattern", "").split("/", 1)[0].lower() == z["name"]:
                    dominios[z["name"]] = z["id"]
                    break
        if len(zonas_pagina) < 50:
            break
        pagina += 1
    return dominios


def enlazar_todos(hostnames):
    """hostnames: lista de (hostname, zona o None)."""
    for hostname, zona in hostnames:
        try:
            enlazar(hostname, zona)
        except ErrorApi as e:
            if e.estado in (401, 403):
                aviso(f"{hostname}: el token no tiene permiso ({e}). {PERMISOS}")
                return
            aviso(f"{hostname}: error de la API de Cloudflare ({e}).")
        except Exception as e:  # red, respuesta inesperada…
            aviso(f"{hostname}: {e}")


def main():
    cliente = sys.argv[1] if len(sys.argv) > 1 else ""
    ruta_clientes = sys.argv[2] if len(sys.argv) > 2 else "clientes.json"
    if not TOKEN or not CUENTA:
        aviso("Faltan CLOUDFLARE_API_TOKEN o CLOUDFLARE_ACCOUNT_ID: no se enlazan dominios.")
        return

    # --todos: el www de cada dominio que ya llega al Worker, sea de quien sea.
    if cliente == "--todos":
        try:
            dominios = dominios_del_worker()
        except ErrorApi as e:
            aviso(f"No se han podido listar los dominios del Worker ({e}). {PERMISOS}")
            return
        print(f"Dominios enlazados a {WORKER}: {len(dominios)}")
        enlazar_todos([(f"www.{d}", z) for d, z in sorted(dominios.items())])
        return

    dominios = [d for d in dominios_del_cliente(cliente, ruta_clientes) if DOMINIO_VALIDO.match(d)]
    if not dominios:
        print(f"«{cliente}» no es un dominio: no se enlaza nada.")
        return

    print(f"Dominios de {cliente}: {', '.join(dominios)}")
    enlazar_todos([(d, None) for d in dominios])


if __name__ == "__main__":
    main()
