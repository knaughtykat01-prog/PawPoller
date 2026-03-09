// PawPoller Cloudflare Worker Proxy
// Forwards requests to DA/SF through Cloudflare's IP range
// to bypass datacenter IP blocking.
//
// Paste this into the Cloudflare Workers online editor.
// Set PROXY_SECRET as an environment variable in Worker Settings.
//
// Key feature: the Worker follows redirects internally and carries
// cookies between redirect hops.  This keeps the entire redirect
// chain within one Worker execution (same egress IP), which is
// critical for sites like SoFurry that pin sessions to IPs.

export default {
  async fetch(request, env) {
    // Auth check — reject requests without valid key
    const proxyKey = request.headers.get('x-proxy-key');
    if (!proxyKey || proxyKey !== env.PROXY_SECRET) {
      return new Response('Unauthorized', { status: 403 });
    }

    // Target URL passed via header
    const targetUrl = request.headers.get('x-target-url');
    if (!targetUrl) {
      return new Response('Missing x-target-url header', { status: 400 });
    }

    // Build headers for the real target — strip proxy-specific
    // and Cloudflare-injected headers
    const headers = new Headers();
    const skipHeaders = new Set([
      'x-proxy-key', 'x-target-url', 'host',
      'cf-connecting-ip', 'cf-ray', 'cf-visitor',
      'cf-ipcountry', 'cf-warp-tag-id', 'cdn-loop',
    ]);

    for (const [key, value] of request.headers) {
      if (!skipHeaders.has(key.toLowerCase())) {
        headers.set(key, value);
      }
    }

    // Parse initial cookies from the request
    const cookies = {};
    const cookieHeader = headers.get('cookie');
    if (cookieHeader) {
      cookieHeader.split(';').forEach(c => {
        const eq = c.indexOf('=');
        if (eq > 0) {
          cookies[c.substring(0, eq).trim()] = c.substring(eq + 1).trim();
        }
      });
    }

    // Set the correct Host header for the target domain
    let currentUrl = targetUrl;
    try {
      headers.set('Host', new URL(currentUrl).host);
    } catch {
      return new Response('Invalid target URL', { status: 400 });
    }

    try {
      // Accumulate all Set-Cookie headers across redirect hops
      const allSetCookies = [];

      let resp = await fetch(currentUrl, {
        method: request.method,
        headers: headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        redirect: 'manual',
      });

      // Capture Set-Cookie from this response
      const sc1 = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
      allSetCookies.push(...sc1);
      for (const sc of sc1) {
        const eq = sc.indexOf('=');
        const semi = sc.indexOf(';');
        if (eq > 0) {
          const name = sc.substring(0, eq).trim();
          const value = sc.substring(eq + 1, semi > 0 ? semi : undefined).trim();
          cookies[name] = value;
        }
      }

      // Follow redirects internally, carrying cookies between hops.
      // This keeps everything in one Worker execution (same egress IP).
      let redirectCount = 0;
      while (resp.status >= 300 && resp.status < 400 && redirectCount < 10) {
        const location = resp.headers.get('location');
        if (!location) break;

        // Resolve relative URLs
        const nextUrl = new URL(location, currentUrl).toString();
        currentUrl = nextUrl;

        // Build redirect request headers
        const redirHeaders = new Headers();
        for (const [key, value] of headers) {
          if (key.toLowerCase() !== 'host' && key.toLowerCase() !== 'cookie'
              && key.toLowerCase() !== 'content-type' && key.toLowerCase() !== 'content-length') {
            redirHeaders.set(key, value);
          }
        }
        redirHeaders.set('Host', new URL(nextUrl).host);

        // Inject accumulated cookies
        const cookieStr = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
        if (cookieStr) {
          redirHeaders.set('Cookie', cookieStr);
        }

        resp = await fetch(nextUrl, {
          method: 'GET',  // Redirects always become GET
          headers: redirHeaders,
          redirect: 'manual',
        });

        // Capture Set-Cookie from redirect response
        const scN = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
        allSetCookies.push(...scN);
        for (const sc of scN) {
          const eq = sc.indexOf('=');
          const semi = sc.indexOf(';');
          if (eq > 0) {
            const name = sc.substring(0, eq).trim();
            const value = sc.substring(eq + 1, semi > 0 ? semi : undefined).trim();
            cookies[name] = value;
          }
        }

        redirectCount++;
      }

      // Build final response with all accumulated Set-Cookie headers
      const responseHeaders = new Headers();
      for (const [key, value] of resp.headers) {
        if (key.toLowerCase() !== 'set-cookie') {
          responseHeaders.append(key, value);
        }
      }
      // Add all Set-Cookie headers from all hops
      for (const sc of allSetCookies) {
        responseHeaders.append('Set-Cookie', sc);
      }
      // Tell the caller where the redirect chain ended
      if (redirectCount > 0) {
        responseHeaders.set('X-Final-URL', currentUrl);
      }

      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  }
};
