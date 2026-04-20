# Phase 7 Design: Credential Management Modes

**Status:** Design  
**Date:** 2026-04-19  
**Depends on:** Phase 6 complete (posting module stable)

---

## Problem

PawPoller stores all credentials (11 platform logins, dashboard auth,
bot tokens, CF proxy keys) as plaintext JSON in `data/settings.json`.
Desktop and server each maintain their own copy. When the user logs
into a platform on one side, the other doesn't know — they must
re-enter credentials manually. Meanwhile the plaintext file is a
single-point compromise risk.

## Solution

Two mutually exclusive credential modes, selectable via
`"credential_mode": "cloud" | "local"` in settings.json:

| | Cloud mode | Local-only mode |
|---|---|---|
| **Who uses it** | Convenience — login once, both sides share | Security — credentials never leave the machine |
| **Storage** | Plaintext JSON (current behaviour) | Encrypted at rest via OS keyring |
| **Sync** | Desktop ↔ server via `/api/settings/sync` | No sync — each machine is independent |
| **Threat model** | Trusts the server (Docker volume, HTTPS) | Zero-trust — compromise of one machine doesn't leak creds |

Default: `"cloud"` (preserves current behaviour, zero migration cost).

---

## Credential Inventory

35+ sensitive fields across 12 contexts. The design must handle all
of these — not just "the big platforms."

### Platform credentials

| Platform | Fields | Auth type |
|----------|--------|-----------|
| Inkbunny | `username`, `password` | Form login → SID |
| FurAffinity | `fa_cookie_a`, `fa_cookie_b` | Browser cookies |
| Weasyl | `ws_api_key` | API key header |
| SoFurry | `sf_username`, `sf_password`, `sf_session_cookies` | Email/password + CSRF |
| SquidgeWorld | `sqw_username`, `sqw_password`, `sqw_author_username`, `sqw_author_password` | Form login (2 accounts) |
| AO3 | `ao3_username`, `ao3_password` | Rails form login |
| DeviantArt | `da_cookie` | Browser cookie |
| Bluesky | `bsky_identifier`, `bsky_app_password` | AT Protocol JWT |
| X/Twitter | `tw_auth_token`, `tw_ct0` | GraphQL session |

### Infrastructure credentials

| Context | Fields |
|---------|--------|
| CF proxy | `cf_worker_url`, `cf_worker_key` |
| Dashboard auth | `auth_password_hash`, `auth_api_keys`, `auth_session_secret`, `auth_totp_secret` |
| Telegram | `telegram_bot_token`, `telegram_chat_id` |
| GitHub | `github_pat` |
| Turnstile | `turnstile_site_key`, `turnstile_secret_key` |
| Desktop ↔ server | `posting_server_url`, `posting_server_api_key` |

### Non-credential settings (never encrypted, always synced in cloud mode)

Poll intervals, notification toggles, display timezone, target
usernames, `minimize_to_tray`, `posting_story_archive_path`, etc.

---

## Cloud Mode Design

### Sync endpoint

```
POST /api/settings/sync
Authorization: Bearer pp_xxx
Content-Type: application/json

{
    "settings": { ... },         // full or partial settings dict
    "timestamp": 1750000000,     // client's last-known settings mtime
    "mode": "push" | "pull"
}
```

**Pull** (desktop startup, or manual refresh):
- Server returns its current settings + server timestamp.
- Client merges: server wins for any key the client hasn't modified
  since its last sync. Client-modified keys win.

**Push** (after login/config change on desktop):
- Client sends its changed keys + timestamp.
- Server merges: incoming keys overwrite server values.
  Non-overlapping server keys are preserved.
- Server returns the merged result so client stays in sync.

**Auth:** Requires valid API key (same as existing poll pause/resume).

**Conflict resolution:** Last-write-wins per key, with timestamp
comparison. No full-file locking. Rationale: credentials rarely
change on both sides simultaneously; when they do, the most recent
login is the one that matters.

### Sync trigger points

| Event | Direction | What syncs |
|-------|-----------|------------|
| Desktop startup | Pull | All settings |
| Platform login/logout on desktop | Push | Changed platform keys |
| Platform login/logout on server dashboard | (no push — desktop pulls on next startup) | — |
| Manual "Sync now" button | Push then Pull | All settings |
| Settings page save | Push | Changed keys |

### What doesn't sync

- `credential_mode` itself (per-machine)
- `auth_session_secret` (per-instance, used for cookie signing)
- `minimize_to_tray` and other desktop-only UI prefs

```python
SYNC_EXCLUDE = {
    "credential_mode",
    "auth_session_secret",
    "minimize_to_tray",
}
```

---

## Local-Only Mode Design

### Encryption approach

```
settings.json          — non-credential settings (plaintext, as today)
settings.vault.json    — credential fields only (encrypted blob)
```

**Key derivation:**
- Windows: DPAPI via `win32crypt.CryptProtectData()` — key is tied to
  the Windows user account. No password prompt needed; decryption
  fails if a different user or machine tries.
