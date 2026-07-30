"""Credentials must not reach a log handler (2.193.1).

Found on the production VM: `docker compose logs pawpoller` printed live access
tokens at INFO, because httpx logs the full request URL and several platforms
carry credentials in the query string or path. The token strings below are the
SHAPES observed in that output, with the secret bodies replaced by fakes.

The important assertions are the negative ones: the secret must not appear
anywhere in the formatted record, and the URL arrives via record.args (not
record.msg) which is the part a naive msg-only filter would miss.

Every token literal below is **fully synthetic** — deliberately not built by
keeping a real prefix and swapping the tail, because a real prefix plus a real
bot id is still real information committed to a repo for no benefit. The URL
STRUCTURE is what these tests need; the bytes are invented.
"""
import logging

import config
import log_redaction
from log_redaction import MASK, SecretRedactingFilter


def _formatted(filt, msg, *args):
    """Push a record through the filter, then format it as a handler would."""
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, msg, args or None, None)
    assert filt.filter(rec) is True          # never drops a record
    return logging.Formatter("%(message)s").format(rec)


# ── pattern layer ─────────────────────────────────────────────

def test_query_string_access_token_is_masked_from_args():
    """httpx passes the URL as an ARG, not in msg — the easy thing to get wrong."""
    filt = SecretRedactingFilter(redact_values=False)
    url = ("https://graph.instagram.com/refresh_access_token"
           "?grant_type=ig_refresh_token&access_token=SYNTHETIC0igtoken0value0aaaa")
    out = _formatted(filt, 'HTTP Request: %s %s "%s"', "GET", url, "200 OK")
    assert "SYNTHETIC0igtoken0value0aaaa" not in out
    assert MASK in out
    # Non-secret context survives, or the log is useless.
    assert "graph.instagram.com" in out
    assert "grant_type=ig_refresh_token" in out
    assert "200 OK" in out


def test_telegram_bot_token_in_url_path_is_masked():
    """Telegram puts the token in the PATH, so query-param matching misses it."""
    filt = SecretRedactingFilter(redact_values=False)
    url = "https://api.telegram.org/bot1111100000:SYNTHETICbottoken0value/getUpdates?offset=1"
    out = _formatted(filt, "HTTP Request: GET %s", url)
    assert "1111100000:SYNTHETICbottoken0value" not in out
    assert "api.telegram.org" in out
    assert "/getUpdates" in out


def test_tumblr_api_key_and_threads_token_masked():
    filt = SecretRedactingFilter(redact_values=False)
    out = _formatted(filt, "HTTP Request: GET %s",
                     "https://api.tumblr.com/v2/blog/x/info?api_key=SYNTHETIC0tumblr0key0")
    assert "SYNTHETIC0tumblr0key0" not in out
    out = _formatted(filt, "HTTP Request: GET %s",
                     "https://graph.threads.net/refresh_access_token"
                     "?grant_type=th_refresh_token&access_token=SYNTHETIC0threads0token0")
    assert "SYNTHETIC0threads0token0" not in out


def test_bearer_and_token_auth_headers_masked():
    filt = SecretRedactingFilter(redact_values=False)
    assert "abcdef1234567890xyz" not in _formatted(
        filt, "sending Authorization: Bearer abcdef1234567890xyz")
    # Itaku uses the DRF "Token <t>" scheme.
    assert "ik_tok_abcdef123456" not in _formatted(
        filt, "header Authorization: Token ik_tok_abcdef123456")


def test_cookie_header_masked():
    filt = SecretRedactingFilter(redact_values=False)
    out = _formatted(filt, "Cookie: sessionid=abcdef1234567890")
    assert "abcdef1234567890" not in out


