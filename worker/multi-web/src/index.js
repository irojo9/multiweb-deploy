// Worker que sirve todas las webs de clientes desde R2 (clientes-web/<dominio>/).
//
//   cliente.com            →  clientes-web/cliente.com/
//   www.cliente.com        →  301 a cliente.com
//   cliente.damemiweb.com  →  preview de clientes-web/cliente.<tld>/ (sin indexar)

// Dominios que muestran la web de otra carpeta de R2
// (p. ej. elcontrapeso.com sirve lo que publica el repositorio elcontrapeso.es).
const ALIAS = {
  "elcontrapeso.com": "elcontrapeso.es"
};

// Archivos del repositorio que nunca se sirven aunque estén en R2.
// La misma lista está en scripts/publicar.sh (que ya no los sube).
const NOMBRES_PRIVADOS = new Set([
  "_headers",
  "_redirects",
  "_routes.json",
  "package.json",
  "package-lock.json",
  "wrangler.toml",
  "wrangler.jsonc",
  "wrangler.json",
  "app.config.ts",
  "manus-routes.json"
]);
const CARPETAS_PRIVADAS = new Set(["_build", "node_modules"]);

function esPrivado(ruta) {
  const partes = ruta.toLowerCase().split("/");
  const nombre = partes[partes.length - 1];

  for (const parte of partes) {
    // Archivos y carpetas ocultos (.git, .github, .htaccess, manifiesto…),
    // salvo .well-known, que usan los certificados y verificaciones.
    if (parte.startsWith(".") && parte !== ".well-known") return true;
  }
  for (const carpeta of partes.slice(0, -1)) {
    if (CARPETAS_PRIVADAS.has(carpeta)) return true;
  }
  if (NOMBRES_PRIVADOS.has(nombre)) return true;
  if (nombre.endsWith(".md")) return true;

  return false;
}

// Cuánto tiempo guarda el navegador cada tipo de archivo.
function cacheControl(ruta, tieneVersion) {
  const ext = (ruta.match(/\.([a-z0-9]+)$/i) || [])[1]?.toLowerCase() || "";

  const ESTATICOS = /^(css|js|mjs|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|otf|mp4|webm|mp3|m4a|pdf)$/;

  // styles.css?v=abc123: el contenido no cambia sin cambiar la dirección
  if (tieneVersion && ESTATICOS.test(ext)) {
    return "public, max-age=31536000, immutable";
  }
  if (/^(woff2?|ttf|otf)$/.test(ext)) {
    return "public, max-age=2592000, stale-while-revalidate=31536000";
  }
  if (/^(png|jpe?g|gif|webp|avif|svg|ico|mp4|webm|mp3|m4a|pdf)$/.test(ext)) {
    return "public, max-age=86400, stale-while-revalidate=604800";
  }
  if (/^(css|js|mjs)$/.test(ext)) {
    return "public, max-age=600, stale-while-revalidate=86400";
  }
  // HTML, sitemap, robots…: siempre se pregunta si ha cambiado (responde 304)
  return "public, max-age=0, must-revalidate";
}

function texto(mensaje, status) {
  return new Response(mensaje, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=UTF-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex"
    }
  });
}

