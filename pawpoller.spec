# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PawPoller desktop app.

Cross-platform: the hidden-imports block branches on sys.platform so
Windows builds pull in pystray._win32 + winotify, Linux builds pull in
pystray._appindicator (and the GTK backend), and macOS (when shipped)
will use pystray._darwin. CI's runners-os matrix picks the right
spec implicitly because PyInstaller is invoked from the relevant OS.
"""

import os
import sys

block_cipher = None

# Per-OS hidden imports — pystray has a different backend per platform
# and PyInstaller can't autodetect which one will be loaded at runtime.
_PLATFORM_HIDDEN_IMPORTS = {
    'win32':  ['pystray._win32', 'winotify'],
    'linux':  ['pystray._appindicator', 'pystray._gtk'],
    'darwin': ['pystray._darwin'],
}
_platform_key = 'linux' if sys.platform.startswith('linux') else sys.platform
_platform_hidden = _PLATFORM_HIDDEN_IMPORTS.get(_platform_key, [])

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('database/schema.sql', 'database'),
        ('database/fa_schema.sql', 'database'),
        ('database/ws_schema.sql', 'database'),
        ('database/sf_schema.sql', 'database'),
        ('database/sqw_schema.sql', 'database'),
        ('database/ao3_schema.sql', 'database'),
        ('database/da_schema.sql', 'database'),
        ('database/wp_schema.sql', 'database'),
        ('database/ik_schema.sql', 'database'),
        ('database/bsky_schema.sql', 'database'),
        ('database/tw_schema.sql', 'database'),
        ('database/mast_schema.sql', 'database'),
        ('database/tum_schema.sql', 'database'),
        ('database/pix_schema.sql', 'database'),
        ('database/posting_schema.sql', 'database'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.interval',
        'PIL',
        *_platform_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PawPoller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # hide console window in release build
    icon='assets/pawpoller.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PawPoller',
)
