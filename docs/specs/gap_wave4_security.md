# Gap Wave 4 — Self-host security hardening

**Status:** SPEC — building now · **Author:** Rhys + Claude (fable) · **Date:** 2026-07-24

> Direction chosen: "Self-host & security." A scout + an adversarial security review reframed this from "build 2FA"
> (already fully built + enforced) to **fix a latent dep bug + close a HIGH vuln + add the one real 2FA gap + cheap
> hardening + the public-readiness docs (§2/§4/§5)**. What already exists: 2FA end-to-end, per-IP rate-limiting,
> bcrypt, signed sessions w/ rotation, API keys, Turnstile, always-on vault. Findings are from the review; each
> item below cites its file:line.

## 1. Latent dependency bug (real; fresh-install crash)
`pyotp`, `bcrypt`, `itsdangerous` are imported directly (`dashboard_auth.py`, `config.py`) but only in
`requirements-server.txt` — **not `requirements.txt`** nor `pawpoller.spec` hiddenimports. A source/dev `pip install
-r requirements.txt` (the self-host path) crashes auth on ImportError. **Fix:** add all three to `requirements.txt`
and `pawpoller.spec` `hiddenimports`.

## 2. HIGH — unauthenticated first-run takeover → vault exfil
`/api/auth/dashboard-setup` is auth-exempt and NOT in `_SENSITIVE_WHEN_OPEN_PREFIXES`; `server.py` binds `0.0.0.0`
with only a warning when unconfigured. Attacker on an exposed unconfigured instance sets their own password → logs in
→ `is_dashboard_auth_required()` flips true → the loopback gate no longer applies → `POST /api/settings/sync` returns
the decrypted vault (all platform creds). **Fix:** gate `dashboard-setup` to loopback callers when unconfigured
(add `request: Request`, reuse `_client_is_loopback`), with a conscious `PAWPOLLER_ALLOW_OPEN_SETUP=1` opt-out for
trusted-network remote setup. Surgical, endpoint-local (no middleware-order dependency).

## 3. MEDIUM — 2FA has no recovery + durable-lockout attack
TOTP is the only factor; no backup codes; `totp-disable` needs a *live* code → lost authenticator = unrecoverable via
UI. And `totp-enable` needs only a session (not the password) → a brief session hijack binds the attacker's
authenticator and locks the owner out durably. **Fix:**
- **Backup codes:** 10 one-time codes generated at enable, returned ONCE, stored as SHA-256 hashes in a new
  `auth_totp_backup_codes` credential key (vault). Accepted at login (TOTP branch, on TOTP-verify failure) and at
  `totp-disable`; consumed on use (hash removed). `regenerate-backup-codes` endpoint. Status returns remaining count.
- **Require the password to enable 2FA** (closes the hijack→lockout path).

## 4. MEDIUM — global brute-force ceiling (IP-rotation)
Per-IP limiter only (`dashboard.py:307-338`); IP rotation defeats it. **Fix (conservative, no admin lockout):** a
global failure counter; past a high window threshold, add a fixed delay to each login attempt (soft throttle — slows
distributed guessing, never hard-locks the real admin, who clears their own IP on success). Turnstile stays the
strong operator-configurable option (documented).

## 5. LOW hardening (cheap, review points 4-6)
- **API-key compare** (`config.py:1224`): `==` → `hmac.compare_digest`.
- **Username-enum timing** (`dashboard_auth.py:122`): run a dummy bcrypt when the username mismatches so timing is
  uniform.
- **HSTS**: emit `Strict-Transport-Security` when the effective scheme is https (`_BASE_SECURITY_HEADERS` +
  conditional in the header middleware).

## 6. Docs (§2/§4/§5 public-readiness)
- `docs/security/SELF_HOST_SECURITY.md` — threat model, first-run/loopback-setup guidance, `PAWPOLLER_FORWARDED_IPS`
  + Secure-cookie/HSTS, 2FA + backup codes + the vault-based reset path, and the **known-gaps register** (stateless
  logout non-revocation, TOTP in-window replay, distributed brute-force → Turnstile). §2 creds-at-rest: the vault is
  already always-on — document the out-of-band `PAWPOLLER_VAULT_KEY` posture.
- `docs/security/SIGNING.md` — §4: installers are **unsigned** today; SmartScreen/Gatekeeper implications; options
  (self-signed / EV cert / sigstore) + recommendation. Honest decision note — signing needs a certificate I can't
  produce.
- `docs/TERMS_TEMPLATE.md` + `docs/PRIVACY_TEMPLATE.md` — §5: fill-in templates for a self-hoster.

**Tests** (`tests/test_auth_hardening.py`): backup-code gen/consume/exhaust + login-with-backup-code; setup
loopback gate (loopback ok / remote refused / override allows); API-key still validates under compare_digest;
require-password-to-enable. **Ship:** 2.185.0, full suite pre-deploy.
