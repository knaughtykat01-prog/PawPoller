// PawPoller Cloudflare Worker Proxy
// Forwards requests to DA/SF through Cloudflare's IP range
// to bypass datacenter IP blocking.
//
// Paste this into the Cloudflare Workers online editor.
// Set PROXY_SECRET as an environment variable in Worker Settings.
// Bind a KV namespace called SF_SESSIONS in Worker Settings → Variables.
//
// Key features:
//   1. Follows redirects internally with cookie forwarding (same egress IP)
//   2. Supports x-proxy-chain: JSON array of follow-up URLs to fetch
//      after the main request, all within one Worker execution.
//   3. Supports x-proxy-login: JSON with {url, email, password, then}
//      Performs GET login page → extract CSRF → POST login → GET 'then' URL
//      all in one invocation.  Critical for SoFurry IP-pinned sessions.
//   4. Session persistence via KV: stores session cookies after login and
//      reuses them on subsequent requests to avoid re-logging in every poll.

export default {
  async fetch(request, env) {
    // Auth check
    const proxyKey = request.headers.get('x-proxy-key');
    if (!proxyKey || proxyKey !== env.PROXY_SECRET) {
      return new Response('Unauthorized', { status: 403 });
    }

    // Build headers — strip proxy-specific and CF-injected headers
    const headers = new Headers();
    const skipHeaders = new Set([
      'x-proxy-key', 'x-target-url', 'x-proxy-chain', 'x-proxy-login', 'host',
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

    // Helper: build headers for a forwarded request.
    //
    // History note (fixed 2026-04-08): the previous version of this function
    // ALSO stripped 'content-type'. That broke every POST/PUT with a body
    // proxied through the worker — the body would arrive at the target
    // with no Content-Type, so SF/AO3/SQW couldn't parse JSON /
    // form-urlencoded / multipart bodies. Polling didn't notice because
    // polling is GET-only. Posting via the proxy was silently broken — we
    // only caught it when SF/AO3 server-side posting was about to be wired
    // up.
    //
    // We preserve Content-Type because it's a property of the request body,
    // not the connection. Multipart bodies in particular MUST keep their
    // boundary= parameter or the body is unparseable.
    //
    // We strip Content-Length because Cloudflare Workers' inner fetch()
    // recomputes the length from the body itself (or uses chunked encoding
    // for streams). Forwarding the original Content-Length from the
    // outer client→worker request would set a stale value that may not
    // match what the worker actually streams to the target.
    //
    // We strip Host (we set our own per-target) and Cookie (we manage
    // cookies in our own jar so domain-matching works).
    //
    // The login flow's extraHeaders override still works because
    // Headers.set() replaces existing values.
    function buildHeaders(url) {
      const h = new Headers();
      for (const [key, value] of headers) {
        if (!['host', 'cookie', 'content-length'].includes(key.toLowerCase())) {
          h.set(key, value);
        }
      }
      h.set('Host', new URL(url).host);
      const cookieStr = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
      if (cookieStr) h.set('Cookie', cookieStr);
      return h;
    }

    // Helper: fetch with internal redirect following + cookie forwarding
    async function fetchWithRedirects(url, method, body, extraHeaders) {
      const reqHeaders = buildHeaders(url);
      if (extraHeaders) {
        for (const [k, v] of Object.entries(extraHeaders)) {
          reqHeaders.set(k, v);
        }
      }

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

        // The redirect target is fetched as a GET with no body.
        // Drop content-type and content-length — they relate to the
        // (now-discarded) original POST/PUT body and would be misleading
        // on a body-less GET. Some strict servers reject GET requests
        // that carry a Content-Length header.
        const redirHeaders = buildHeaders(finalUrl);
        redirHeaders.delete('content-type');
        redirHeaders.delete('content-length');

        resp = await fetch(finalUrl, {
          method: 'GET',
          headers: redirHeaders,
          redirect: 'manual',
        });
        captureCookies(resp);
        redirects++;
      }

      return { resp, finalUrl, redirects };
    }

    // Helper: build final response with cookies
    function buildResponse(resp, finalUrl, extraHeaders) {
      const responseHeaders = new Headers();
      for (const [key, value] of resp.headers) {
        if (key.toLowerCase() !== 'set-cookie') {
          responseHeaders.append(key, value);
        }
      }
      for (const sc of allSetCookies) {
        responseHeaders.append('Set-Cookie', sc);
      }
      responseHeaders.set('X-Final-URL', finalUrl);
      const cookieStr = Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');
      if (cookieStr) {
        responseHeaders.set('X-Session-Cookies', cookieStr);
      }
      if (extraHeaders) {
        for (const [k, v] of Object.entries(extraHeaders)) {
          responseHeaders.set(k, v);
        }
      }
      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: responseHeaders,
      });
    }

    // Helper: save session cookies to KV (if KV is bound)
    async function saveSessionToKV(key, cookieObj) {
      if (!env.SF_SESSIONS) return;
      try {
        await env.SF_SESSIONS.put(key, JSON.stringify({
          cookies: cookieObj,
          saved_at: new Date().toISOString(),
        }), { expirationTtl: 86400 }); // 24h TTL
      } catch (e) {
        // KV write failures are non-fatal
      }
    }

    // Helper: load session cookies from KV
    async function loadSessionFromKV(key) {
      if (!env.SF_SESSIONS) return null;
      try {
        const data = await env.SF_SESSIONS.get(key, { type: 'json' });
        return data;
      } catch (e) {
        return null;
      }
    }

    // ─── Login sequence mode ───────────────────────────────────
    // x-proxy-login: {"url":"https://sofurry.com/login","email":"...","password":"...","then":"https://sofurry.com/u/X/gallery"}
    // Does GET login page → extract CSRF → POST login → GET 'then' URL, all same IP.
    // With KV: tries stored session first, only re-logins if session expired.
    const loginHeader = request.headers.get('x-proxy-login');
    if (loginHeader) {
      try {
        const login = JSON.parse(loginHeader);
        if (!login.url || !login.email || !login.password) {
          return new Response('x-proxy-login requires url, email, password', { status: 400 });
        }

        const kvKey = `sf_session_${login.email}`;

        // ── Try stored session first ──────────────────────────
        const stored = await loadSessionFromKV(kvKey);
        if (stored && stored.cookies && login.then) {
          // Inject stored cookies into our jar
          for (const [k, v] of Object.entries(stored.cookies)) {
            cookies[k] = v;
          }

          // Try fetching the 'then' URL with stored cookies
          const { resp: tryResp, finalUrl: tryUrl } =
            await fetchWithRedirects(login.then, 'GET', null);
          const tryHtml = await tryResp.text();

          // Check if session is still valid (not redirected to login, has content)
          const isLoggedIn = !tryUrl.includes('/login') &&
            (tryHtml.includes('logout') || tryHtml.includes('/s/'));

          if (isLoggedIn) {
            // Session reused — save updated cookies back to KV
            await saveSessionToKV(kvKey, { ...cookies });
            // Rebuild response from the HTML we already consumed
            const reusedResp = new Response(tryHtml, {
              status: 200,
              headers: tryResp.headers,
            });
            return buildResponse(reusedResp, tryUrl, { 'X-Session-Reused': 'true' });
          }

          // Session expired — fall through to fresh login
          // Clear stale cookies
          for (const k of Object.keys(cookies)) {
            delete cookies[k];
          }
          allSetCookies.length = 0;
        }

        // ── Fresh login ───────────────────────────────────────
        // Step 1: GET login page to extract CSRF token
        const { resp: loginPageResp, finalUrl: loginPageUrl } =
          await fetchWithRedirects(login.url, 'GET', null);
        const loginHtml = await loginPageResp.text();
        const csrfMatch = loginHtml.match(/name="_token"\s*value="([^"]+)"/);
        if (!csrfMatch) {
          return new Response('Could not find CSRF token on login page', { status: 502 });
        }
        const csrfToken = csrfMatch[1];

        // Step 2: POST login with CSRF token + credentials
        const formBody = `_token=${encodeURIComponent(csrfToken)}&email=${encodeURIComponent(login.email)}&password=${encodeURIComponent(login.password)}&remember=on`;
        const { resp: postResp, finalUrl: postFinalUrl } =
          await fetchWithRedirects(login.url, 'POST', formBody, {
            'Content-Type': 'application/x-www-form-urlencoded',
          });
        // Consume the POST response body so the connection is released
        await postResp.text();

        // Check if login failed (still on /login page)
        if (postFinalUrl.includes('/login')) {
          return buildResponse(postResp, postFinalUrl, { 'X-Session-Reused': 'false' });
        }

        // Step 3: Fetch the 'then' URL (e.g. gallery) if provided
        if (login.then) {
          const { resp: thenResp, finalUrl: thenUrl } =
            await fetchWithRedirects(login.then, 'GET', null);

          // Save session cookies to KV for next time
          await saveSessionToKV(kvKey, { ...cookies });

          return buildResponse(thenResp, thenUrl, { 'X-Session-Reused': 'false' });
        }

        // Save session cookies to KV
        await saveSessionToKV(kvKey, { ...cookies });

        return buildResponse(postResp, postFinalUrl, { 'X-Session-Reused': 'false' });
      } catch (err) {
        return new Response(`Login sequence error: ${err.message}`, { status: 502 });
      }
    }

    // ─── Normal proxy mode ─────────────────────────────────────
    const targetUrl = request.headers.get('x-target-url');
    if (!targetUrl) {
      return new Response('Missing x-target-url or x-proxy-login header', { status: 400 });
    }

    // Hostname allowlist — if PROXY_SECRET ever leaks, an attacker
    // shouldn't be able to turn this into an open proxy to arbitrary
    // hosts. Only allow the platforms we actually route through here.
    const ALLOWED_HOSTS = new Set([
      'sofurry.com',
      'www.sofurry.com',
      'deviantart.com',
      'www.deviantart.com',
      'archiveofourown.org',
      'www.archiveofourown.org',
      'squidgeworld.org',
      'www.squidgeworld.org',
      'furaffinity.net',
      'www.furaffinity.net',
    ]);
    let targetHost;
    try {
      targetHost = new URL(targetUrl).host.toLowerCase();
    } catch {
      return new Response('Invalid target URL', { status: 400 });
    }
    if (!ALLOWED_HOSTS.has(targetHost)) {
      return new Response(
        `Target host not on allowlist: ${targetHost}`,
        { status: 403 },
      );
    }

    // Optional: chain of follow-up URLs to fetch after the main request
    const chainHeader = request.headers.get('x-proxy-chain');
    let chainUrls = [];
    if (chainHeader) {
      try { chainUrls = JSON.parse(chainHeader); } catch {}
    }

    // Validate chain URLs against the same allowlist
    for (const u of chainUrls) {
      try {
        if (!ALLOWED_HOSTS.has(new URL(u).host.toLowerCase())) {
          return new Response(
            `Chain URL host not on allowlist: ${u}`,
            { status: 403 },
          );
        }
      } catch {
        return new Response(`Invalid chain URL: ${u}`, { status: 400 });
      }
    }

    try {
      headers.set('Host', targetHost);
    } catch {
      return new Response('Invalid target URL', { status: 400 });
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

      return buildResponse(lastResp, lastUrl);
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  }
};
