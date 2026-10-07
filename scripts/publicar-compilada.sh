#!/usr/bin/env bash
# Publica en R2 una web compilada (la carpeta que genera «npm run build», p. ej. dist/).
#
# Solo sube los archivos que han cambiado y borra de R2 los que ya no existen. Para
# saberlo guarda en R2 un manifiesto con la huella SHA-1 de cada archivo publicado.
# La primera vez (sin manifiesto) borra también los archivos del repositorio que se
# hubieran subido antes tal cual (código fuente, borradores…).
#
# Uso: publicar-compilada.sh CLIENTE CARPETA_COMPILADA CARPETA_REPO
set -euo pipefail

CLIENTE="${1:?Falta el cliente}"
ORIGEN="$(cd "${2:?Falta la carpeta compilada}" && pwd)"
REPO="$(cd "${3:?Falta la carpeta del repositorio}" && pwd)"
BUCKET="clientes-web"
PARALELO=8

if [[ ! "$CLIENTE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Cliente no válido: $CLIENTE" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
MANIFIESTO_KEY="$CLIENTE/.multiweb-manifiesto.txt"

# Manifiesto nuevo: «huella␠␠ruta» por línea, ordenado.
(cd "$ORIGEN" && find . -type f -print0 | xargs -0 -r sha1sum | sed 's#  \./#  #' | sort -k2) > "$TMP/nuevo.txt"
cut -c43- "$TMP/nuevo.txt" | sort > "$TMP/claves-nuevas.txt"

if wrangler r2 object get "$BUCKET/$MANIFIESTO_KEY" --file "$TMP/anterior.txt" --remote > /dev/null 2>&1; then
  PRIMERA=false
else
  PRIMERA=true
  : > "$TMP/anterior.txt"
fi
cut -c43- "$TMP/anterior.txt" | sort > "$TMP/claves-anteriores.txt"

# Qué subir: archivos nuevos o con otra huella.
comm -23 <(sort "$TMP/nuevo.txt") <(sort "$TMP/anterior.txt") | cut -c43- > "$TMP/subir.txt"

# Qué borrar: lo que estaba publicado y ya no existe.
comm -23 "$TMP/claves-anteriores.txt" "$TMP/claves-nuevas.txt" > "$TMP/borrar.txt"
if [ "$PRIMERA" = true ]; then
  # Archivos del repositorio que el despliegue antiguo subía tal cual.
  git -C "$REPO" ls-files | sort > "$TMP/fuente.txt"
  comm -23 "$TMP/fuente.txt" "$TMP/claves-nuevas.txt" >> "$TMP/borrar.txt"
  sort -u -o "$TMP/borrar.txt" "$TMP/borrar.txt"
fi

echo "Archivos en la web: $(wc -l < "$TMP/claves-nuevas.txt")"
echo "A subir:            $(wc -l < "$TMP/subir.txt")"
echo "A borrar:           $(wc -l < "$TMP/borrar.txt")"
[ "$PRIMERA" = true ] && echo "(Primera publicación compilada: se limpian los archivos de código subidos antes.)"

tipo() {
  local ext="${1##*.}"
  ext="${ext,,}"
  case "$ext" in
    html|htm)    echo "text/html; charset=utf-8" ;;
    css)         echo "text/css; charset=utf-8" ;;
    js|mjs)      echo "text/javascript; charset=utf-8" ;;
    json|map)    echo "application/json; charset=utf-8" ;;
    webmanifest) echo "application/manifest+json; charset=utf-8" ;;
    xml)         echo "application/xml; charset=utf-8" ;;
    txt|md)      echo "text/plain; charset=utf-8" ;;
    svg)         echo "image/svg+xml" ;;
    png)         echo "image/png" ;;
    jpg|jpeg)    echo "image/jpeg" ;;
    gif)         echo "image/gif" ;;
    webp)        echo "image/webp" ;;
    avif)        echo "image/avif" ;;
    ico)         echo "image/x-icon" ;;
    woff2)       echo "font/woff2" ;;
    woff)        echo "font/woff" ;;
    ttf)         echo "font/ttf" ;;
    otf)         echo "font/otf" ;;
    pdf)         echo "application/pdf" ;;
    mp3)         echo "audio/mpeg" ;;
    m4a)         echo "audio/mp4" ;;
    mp4)         echo "video/mp4" ;;
    webm)        echo "video/webm" ;;
    *)           echo "application/octet-stream" ;;
  esac
}

subir() {
  local clave="$1"
  wrangler r2 object put "$BUCKET/$CLIENTE/$clave" --file "$ORIGEN/$clave" --content-type "$(tipo "$clave")" --remote > /dev/null
  echo "↑ $clave"
}

borrar() {
  local clave="$1"
  wrangler r2 object delete "$BUCKET/$CLIENTE/$clave" --remote > /dev/null 2>&1 || true
  echo "✗ $clave"
}

export -f tipo subir borrar
export BUCKET CLIENTE ORIGEN

# Primero se sube lo nuevo, luego el manifiesto y por último se borra lo viejo,
# para que la web nunca quede a medias.
[ -s "$TMP/subir.txt" ] && xargs -d '\n' -P "$PARALELO" -I{} bash -c 'subir "$1"' _ {} < "$TMP/subir.txt"
wrangler r2 object put "$BUCKET/$MANIFIESTO_KEY" --file "$TMP/nuevo.txt" --content-type "text/plain; charset=utf-8" --remote > /dev/null
[ -s "$TMP/borrar.txt" ] && xargs -d '\n' -P "$PARALELO" -I{} bash -c 'borrar "$1"' _ {} < "$TMP/borrar.txt"

echo "Publicación compilada terminada."
