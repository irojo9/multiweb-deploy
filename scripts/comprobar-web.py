#!/usr/bin/env python3
"""Revisa una web antes de publicarla y avisa de lo que le falta.

Nunca detiene el despliegue: solo deja avisos en el registro y en el resumen
de la ejecución de GitHub Actions, para corregirlos en el repositorio del cliente.

Comprueba: página de inicio, título, descripción, canonical, datos estructurados,
enlace de teléfono o WhatsApp, páginas legales, robots.txt, sitemap.xml, 404.html,
textos de relleno sin sustituir, recursos de terceros e imágenes pesadas.

Uso: comprobar-web.py CLIENTE CARPETA_A_PUBLICAR
"""
import os
import re
import sys

IMAGEN_PESADA = 400 * 1024  # bytes
RELLENOS = [
    ("DOMINIO-DEFINITIVO", "queda el marcador DOMINIO-DEFINITIVO sin sustituir por el dominio real"),
    ("manuscdn.com", "enlaza recursos de manuscdn.com (exportación de Manus): hay que alojarlos en la web"),
    ("lorem ipsum", "queda texto de relleno «lorem ipsum»"),
    ("{{", "quedan marcadores {{…}} de la plantilla sin sustituir"),
    ("PEGA_AQUI", "queda un marcador PEGA_AQUI sin rellenar"),
    ("tudominio.com", "queda el dominio de ejemplo tudominio.com"),
    ("example.com", "queda el dominio de ejemplo example.com"),
]
TERCEROS = ["cdn.tailwindcss.com", "cdn.jsdelivr.net", "unpkg.com", "fonts.googleapis.com"]
OCULTOS = re.compile(r"(^|/)(\.[^/]+|_build|node_modules)(/|$)")


def leer(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def main():
    cliente = sys.argv[1] if len(sys.argv) > 1 else ""
    carpeta = sys.argv[2] if len(sys.argv) > 2 else "."
    avisos = []

    archivos = []
    for raiz, carpetas, nombres in os.walk(carpeta):
        carpetas[:] = [c for c in carpetas if not c.startswith(".") and c not in ("_build", "node_modules")]
        for nombre in nombres:
            relativa = os.path.relpath(os.path.join(raiz, nombre), carpeta).replace(os.sep, "/")
            if not OCULTOS.search(relativa):
                archivos.append(relativa)

    existe = lambda nombre: nombre in archivos
    inicio = leer(os.path.join(carpeta, "index.html"))

    if not inicio:
        avisos.append("No hay index.html en la raíz: la web no tiene página de inicio.")
    else:
        hay = lambda patron: re.search(patron, inicio, re.I | re.S) is not None
        if not hay(r"<title>\s*\S"):
            avisos.append("La página de inicio no tiene <title>.")
        if not hay(r"<meta[^>]+name=[\"']description[\"']"):
            avisos.append("La página de inicio no tiene meta descripción.")
        if not hay(r"<link[^>]+rel=[\"']canonical[\"']"):
            avisos.append("La página de inicio no tiene <link rel=\"canonical\">.")
        if not hay(r"<meta[^>]+property=[\"']og:image[\"']"):
            avisos.append("Falta la imagen para redes (og:image).")
        if not hay(r"application/ld\+json"):
            avisos.append("Faltan datos estructurados (JSON-LD de negocio local).")
        if not hay(r"href=[\"']tel:") and not hay(r"wa\.me|api\.whatsapp\.com"):
            avisos.append("No hay enlace de llamada (tel:) ni de WhatsApp.")
        if not hay(r"aviso[-_ ]?legal"):
            avisos.append("No se enlaza un aviso legal (obligatorio identificar al titular de la web).")
        if not hay(r"privacidad"):
            avisos.append("No se enlaza una política de privacidad.")
        if not hay(r"<html[^>]+lang="):
            avisos.append("Falta el idioma en <html lang=\"es\">.")

    for nombre, falta in [
        ("robots.txt", "Falta robots.txt."),
        ("sitemap.xml", "Falta sitemap.xml."),
        ("404.html", "Falta 404.html (página de error propia)."),
    ]:
        if not existe(nombre):
            avisos.append(falta)

    # Textos de relleno y recursos de terceros en HTML, CSS, JS, XML y TXT
    encontrados = {}
    for relativa in archivos:
        if not re.search(r"\.(html?|css|js|xml|txt|json|webmanifest)$", relativa, re.I):
            continue
        contenido = leer(os.path.join(carpeta, relativa)).lower()
        for marca, mensaje in RELLENOS:
            # «{{» es normal en JavaScript y CSS compilados: solo cuenta en páginas y textos
            if marca == "{{" and not re.search(r"\.(html?|xml|txt)$", relativa, re.I):
                continue
            if marca.lower() in contenido:
                encontrados.setdefault(mensaje, []).append(relativa)
        if relativa.lower().endswith((".html", ".htm")):
            for host in TERCEROS:
                if host in contenido:
                    encontrados.setdefault(
                        f"carga recursos de {host}: mejor alojarlos en la propia web (velocidad y privacidad)", []
                    ).append(relativa)
    for mensaje, donde in encontrados.items():
        lista = ", ".join(donde[:5]) + ("…" if len(donde) > 5 else "")
        avisos.append(f"{lista}: {mensaje}.")

    # Imágenes pesadas
    pesadas = []
    for relativa in archivos:
        if re.search(r"\.(jpe?g|png|gif|webp|avif)$", relativa, re.I):
            try:
                peso = os.path.getsize(os.path.join(carpeta, relativa))
            except OSError:
                continue
            if peso > IMAGEN_PESADA:
                pesadas.append((peso, relativa))
    if pesadas:
        pesadas.sort(reverse=True)
        lista = ", ".join(f"{r} ({p // 1024} KB)" for p, r in pesadas[:5])
        resto = f" y {len(pesadas) - 5} más" if len(pesadas) > 5 else ""
        avisos.append(f"Imágenes de más de {IMAGEN_PESADA // 1024} KB sin optimizar: {lista}{resto}.")

    # Salida
    if avisos:
        print(f"Revisión de {cliente}: {len(avisos)} aviso(s).")
        for a in avisos:
            print(f"::warning title={cliente}::{a}")
    else:
        print(f"Revisión de {cliente}: todo correcto.")

    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"## Revisión de {cliente}\n\n")
            if avisos:
                f.write("\n".join(f"- {a}" for a in avisos) + "\n")
            else:
                f.write("Todo correcto.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # la revisión nunca debe impedir publicar
        print(f"::warning::No se ha podido revisar la web: {e}")