// ¿El navegador ya tiene esta versión? (If-None-Match frente al etag de R2)
function etagCoincide(request, etag) {
  const cabecera = request.headers.get("If-None-Match");
  if (!cabecera) return false;
  if (cabecera.trim() === "*") return true;

  const limpio = (valor) => valor.trim().replace(/^W\//, "");
  return cabecera.split(",").some((valor) => limpio(valor) === limpio(etag));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const hostname = url.hostname.toLowerCase();

    // ==========================================
    // DAME MI WEB
    // ==========================================

    if (hostname === "area.damemiweb.com") {
      return env.WEBSALES_CRM.fetch(request);
    }

    if (hostname === "www.damemiweb.com") {
      return Response.redirect("https://damemiweb.com" + url.pathname + url.search, 301);
    }

    if (hostname === "damemiweb.com") {
      return texto("Este dominio no debe pasar por multi-web.", 404);
    }

    // La dirección *.workers.dev del Worker no sirve ninguna web.
    if (hostname.endsWith(".workers.dev")) {
      return texto("No encontrado", 404);
    }

    let carpeta = null;
    let esPreview = false;

    // ==========================================
    // PREVIEWS
    //
    // cliente.damemiweb.com  →  busca  clientes-web/cliente.com/
    // ==========================================

    if (hostname.endsWith(".damemiweb.com")) {
      esPreview = true;
      const subdominio = hostname.slice(0, -".damemiweb.com".length);

      if (!/^[a-z0-9-]+$/.test(subdominio)) {
        return texto("Preview no válida", 400);
      }

      // Preview automática .com
      const posibleCarpeta = `${subdominio}.com`;
      if (await env.BUCKET.head(`${posibleCarpeta}/index.html`)) {
        carpeta = posibleCarpeta;
      }

      // Si no existe .com, buscamos carpetas que empiecen por "subdominio."
      if (!carpeta) {
        const resultado = await env.BUCKET.list({ prefix: `${subdominio}.`, delimiter: "/" });

        for (const prefijo of resultado.delimitedPrefixes || []) {
          if (await env.BUCKET.head(`${prefijo}index.html`)) {
            carpeta = prefijo.slice(0, -1);
            break;
          }
        }
      }

      if (!carpeta) {
        return texto(`Preview no encontrada\n\nSubdominio: ${subdominio}`, 404);
      }
    }

    // ==========================================
    // PRODUCCIÓN
    // ==========================================

    if (!carpeta) {
      const dominio = hostname.replace(/^www\./, "");

      if (!dominio || dominio.includes("..") || !/^[a-z0-9.-]+$/.test(dominio)) {
        return texto("Dominio no válido", 400);
      }

      // www.cliente.com  →  301 a  cliente.com  (una sola dirección para Google)
      if (dominio !== hostname) {
        return Response.redirect("https://" + dominio + url.pathname + url.search, 301);
      }

      carpeta = ALIAS[dominio] || dominio;
    }

    // ==========================================
    // ARCHIVO SOLICITADO
    //
    //   /            →  index.html
    //   /blog/       →  blog/index.html
    //   /css/a.css   →  css/a.css
    //   /contacto    →  contacto.html  (si existe)
    // ==========================================

    let ruta = url.pathname;
    try {
      // Nombres con espacios, eñes o tildes llegan codificados (%20, %C3%B1…)
      ruta = decodeURIComponent(ruta);
    } catch {
      // Dirección mal codificada: se busca tal cual
    }

    if (ruta.endsWith("/")) {
      ruta += "index.html";
    }

    ruta = ruta.replace(/^\/+/, "").replace(/\.\./g, "");

    const tieneExtension = /\.[a-z0-9]+$/i.test(ruta);
    const cabecerasComunes = (headers) => {
      headers.set("X-Content-Type-Options", "nosniff");
      headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
      headers.set("Strict-Transport-Security", "max-age=31536000");
      // Las previews no deben aparecer en Google ni quedarse en caché
      if (esPreview) {
        headers.set("X-Robots-Tag", "noindex, nofollow");
        headers.set("Cache-Control", "no-cache");
      }
      return headers;
    };

    let object = null;
    const key = `${carpeta}/${ruta}`;

    if (!esPrivado(ruta)) {
      object = await env.BUCKET.get(key);

      if (!object && !tieneExtension) {
        object = await env.BUCKET.get(`${key}.html`);
      }
    }

    // ==========================================
    // ARCHIVO NO ENCONTRADO
    // ==========================================

    if (!object) {
      // /blog sin barra final: si existe blog/index.html, redirige a /blog/
      if (!tieneExtension && !esPrivado(ruta)) {
        if (await env.BUCKET.head(`${key}/index.html`)) {
          return Response.redirect(`${url.origin}${url.pathname}/${url.search}`, 301);
        }
      }

      // Página 404 propia de la web, si la tiene
      const pagina404 = await env.BUCKET.get(`${carpeta}/404.html`);

      if (pagina404) {
        const headers = cabecerasComunes(new Headers());
        headers.set("Content-Type", "text/html; charset=UTF-8");
        headers.set("Cache-Control", "no-cache");
        return new Response(pagina404.body, { status: 404, headers });
      }

      return texto("Página no encontrada", 404);
    }

    // ==========================================
    // RESPUESTA
    // ==========================================

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("ETag", object.httpEtag);
    headers.set("Cache-Control", cacheControl(object.key, url.searchParams.has("v")));
    cabecerasComunes(headers);

    if ((headers.get("Content-Type") || "").startsWith("text/html")) {
      // La web solo puede incrustarse en sí misma y en Dame Mi Web (previews del área)
      headers.set(
        "Content-Security-Policy",
        "frame-ancestors 'self' https://damemiweb.com https://*.damemiweb.com"
      );
    }

    // El navegador ya tiene esta versión: 304 sin volver a enviar el archivo
    if (etagCoincide(request, object.httpEtag)) {
      await object.body.cancel();
      headers.delete("Content-Type");
      headers.delete("Content-Security-Policy");
      return new Response(null, { status: 304, headers });
    }

    return new Response(request.method === "HEAD" ? null : object.body, { headers });
  }
};
