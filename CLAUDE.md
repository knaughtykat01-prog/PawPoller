# Claude Context — PawPoller

**Read `docs/HANDOFF.md` first** in any session — current state, deployed version, open
work, automation index. Deep technical reference: `docs/documentation_guide.md` (the heavy
comments and that guide exist specifically to give Claude context across sessions).
Per-version history: `CHANGELOG.md` — grep it by version, don't read it whole.

## Rituals (non-negotiable)
- Every code change ships **three doc surfaces**: a versioned `CHANGELOG.md` entry,
  the `docs/HANDOFF.md` header, and `docs/documentation_guide.md` where architecture
  changed — plus the `APP_VERSION` bump in `config.py`.
- Deploy workflow is **build → commit → push → deploy** — don't stop at commit.
  Cut a release: `/pp-release X.Y.Z "blurb"`. Ship to the VM: `/pp-deploy [version]`.
- If story files under `../m_x/Archives/Complete_Stories/` changed, run
  `deploy/pawsync.bat` BEFORE pushing code that references them. The server archive is a
  separate copy; pawsync pre-checks server freshness — if it aborts, `pawpull` first.

## Gotchas (each one cost a real incident)
- VM: `git pull` must run as kithetiger (`sudo -u kithetiger`); docker commands need `sudo`.
- `tag_database/` lives at repo root, NOT under `data/` — the Docker volume shadows
  bundled files.
- Never hold a SQLite write transaction across an `await` in pollers — commit before any
  network fetch that follows a write (2.26.3).
- FA posting requires desktop (datacenter IP block); CF Worker proxy is for DA + SF
  polling IP blocks only — it does NOT help with rate limits (shared egress).
- Dashboard/API on port 8420; `settings.json` lives at `/app/data/settings.json`
  (persistent volume).
- Tag drift check before tagging a release: `installer/PawPoller.iss` AppId GUID must
  never change (orphans every Windows install). The release-verifier subagent checks this.