def test_ordinary_lines_are_left_alone():
    """Over-redaction would make the logs worthless — check the common cases."""
    filt = SecretRedactingFilter(redact_values=False)
    for line in (
        "session check complete: {'ao3': 'valid', 'sf': 'valid'}",
        "SqW: Successfully logged in as KnaughtyKat",
        "Skipping startup poll - last cycle was recent, next in 100 min",
        "HTTP Request: GET https://e621.net/favorites.json?limit=1",
        "Submission 12345: scraping comments (count=3, force=False)",
    ):
        assert _formatted(filt, "%s", line) == line, line


# ── value layer ───────────────────────────────────────────────

def test_actual_stored_secret_is_masked_in_any_shape():
    """The guarantee: a real token is unfindable even with no recognisable shape.

    Pattern matching can only cover shapes it knows about; this is what covers
    an exception repr, a response body, or a log line added next year.
    """
    secret = "th_live_SECRET_VALUE_abcdefgh1234"
    config.save_settings({"thr_access_token": secret})
    filt = SecretRedactingFilter()
    out = _formatted(filt, "unexpected reply from Threads: %s",
                     "{'error': 'bad token " + secret + " rejected'}")
    assert secret not in out
    assert MASK in out


def test_identity_fields_stay_readable():
    """Usernames live in CREDENTIAL_FIELDS but are not secrets; masking them
    would turn 'Logging in as KnaughtyKat' into noise."""
    config.save_settings({"username": "KnaughtyKatLongEnough",
                          "password": "sup3rsecret_password_value"})
    filt = SecretRedactingFilter()
    out = _formatted(filt, "IB: logging in as %s", "KnaughtyKatLongEnough")
    assert "KnaughtyKatLongEnough" in out
    # ...but the password beside it is gone.
    assert "sup3rsecret_password_value" not in _formatted(
        filt, "creds=%s", "sup3rsecret_password_value")


def test_short_values_never_redacted():
    """A short secret would collide with ordinary words and mangle real lines."""
    config.save_settings({"tw_ct0": "abc"})
    filt = SecretRedactingFilter()
    assert _formatted(filt, "%s", "abc def abc") == "abc def abc"


# ── robustness ────────────────────────────────────────────────

def test_filter_never_raises_or_drops_on_hostile_input():
    filt = SecretRedactingFilter()
    for msg, args in (
        (None, None), (12345, None), (b"bytes", None),
        ("%s", (object(),)), ("no args but %s", None),
    ):
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, msg, args, None)
        assert filt.filter(rec) is True


def test_broken_settings_degrades_to_pattern_only(monkeypatch):
    """An unreadable vault must not take out logging for the whole process."""
    filt = SecretRedactingFilter()
    monkeypatch.setattr(config, "get_settings",
                        lambda: (_ for _ in ()).throw(RuntimeError("vault boom")))
    out = _formatted(filt, "HTTP Request: GET %s", "https://x/y?access_token=STILLMASKED123")
    assert "STILLMASKED123" not in out       # pattern layer still works


def test_reading_settings_cannot_recurse_through_the_filter(monkeypatch):
    """Value refresh reads settings, and reading settings can LOG. Without the
    thread-local guard that re-enters the filter and recurses forever."""
    filt = SecretRedactingFilter()
    calls = {"n": 0}
    logger = logging.getLogger("recursion-probe")

    def _logging_get_settings():
        calls["n"] += 1
        if calls["n"] < 5:
            rec = logging.LogRecord("cfg", logging.WARNING, __file__, 1,
                                    "vault warning", None, None)
            filt.filter(rec)          # simulates a log call inside get_settings
        return {}

    monkeypatch.setattr(config, "get_settings", _logging_get_settings)
    filt.scrub("anything")
    assert calls["n"] < 5, "filter re-entered settings load — guard failed"
    del logger


def test_install_is_idempotent_and_handler_scoped():
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        log_redaction.install()
        log_redaction.install()
        n = sum(1 for f in handler.filters if isinstance(f, SecretRedactingFilter))
        assert n == 1
    finally:
        root.removeHandler(handler)
