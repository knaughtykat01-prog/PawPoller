"""Strip credentials out of log records before they reach any handler (2.193.1).

Found on the production VM: `docker compose logs pawpoller` printed **live access
tokens** at INFO. Nothing was logging them deliberately — httpx logs the complete
request URL for every call, and Threads, Instagram, Tumblr and Telegram all carry
credentials in the query string or path::

    HTTP Request: GET https://graph.instagram.com/refresh_access_token?...&access_token=<live token>
    HTTP Request: GET https://api.telegram.org/bot<bot id>:<live token>/getUpdates

Anything with log access read working credentials: the rotating files under
LOGS_DIR, `docker logs`, and the dashboard's own Logs view.

Two layers, because either alone is insufficient:

1. **Pattern redaction** — sensitive query/form parameters, the Telegram bot path
   token, ``Bearer``/``Token`` prefixes, and cookie headers. Catches credentials
   belonging to code that has not been written yet, but only in shapes it knows.
2. **Value redaction** — the actual secret values from the settings vault, so a
   token is unfindable even when it appears somewhere with no recognisable
   shape at all (an exception repr, a response body, a f-string someone adds
   next year). This is what makes the guarantee hold.

Design constraints this had to respect:

* **It must never break logging.** Every path is wrapped; on any error the record
  passes through unmodified rather than raising inside a handler.
* **It must not recurse.** Value redaction reads settings, and reading settings
  can itself log (vault warnings). A thread-local guard makes the filter a
  pass-through while it is refreshing, so a log call inside ``get_settings()``
  cannot re-enter it.
* **Identity fields stay readable.** Usernames and handles live in
  ``CREDENTIAL_FIELDS`` but are not secrets, and redacting them would turn
  "Logging in as KnaughtyKat" into noise. See ``_IDENTITY_HINTS``.
* **httpx puts the URL in ``record.args``, not ``record.msg``**, so args are
  rewritten too. Filters run before formatting, so this is the only place the
  URL can be reached before it hits both the stream and the file handler.

Install with ``install(...)`` on every entry point that configures logging
(``server.py``, ``main.py``, ``dashboard.py``) — a filter on the root logger's
handlers covers every library logger, httpx included.
"""
from __future__ import annotations

import logging
import re
import threading
import time

MASK = "[REDACTED]"

# Query-string / form parameters whose value is a credential.
_PARAM_NAMES = (
    "access_token", "refresh_token", "auth_token", "id_token", "api_key",
    "apikey", "client_secret", "token", "key", "secret", "password", "passwd",
    "pwd", "sid", "session", "session_key", "signature", "sig", "code",
    "cookie", "auth", "credentials", "app_password",
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ?access_token=… / &api_key=… — value runs to the next delimiter.
    (re.compile(r"(?i)([?&;](?:" + "|".join(_PARAM_NAMES) + r")=)[^&;\s\"'\\]+"),
     r"\1" + MASK),
    # Telegram carries the bot token in the PATH: /bot<id>:<secret>/getUpdates
    (re.compile(r"(?i)(/bot)\d{5,}:[A-Za-z0-9_\-]{15,}"), r"\1" + MASK),
    # Authorization: Bearer <t> / Token <t>  (Itaku uses the Token scheme)
    (re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=\-]{12,}"),
     r"\1 " + MASK),
    # Header-ish "Authorization: …" / "Cookie: …" in a message body.
    (re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-api-key)"
                r"(\s*[:=]\s*)[^\s,;]{8,}"), r"\1\2" + MASK),
]

# Credential keys that are IDENTITY, not secrets — keep them legible in logs.
_IDENTITY_HINTS = ("username", "identifier", "target_user", "display_name",
                   "instance_url", "own_handle", "_url", "user")

# Never redact a value shorter than this: short strings collide with ordinary
# log text and would mangle unrelated lines.
_MIN_VALUE_LEN = 8

_VALUE_TTL_SECONDS = 60.0


class SecretRedactingFilter(logging.Filter):
    """Rewrites credentials out of a record's msg and args."""

    def __init__(self, redact_values: bool = True):
        super().__init__()
        self._redact_values = redact_values
        self._values: tuple[str, ...] = ()
        self._values_at = 0.0
        self._lock = threading.Lock()
        self._guard = threading.local()

    # ── value cache ───────────────────────────────────────────
    def _secret_values(self) -> tuple[str, ...]:
        """Current secret values from settings, refreshed at most per TTL.

        Returns () rather than raising if settings are unreadable — a filter that
        throws would take out logging for the whole process.
        """
        if not self._redact_values:
            return ()
        now = time.monotonic()
        if self._values and (now - self._values_at) < _VALUE_TTL_SECONDS:
            return self._values
        # Reading settings can log; the guard makes this a pass-through if so.
        if getattr(self._guard, "busy", False):
            return self._values
        with self._lock:
            self._guard.busy = True
            try:
                import config
                settings = config.get_settings()
                vals = []
                for key, value in settings.items():
                    if not isinstance(value, str) or len(value) < _MIN_VALUE_LEN:
                        continue
                    if not config.is_credential_key(key):
                        continue
                    low = key.lower()
                    if any(h in low for h in _IDENTITY_HINTS):
                        continue
                    vals.append(value)
                # Longest first, so a token containing a shorter secret as a
                # substring is masked whole instead of leaving a tail behind.
                vals.sort(key=len, reverse=True)
                self._values = tuple(vals)
                self._values_at = now
            except Exception:  # noqa: BLE001 — never break logging
                self._values_at = now      # don't hot-loop on a broken vault
            finally:
                self._guard.busy = False
        return self._values

    # ── scrubbing ─────────────────────────────────────────────
    def scrub(self, text: str) -> str:
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        for secret in self._secret_values():
            if secret in text:
                text = text.replace(secret, MASK)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str) and record.msg:
                record.msg = self.scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (self.scrub(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        self.scrub(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:  # noqa: BLE001 — a broken filter must not drop logs
            pass
        return True          # always emit; we only rewrite


def install(redact_values: bool = True) -> SecretRedactingFilter:
    """Attach the filter to every root handler. Idempotent.

    Handler-level (not logger-level) so it applies to records propagated up from
    library loggers — a filter on the root *logger* is not consulted for those.
    """
    filt = SecretRedactingFilter(redact_values=redact_values)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(filt)
    return filt
