// PawPoller Cloudflare Worker Proxy
// Forwards requests to DA/SF through Cloudflare's IP range
// to bypass datacenter IP blocking.
//
// Paste this into the Cloudflare Workers online editor.
// Set PROXY_SECRET as an environment variable in Worker Settings.
//
// Key features:
//   1. Follows redirects internally with cookie forwarding (same egress IP)
//   2. Supports x-proxy-chain: JSON array of follow-up URLs to fetch
//      after the main request, all within one Worker execution.
//      This is critical for SoFurry which pins sessions to IPs.

export default {
  async fetch(request, env) {
    // Auth check
    const proxyKey = request.headers.get('x-proxy-key');
    if (!proxyKey || proxyKey !== env.PROXY_SECRET) {
      return new Response('Unauthorized', { status: 403 });
    }

    const targetUrl = request.headers.get('x-target-url');
    if (!targetUrl) {
      return new Response('Missing x-target-url header', { status: 400 });
    }

    // Optional: chain of follow-up URLs to fetch after the main request
    const chainHeader = request.headers.get('x-proxy-chain');
    let chainUrls = [];
    if (chainHeader) {
      try { chainUrls = JSON.parse(chainHeader); } catch {}
    }

    // Build headers — strip proxy-specific and CF-injected headers
    const headers = new Headers();
    const skipHeaders = new Set([
      'x-proxy-key', 'x-target-url', 'x-proxy-chain', 'host',
      'cf-connecting-ip', 'cf-ray', 'cf-visitor',
      'cf-ipcountry', 'cf-warp-tag-id', 'cdn-loop',
    ]);
    for (const [key, value] of request.headers) {
      if (!skipHeaders.has(key.toLowerCase())) {
        headers.set(key, value);
      }
    }

    // Parse initial cookies
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

    try {
      headers.set('Host', new URL(targetUrl).host);
    } catch {
      return new Response('Invalid target URL', { status: 400 });
    }

    // Helper: capture Set-Cookie headers into our cookie jar
    const allSetCookies = [];
    function captureCookies(resp) {
      const scs = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
      allSetCookies.push(...scs);
      for (const sc of scs) {
        const eq = sc.indexOf('=');
        const semi = sc.indexOf(';');
        if (eq > 0) {
          cookies[sc.substring(0, eq).trim()] =
            sc.substring(eq + 1, semi > 0 ? semi : undefined).trim();
        }
      }
    }

    // Helper: build headers for a follow-up request
    function buildHeaders(url) {
      const h = new Headers();
      for (const [key, value] of headers) {
        if (!['host', 'cookie', 'content-type', 'content-length'].includes(key.toLowerCase())) {
          h.set(key, value);
        }
      }
      h.set('Host', new URL(url).host);
      const cookieStr = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
      if (cookieStr) h.set('Cookie', cookieStr);
      return h;
    }

    // Helper: fetch with internal redirect following + cookie forwarding
    async function fetchWithRedirects(url, method, body) {
      const reqHeaders = method === 'GET' ? buildHeaders(url) : headers;
      if (method !== 'GET') reqHeaders.set('Host', new URL(url).host);

      let resp = await fetch(url, {
        method,
        headers: reqHeaders,
        body: ['GET', 'HEAD'].includes(method) ? undefined : body,
        redirect: 'manual',
      });
      captureCookies(resp);

      let finalUrl = url;
      let redirects = 0;
      while (resp.status >= 300 && resp.status < 400 && redirects < 10) {
        const location = resp.headers.get('location');
        if (!location) break;
        finalUrl = new URL(location, finalUrl).toString();

        resp = await fetch(finalUrl, {
          method: 'GET',
          headers: buildHeaders(finalUrl),
          redirect: 'manual',
        });
        captureCookies(resp);
        redirects++;
      }

      return { resp, finalUrl, redirects };
    }

    try {
      // Step 1: Execute the main request
      const { resp: mainResp, finalUrl, redirects } =
        await fetchWithRedirects(targetUrl, request.method, request.body);

      // Step 2: Execute chain URLs (if any) within the same invocation
      let lastResp = mainResp;
      let lastUrl = finalUrl;
      for (const chainUrl of chainUrls) {
        const { resp, finalUrl: fUrl } = await fetchWithRedirects(chainUrl, 'GET', null);
        lastResp = resp;
        lastUrl = fUrl;
      }

      // Build final response with all accumulated Set-Cookie headers
      const responseHeaders = new Headers();
      for (const [key, value] of lastResp.headers) {
        if (key.toLowerCase() !== 'set-cookie') {
          responseHeaders.append(key, value);
        }
      }
      for (const sc of allSetCookies) {
        responseHeaders.append('Set-Cookie', sc);
      }
      if (redirects > 0 || chainUrls.length > 0) {
        responseHeaders.set('X-Final-URL', lastUrl);
      }
      // Return accumulated cookies as a header so the client can store them
      const cookieStr = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
      if (cookieStr) {
        responseHeaders.set('X-Session-Cookies', cookieStr);
      }

      return new Response(lastResp.body, {
        status: lastResp.status,
        statusText: lastResp.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  }
};
