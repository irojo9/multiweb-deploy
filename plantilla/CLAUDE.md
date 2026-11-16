# Estándar de las webs de Dame Mi Web

Este repositorio es la web de un cliente. Se publica sola al hacer push a `main`
(sistema `irojo9/multiweb-deploy`: GitHub → R2 → Worker `multi-web`). No hay que
configurar nada en Cloudflare a mano.

## Reglas del repositorio

- **El nombre del repositorio es el dominio exacto**: `cliente.com` (sin `www`, sin
  guiones al final, sin mayúsculas). De él salen la carpeta de R2, el dominio enlazado
  y la preview `cliente.damemiweb.com`.
- Repositorio **privado**.
- Los cambios se hacen con commits (Claude Code), no con «Add files via upload».
- No se publican: `*.md`, archivos ocultos, `_build/`, `node_modules/`, `package.json`,
  `_headers`, `.htaccess`. Las cabeceras y la caché las pone el Worker: no crear `_headers`.
- Si la web necesita compilarse: `package.json` con script `build` **y** `package-lock.json`.
  Se publica `dist/` (u otra carpeta con `"multiweb": { "salida": "carpeta" }`).

## Qué debe tener toda web antes de publicarse

1. `index.html` con `<html lang="es-ES">`, `<title>` (servicio + ciudad + marca),
   meta descripción, `<link rel="canonical">` con el dominio real y Open Graph completo
   (`og:image` de 1200×630 alojada en la web).
2. Datos estructurados JSON-LD del negocio (`Plumber`, `Locksmith`, `GeneralContractor`,
   `LocalBusiness`…) con nombre, teléfono, zona (`areaServed`) y horario.
3. Un solo `<h1>`. Enlace `tel:` visible arriba y, si el cliente lo usa, WhatsApp (`wa.me`).
4. `robots.txt` y `sitemap.xml` con el dominio real, y `404.html` con botón de llamada.
5. `aviso-legal/` y `privacidad/` enlazados en el pie, con los datos reales del titular
   (nombre o razón social, NIF, domicilio, correo). Pedírselos al cliente.
6. Nada de terceros: fuentes, iconos y librerías alojados en la propia web
   (sin Google Fonts, jsDelivr, unpkg, Tailwind CDN ni manuscdn).
7. Imágenes en AVIF/WebP con `srcset`, `width`/`height` y `loading="lazy"` (salvo la
   principal, que lleva `fetchpriority="high"`). Ninguna por encima de 400 KB.
   Las fotos del cliente se renombran (`reforma-bano-madrid.webp`, no `1000028121.jpg`).
8. CSS y JS enlazados con versión para que la caché no moleste: `styles.css?v=3`.
   Al cambiar el archivo, subir el número.
9. Ningún marcador sin sustituir: buscar `{{` y `DOMINIO-DEFINITIVO` antes del push.

El despliegue revisa todo esto y deja los avisos en el resumen de la ejecución
(pestaña Actions de `multiweb-deploy`). Una web bien hecha sale con cero avisos.

## Marcadores de esta plantilla

`{{DOMINIO}}` `{{NEGOCIO}}` `{{SERVICIO}}` `{{CIUDAD}}` `{{TELEFONO}}` (formato visible,
`600 000 000`) `{{TELEFONO_E164}}` (`+34600000000`) `{{DESCRIPCION}}` `{{TIPO_SCHEMA}}`
`{{TITULAR}}` `{{NIF}}` `{{DOMICILIO}}` `{{EMAIL}}` `{{FECHA}}` (AAAA-MM-DD)