- macOS/Linux: `keyring` library to store a Fernet key in the system
  keychain. Falls back to a passphrase prompt if no keyring is
  available.

**Library:** `cryptography.fernet.Fernet` (symmetric, authenticated).

**Vault format:**
```json
{
    "version": 1,
    "encrypted": "<base64-encoded Fernet token>",
    "key_source": "dpapi" | "keyring" | "passphrase"
}
```

The Fernet token decrypts to a JSON dict of credential keys only:
```json
{
    "username": "...",
    "password": "...",
    "fa_cookie_a": "...",
    ...
}
```

### Config loading changes

```python
def _load_settings() -> dict:
    base = _load_json(SETTINGS_PATH)              # non-credential
    if base.get("credential_mode") == "local":
        creds = _decrypt_vault(VAULT_PATH)         # credential fields
        base.update(creds)
    return base

def save_settings(data: dict) -> None:
    if get_credential_mode() == "local":
        cred_keys = data.keys() & CREDENTIAL_FIELDS
        if cred_keys:
            _update_vault({k: data[k] for k in cred_keys})
            data = {k: v for k, v in data.items() if k not in cred_keys}
    _save_json(SETTINGS_PATH, data)                # non-credential remainder
```

`CREDENTIAL_FIELDS` is the union of all fields from the inventory
above. Any key in this set goes to the vault; anything else stays in
plaintext settings.json.

### Migration path

When the user switches from `cloud` → `local`:
1. Read all credential fields from settings.json.
2. Encrypt them into settings.vault.json.
3. Remove credential fields from settings.json.
4. Write `"credential_mode": "local"` to settings.json.

When switching from `local` → `cloud`:
1. Decrypt vault.
2. Merge credential fields back into settings.json.
3. Delete settings.vault.json.
4. Write `"credential_mode": "cloud"`.

Both operations are atomic (write new file, then swap).

---

## Implementation Phases

### Phase 7a — Cloud sync (estimated: 1-2 sessions)

1. Add `POST /api/settings/sync` endpoint to `routes/api.py`
   (or new `routes/settings_api.py`)
2. Add `SYNC_EXCLUDE` set and merge logic to `config.py`
3. Add sync client to desktop startup path in `main.py`
4. Add "Sync now" button to dashboard Settings page
5. Add push calls after platform login/logout in each `{platform}_api.py`
6. Test: login on desktop → verify server picked up creds, and vice versa

### Phase 7b — Local-only vault (estimated: 2-3 sessions)

1. Add `cryptography` to requirements.txt
2. Add `_encrypt_vault()` / `_decrypt_vault()` to `config.py`
3. Add DPAPI wrapper (`win32crypt`) with `keyring` fallback
4. Modify `_load_settings()` / `save_settings()` per the design above
5. Add mode toggle to dashboard Settings page
6. Add migration flow (cloud → local, local → cloud)
7. Test: switch to local → restart → verify credentials still work,
   then switch back → verify settings.json has creds again

### Phase 7c — Desktop setup wizard (estimated: 1 session)

1. First-run detection (no settings.json or no credential_mode key)
2. Prompt: "Cloud sync or Local-only?"
3. If cloud: prompt for server URL + API key, pull settings
4. If local: walk through platform logins, encrypt as we go

---

## Security Considerations

- **Cloud mode trusts the server.** Credentials traverse the network
  (HTTPS) and sit on the Docker volume as plaintext. Acceptable for a
  single-user self-hosted setup; not appropriate for shared hosting.
- **Local-only DPAPI ties to the Windows user account.** If the user
  account is compromised, the vault is compromised. This is the same
  threat model as browser saved passwords.
- **API key for sync must already exist.** The sync endpoint doesn't
  create API keys — the user sets one up via the dashboard first.
  This prevents unauthenticated credential exfiltration.
- **No credential rotation mechanism.** If a credential is
  compromised, the user must change it on the platform and re-enter
  it in PawPoller. This is unchanged from current behaviour.

---

## Open Questions

1. **Should sync be automatic or manual?** Current design: pull on
   startup + push on change. Alternative: manual-only via "Sync now"
   button. The automatic approach is more convenient but adds startup
   latency and a failure mode (server unreachable).

2. **Partial vs full sync?** Current design: push only changed keys.
   Alternative: always push/pull the full settings dict. Full sync is
   simpler but risks overwriting intentionally-different settings
   (e.g. different poll intervals on desktop vs server).

3. **Should the vault encrypt individual fields or the whole blob?**
   Current design: one Fernet token for the whole credential dict.
   Alternative: per-field encryption (allows partial decryption).
   Whole-blob is simpler and sufficient for single-user use.

4. **Docker container and local-only mode?** The server runs in
   Docker — DPAPI doesn't exist there, and `keyring` needs a display
   session. Local-only mode is desktop-only by design; the server
   always uses cloud mode (plaintext in Docker volume). This should
   be explicit in the UI.

5. **Backwards compatibility?** Existing users have plaintext
   settings.json. Cloud mode preserves this exactly. No migration
   needed unless they opt into local-only.
