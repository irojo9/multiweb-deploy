export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const hostname = url.hostname.toLowerCase();

    // ==========================================
    // AREA
    // ==========================================

    if (hostname === "area.damemiweb.com") {
      return env.WEBSALES_CRM.fetch(request);
    }

    // ==========================================
    // WWW DAME MI WEB
    // ==========================================

    if (hostname === "www.damemiweb.com") {
      const destino = "https://damemiweb.com" + url.pathname + url.search;
      return Response.redirect(destino, 301);
    }

    // ==========================================
    // DOMINIO PRINCIPAL
    // ==========================================

    if (hostname === "damemiweb.com") {
      return new Response("Este dominio no debe pasar por multi-web.", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=UTF-8" }
      });
    }

    let carpeta = null;

    // ==========================================
    // PREVIEWS
    //
    // cliente.damemiweb.com  →  busca  clientes-web/cliente.com/
    // ==========================================

    if (hostname.endsWith(".damemiweb.com") && hostname !== "www.damemiweb.com") {
      const subdominio = hostname.slice(0, -".damemiweb.com".length);

      // Seguridad
      if (!/^[a-z0-9-]+$/.test(subdominio)) {
        return new Response("Preview no válida", {
          status: 400,
          headers: { "Content-Type": "text/plain; charset=UTF-8" }
        });
      }

      // Preview automática .com
      const posibleCarpeta = `${subdominio}.com`;
      const indexPreview = await env.BUCKET.head(`${posibleCarpeta}/index.html`);

      if (indexPreview) {
        carpeta = posibleCarpeta;
      }

      // Si no existe .com, buscamos carpetas que empiecen por "subdominio."
      if (!carpeta) {
        const resultado = await env.BUCKET.list({
          prefix: `${subdominio}.`,
          limit: 100
        });

        for (const objeto of resultado.objects) {
          const partes = objeto.key.split("/");

          if (
            partes.length >= 2 &&
            partes[0].startsWith(`${subdominio}.`) &&
            partes[1] === "index.html"
          ) {
            carpeta = partes[0];
            break;
          }
        }
      }

      // No encontrada
      if (!carpeta) {
        return new Response(
          `Preview no encontrada

Subdominio: ${subdominio}

Se buscó:
${subdominio}.com/index.html`,
          {
            status: 404,
            headers: { "Content-Type": "text/plain; charset=UTF-8" }
          }
        );
      }
    }

    // ==========================================
    // WORKERS.DEV
    // ==========================================

    if (hostname.endsWith(".workers.dev")) {
      carpeta = "construccionesyreformasraycosasa.com";
    }

    // ==========================================
    // PRODUCCIÓN
    // ==========================================

    if (!carpeta) {
      const dominio = hostname.replace(/^www\./, "");

      if (
        !dominio ||
        dominio.includes("..") ||
        dominio.includes("/") ||
        dominio.includes("\\") ||
        !/^[a-z0-9.-]+$/.test(dominio)
      ) {
        return new Response("Dominio no válido", { status: 400 });
      }

      // www.cliente.com  →  301 a  cliente.com  (una sola dirección para
      // Google; el despliegue enlaza al Worker los dos nombres)
      if (dominio !== hostname) {
        const destino = "https://" + dominio + url.pathname + url.search;
        return Response.redirect(destino, 301);
      }

      // Dominios que muestran la web de otra carpeta de R2
      // (p. ej. elcontrapeso.com sirve lo que publica el repositorio elcontrapeso.es)
      const ALIAS = { "elcontrapeso.com": "elcontrapeso.es" };
      carpeta = ALIAS[dominio] || dominio;
    }

    // ==========================================
    // ARCHIVO SOLICITADO
    //
    //   /            →  index.html
    //   /blog/       →  blog/index.html
    //   /css/a.css   →  css/a.css
    // ==========================================

    let ruta = url.pathname;

    if (ruta.endsWith("/")) {
      ruta += "index.html";
    }

    ruta = ruta
      .replace(/^\/+/, "")
      .replace(/\.\./g, "");

    const key = `${carpeta}/${ruta}`;

    // ==========================================
    // LOG
    // ==========================================

    console.log(`Dominio: ${hostname}`);
    console.log(`Carpeta R2: ${carpeta}`);
    console.log(`Archivo: ${ruta}`);
    console.log(`R2 Key: ${key}`);

    // ==========================================
    // BUSCAR ARCHIVO
    // ==========================================

    const object = await env.BUCKET.get(key);

    // ==========================================
    // ARCHIVO NO ENCONTRADO
    // ==========================================

    if (!object) {
      // /blog sin barra final: si existe blog/index.html, redirige a /blog/
      if (!/\.[a-z0-9]+$/i.test(ruta)) {
        const carpetaIndex = await env.BUCKET.head(`${key}/index.html`);

        if (carpetaIndex) {
          return Response.redirect(`${url.origin}${url.pathname}/${url.search}`, 301);
        }
      }

      // Página 404 propia de la web, si la tiene
      const pagina404 = await env.BUCKET.get(`${carpeta}/404.html`);

      if (pagina404) {
        return new Response(pagina404.body, {
          status: 404,
          headers: { "Content-Type": "text/html; charset=UTF-8" }
        });
      }

      return new Response(
        `Archivo no encontrado

Dominio: ${hostname}
Carpeta: ${carpeta}
Archivo: ${ruta}
R2 Key: ${key}`,
        {
          status: 404,
          headers: { "Content-Type": "text/plain; charset=UTF-8" }
        }
      );
    }

    // ==========================================
    // RESPUESTA
    // ==========================================

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);

    return new Response(object.body, { headers });
  }
};
