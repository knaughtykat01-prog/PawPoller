-- Commissions — a lightweight client/commission tracker (gap-wave-5 §4).
-- A single self-contained table (no members/rollup, unlike Collections): each
-- row is one commission with client, price, status, an optional linked delivered
-- artwork, and the platforms it was delivered to. Money is data only — there is
-- no payment integration. See docs/specs/gap_wave5.md.

CREATE TABLE IF NOT EXISTS commissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name   TEXT NOT NULL DEFAULT '',
    description   TEXT DEFAULT '',
    price         REAL DEFAULT 0,
    currency      TEXT DEFAULT 'USD',
    status        TEXT NOT NULL DEFAULT 'quote',   -- quote|accepted|wip|paid|delivered
    due_date      TEXT DEFAULT '',                 -- ISO date 'YYYY-MM-DD' or ''
    artwork_name  TEXT DEFAULT '',                 -- links a delivered piece (#/artwork/image/<name>)
    deliver_sites TEXT DEFAULT '[]',               -- JSON array of platform codes
    notes         TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_commissions_status ON commissions(status);
