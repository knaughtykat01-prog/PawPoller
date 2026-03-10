# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PawPoller desktop app."""

import os

block_cipher = None

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
        'pystray._win32',
        'PIL',
        'winotify',
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
    console=True,  # show console window for logs
    icon=None,
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
