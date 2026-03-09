// PawPoller Cloudflare Worker Proxy
// Forwards requests to DA/SF through Cloudflare's IP range
// to bypass datacenter IP blocking.
//
// Paste this into the Cloudflare Workers online editor.
// Set PROXY_SECRET as an environment variable in Worker Settings.

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

    // Set the correct Host header for the target domain
    try {
      headers.set('Host', new URL(targetUrl).host);
    } catch {
      return new Response('Invalid target URL', { status: 400 });
    }

    try {
      const resp = await fetch(targetUrl, {
        method: request.method,
        headers: headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        redirect: 'manual',  // Don't follow redirects — let caller handle
      });

      // Pass response back as-is
      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: resp.headers,
      });
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  }
};
