# multiweb-deploy

Sistema de publicación de las webs de clientes de Dame Mi Web.

```
push al repo del cliente → Worker multiweb-github (webhook) → workflow «MultiWeb Deploy»
   → R2 clientes-web/<dominio>/ → Worker multi-web (sirve todas las webs)
```

## Alta de una web nueva

1. Crear un repositorio **privado** llamado exactamente como el dominio (`cliente.com`).
2. Copiar dentro el contenido de `plantilla/` y sustituir los marcadores `{{…}}`
   (el estándar completo está en `plantilla/CLAUDE.md`).
3. Push a `main`. El despliegue publica la web, enlaza `cliente.com` y `www.cliente.com`
   al Worker (si el dominio está en la cuenta de Cloudflare) y deja la preview en
   `https://cliente.damemiweb.com` (sin indexar).

## Qué hace cada pieza

| Pieza | Qué hace |
| --- | --- |
| `.github/workflows/deploy.yml` | Publica la web de un cliente. Se lanza sola con cada push o a mano desde Actions. |
| `scripts/comprobar-web.py` | Revisión previa: avisa de lo que le falta a la web (no detiene la publicación). |
| `scripts/publicar.sh` | Sube a R2 solo lo que ha cambiado y borra lo que ya no existe. |
| `scripts/enlazar-dominios.py` | Enlaza los dominios del cliente al Worker. |
| `worker/multi-web/` | Worker que sirve las webs: caché, 304, cabeceras de seguridad, previews, 404. |
| `plantilla/` | Punto de partida de una web nueva y estándar de calidad. |

Los avisos de la revisión aparecen en el resumen de cada ejecución (pestaña Actions).

## Caché

HTML: siempre se revalida (304). CSS y JS: 10 minutos (un año con `?v=N`).
Imágenes: 1 día. Fuentes: 30 días. Las previews nunca se guardan en caché.

Tras cambiar `worker/multi-web/`, lanzar el workflow «Desplegar multi-web».
