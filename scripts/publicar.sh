#!/usr/bin/env bash
# Publica una web en R2: la carpeta que genera «npm run build» (p. ej. dist/) o,
# en las webs sin compilación, el propio repositorio.
#
# Solo sube los archivos que han cambiado y borra de R2 los que ya no existen. Para
# saberlo guarda en R2 un manifiesto con la huella SHA-1 de cada archivo publicado.
# La primera vez (sin manifiesto) borra también los archivos del repositorio que se
# hubieran subido antes y ya no se publican (documentación, código fuente…).
#
# Nunca se publican: archivos y carpetas ocultos (salvo .well-known), *.md, _build/,
# node_modules/ ni los archivos de configuración de PRIVADOS. El Worker multi-web
# tiene la misma lista (esPrivado) y tampoco los sirve.
#
# Uso: publicar.sh CLIENTE CARPETA_A_PUBLICAR CARPETA_REPO
set -euo pipefail

CLIENTE="${1:?Falta el cliente}"
ORIGEN="$(cd "${2:?Falta la carpeta compilada}" && pwd)"
REPO="$(cd "${3:?Falta la carpeta del repositorio}" && pwd)"
BUCKET="clientes-web"
PARALELO=8
# Se aplica a las líneas «huella(40)␠␠ruta» del manifiesto: la ruta empieza en la columna 43.
INI='(^.{42}|/)'
PRIVADOS="${INI}\\.(?!well-known(/|\$))|${INI}(_build|node_modules)/|${INI}(_headers|_redirects|_routes\\.json|package\\.json|package-lock\\.json|wrangler\\.toml|wrangler\\.jsonc|wrangler\\.json|app\\.config\\.ts|manus-routes\\.json)\$|\\.md\$"

if [[ ! "$CLIENTE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Cliente no válido: $CLIENTE" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
MANIFIESTO_KEY="$CLIENTE/.multiweb-manifiesto.txt"

# Manifiesto nuevo: «huella␠␠ruta» por línea, ordenado.
(cd "$ORIGEN" && find . -type f -not -path './.git/*' -print0 | xargs -0 -r sha1sum | sed 's#  \./#  #' | { grep -Piv "$PRIVADOS" || true; } | sort -k2) > "$TMP/nuevo.txt"

if [ ! -s "$TMP/nuevo.txt" ]; then
  echo "::error::La carpeta a publicar está vacía: no se publica nada." >&2
  exit 1
fi
grep -q '^.\{42\}index\.html$' "$TMP/nuevo.txt" || echo "::warning::$CLIENTE: no hay index.html en la raíz de la web."

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
  git -C "$REPO" -c core.quotepath=off ls-files | sort > "$TMP/fuente.txt"
  comm -23 "$TMP/fuente.txt" "$TMP/claves-nuevas.txt" >> "$TMP/borrar.txt"
  sort -u -o "$TMP/borrar.txt" "$TMP/borrar.txt"
fi

echo "Archivos en la web: $(wc -l < "$TMP/claves-nuevas.txt")"
echo "A subir:            $(wc -l < "$TMP/subir.txt")"
echo "A borrar:           $(wc -l < "$TMP/borrar.txt")"
[ "$PRIMERA" = true ] && echo "(Primera publicación con manifiesto: se limpian los archivos que ya no se publican.)"

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
  local intento
  for intento in 1 2 3; do
    if wrangler r2 object put "$BUCKET/$CLIENTE/$clave" --file "$ORIGEN/$clave" --content-type "$(tipo "$clave")" --remote > /dev/null 2>&1; then
      echo "↑ $clave"
      return 0
    fi
    sleep $((intento * 3))
  done
  echo "::error::No se ha podido subir $clave" >&2
  return 1
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
# La subida va por la API (r2-subir.py): mucho más rápida que un wrangler por archivo
# y reanudable (se salta lo que ya está igual en R2). Si no hay Python, como antes.
# Lo editado en las últimas horas (artículos e imágenes) se sube lo primero.
if git -C "$REPO" rev-parse --git-dir > /dev/null 2>&1; then
  git -C "$REPO" -c core.quotepath=off log --since="6 hours ago" --name-only --pretty=format: 2>/dev/null \
    | { grep -E '^(content/|.*/uploads/)' || true; } | sort -u | while IFS= read -r ruta; do
      nombre="${ruta##*/}"; nombre="${nombre%.*}"
      case "$nombre" in index|README|readme|_index|"") ;; *) echo "$nombre" ;; esac
    done | sort -u | head -n 300 > "$TMP/prioridad.txt" || true
  export PRIORIDAD="$TMP/prioridad.txt"
fi

if [ -s "$TMP/subir.txt" ]; then
  if command -v python3 > /dev/null && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
    python3 "$(dirname "$0")/r2-subir.py" "$BUCKET" "$CLIENTE" "$ORIGEN" "$TMP/subir.txt"
  else
    xargs -d '\n' -P "$PARALELO" -I{} bash -c 'subir "$1"' _ {} < "$TMP/subir.txt"
  fi
fi
wrangler r2 object put "$BUCKET/$MANIFIESTO_KEY" --file "$TMP/nuevo.txt" --content-type "text/plain; charset=utf-8" --remote > /dev/null
[ -s "$TMP/borrar.txt" ] && xargs -d '\n' -P "$PARALELO" -I{} bash -c 'borrar "$1"' _ {} < "$TMP/borrar.txt"

echo "Publicación terminada."
