<p align="center">
  <img src="frontend/img/logo-quill.png" alt="PawPoller logo" width="108">
</p>

<h1 align="center">PawPoller</h1>

<p align="center"><strong>Multi-platform story publishing pipeline for furry fiction writers.</strong></p>

<p align="center">🌐 <a href="https://pawpoller.pages.dev"><strong>pawpoller.pages.dev</strong></a> &nbsp;·&nbsp; features, screenshots, download</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11+-3776AB.svg" alt="Python 3.11+"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-0078D6.svg" alt="Platform: Windows and Linux"></a>
  <a href="#server--docker-deployment"><img src="https://img.shields.io/badge/Docker-supported-2496ED.svg" alt="Docker supported"></a>
</p>

PawPoller is a desktop app and self-hosted server for publishing fiction across furry writing platforms. Write your stories in Markdown, convert them to every format (BBCode, HTML, Styled HTML, PDF), publish to 11 platforms with per-chapter tags and descriptions, and track views, favourites, and comments from a single dashboard. Think of it as [PostyBirb](https://www.postybirb.com/) but built for writers instead of visual artists -- chaptered posting, format conversion, story analytics, and drift detection.

---

## Features

- **Multi-format conversion** -- Markdown to BBCode (Inkbunny), HTML (SoFurry), Styled HTML (AO3 work skins), PDF, and SquidgeWorld format, all from one source file
- **11-platform support** -- Inkbunny, FurAffinity, SoFurry, Weasyl, AO3, DeviantArt, SquidgeWorld, Wattpad, Itaku, Bluesky, and X/Twitter
- **Chaptered publishing** -- Split multi-chapter stories automatically, with per-chapter tags, descriptions, and thumbnails
- **Analytics dashboard** -- Track views, favourites, comments, and other metrics across all platforms with historical charts
- **Polling engine** -- Automatically fetches stats on a schedule, detects new comments and favourites
- **Telegram notifications** -- Get alerts for milestones, new comments, and goal completions
- **Built-in editor** -- Markdown editor with live preview, slop scoring, and format conversion
- **Tag database** -- 4,600+ tags with per-platform validation and chapter-level tagging
- **Goal tracking** -- Set targets for views/favourites/comments and track progress
- **Two deployment modes** -- Desktop app (Windows .exe) or headless Docker server
- **Credential vault** -- Optional encrypted credential storage with system keyring integration
- **Dashboard auth** -- Session-based login with bcrypt, TOTP 2FA, Cloudflare Turnstile, and API keys

---

## Screenshots

<p align="center">
  <img src="site/public/screens/story-archive.png" alt="Story archive with cover art" width="760"><br>
  <em>Story archive: every completed story with cover art, ratings, relationships, and status</em>
</p>

<p align="center">
  <img src="site/public/screens/analytics-overview.png" alt="Analytics dashboard across 11 platforms" width="760"><br>
  <em>Analytics across 11 platforms: views, favourites, and comment trends over time</em>
</p>

<p align="center">
  <img src="site/public/screens/publish-check-matrix.png" alt="Publish-check matrix" width="760"><br>
  <em>Publish-check matrix: every chapter and platform at a glance (posted / drifted / blocked)</em>
</p>

<p align="center">
  <img src="site/public/screens/editor-anchors.png" alt="Four-pane Markdown editor" width="760"><br>
  <em>Four-pane editor: Markdown source, live preview, and every derived format in sync</em>
</p>

---

## Quick Start

Full walkthrough: [**docs/SETUP.md**](docs/SETUP.md) — covers desktop, Docker self-hosting (including reverse proxy / Cloudflare Tunnel for public access), and running from source.

### Option A: Download the release (Desktop)

Native builds for Windows and Linux — pick whatever fits your machine:

**Windows** (two formats):

- **`PawPoller-Setup-{version}.exe`** (recommended): single-file installer.
  Per-user install by default (no UAC prompt); optional Start Menu /
  desktop shortcuts; optional "Run on Windows startup". Comes with a
  proper uninstaller in **Add or Remove Programs** that offers to keep
  your data folder so reinstalls don't wipe your SQLite DB / settings.
- **`PawPoller-windows-x64.zip`**: portable build. Extract and run
  `PawPoller.exe` from anywhere. No installer artefacts on your system.

**Linux** (single file):

- **`PawPoller-{version}-x86_64.AppImage`**: distro-independent single-file
  build. `chmod +x` and double-click (or run from a terminal). Works
  on Ubuntu 22.04+, Fedora 37+, Debian 12+, Arch — anything with
  glibc 2.35 or newer. Optional autostart via the in-app Settings →
  General toggle (writes a `.desktop` file under `~/.config/autostart/`).
- Need desktop notifications? `sudo apt install libnotify-bin` (or
  your distro's equivalent). The AppImage works without it; you just
  won't see toast pop-ups.

**macOS**: not yet — on the roadmap. Run via Docker for now.

After the first launch, the in-app setup wizard guides you through
connecting your platforms.

### Option B: Run from source

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
pip install -r requirements.txt
python main.py
```

### Option C: Docker (headless server)

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
cp .env.example .env    # Edit with your credentials — set DASHBOARD_PASSWORD!
# Edit docker-compose.yml: change the story-archive bind-mount path to yours
docker compose up -d --build
```

The dashboard is available at `http://localhost:8420`. For public/web access behind TLS, see [docs/SETUP.md §2.5](docs/SETUP.md#25-exposing-it-to-the-web).

---

## Supported Platforms

| Platform | Auth | Poll | Post | Edit | Notes |
|----------|------|------|------|------|-------|
| Inkbunny | Username/password | Yes | Yes | Yes | Full API support, chaptered |
| FurAffinity | Session cookies (a/b) | Yes | Yes | Yes | Scraping-based (no official API) |
| SoFurry | Email/password | Yes | Yes | Yes | Scraping-based, chaptered |
| Weasyl | API key | Yes | Yes | Yes | Official API |
| AO3 | Username/password | Yes | Yes | Yes | Rails CSRF login, work skins, chaptered |
| DeviantArt | Session cookie | Yes | Yes | Yes | Eclipse API, CF proxy for server |
| SquidgeWorld | Username/password | Yes | Yes | Yes | Scraping-based, chaptered |
| Wattpad | Public (read-only) | Yes | -- | -- | Public stats polling only |
| Itaku | Public (read-only) | Yes | -- | -- | Public stats polling only |
| Bluesky | Handle/app password | Yes | -- | -- | AT Protocol |
| X/Twitter | Auth token/ct0 | Yes | -- | -- | GraphQL scraping |

---

## Architecture

PawPoller has two entry points:

- **`main.py`** -- Desktop mode. Runs a pywebview native window with a pystray system tray icon. Per-platform poller threads run in the background. Best for personal use on Windows.
- **`server.py`** -- Headless/server mode. Runs just the FastAPI dashboard and a unified poll orchestrator. Designed for Docker or Linux VPS deployment for 24/7 polling.

Both modes share:
- **`dashboard.py`** -- FastAPI application serving the web UI and API
- **`config.py`** -- Settings, credentials, and path resolution
- **`database/`** -- SQLite database with per-platform schemas
- **`frontend/`** -- Plain HTML/JS/CSS dashboard (no build step, no framework)

Each platform follows a consistent file pattern:
```
clients/{xx}/client.py     -- HTTP client for the platform API
polling/{xx}_poller.py     -- Poll cycle orchestration
database/{xx}_queries.py   -- Database queries
database/{xx}_schema.sql   -- SQL schema
routes/{xx}_api.py         -- Dashboard API endpoints
posting/platforms/{xx}.py  -- Upload/edit logic (where supported)
```

---

## Development

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
pip install -r requirements.txt
cp .env.example .env          # Optional: for env-based credential config
python main.py                # Desktop mode
# or
python server.py              # Headless mode
```

### Server-only dependencies

For Docker/server deployments, use the pinned server requirements:

```bash
pip install -r requirements-server.txt
```

### Building the Windows executable

```bash
pip install pyinstaller
python -m PyInstaller pawpoller.spec --noconfirm
# Output: dist/PawPoller/PawPoller.exe
```

### Running tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Project documentation

See [`docs/documentation_guide.md`](docs/documentation_guide.md) for the full technical reference covering every module, database schema, API endpoint, and platform client.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on development setup, adding new platforms, code style, and pull requests.

---

## License

[MIT](LICENSE)

---

## Credits

- Inspired by [PostyBirb](https://www.postybirb.com/) -- PawPoller takes the multi-platform publishing concept and rebuilds it for fiction writers with chaptered stories, format conversion, and analytics
- Built with [FastAPI](https://fastapi.tiangolo.com/), [pywebview](https://pywebview.flowrl.com/), [Chart.js](https://www.chartjs.org/)
