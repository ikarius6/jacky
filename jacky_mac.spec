# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Jacky Desktop Pet — macOS .app bundle.

Build command (from project root inside a venv with pyinstaller installed):
    python -m PyInstaller jacky_mac.spec

Output: dist/Jacky.app
"""

import os

block_cipher = None
PROJECT_ROOT = os.path.abspath('.')

a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        ('sprites', 'sprites'),
        ('locales', 'locales'),
        ('config.json', '.'),
    ],
    hiddenimports=[
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        # pyobjc frameworks used by pal/macos.py
        'Cocoa',
        'Quartz',
        'ApplicationServices',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        # Windows-only — never bundle on Mac
        'win32api',
        'win32gui',
        'win32con',
        'win32process',
        'pywintypes',
        'pywin32',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Jacky',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX doesn't benefit macOS universal binaries
    console=False,
    # icon='icon.icns',  # Uncomment when an .icns icon is available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Jacky',
)

app = BUNDLE(
    coll,
    name='Jacky.app',
    icon=None,  # Set to 'icon.icns' when available
    bundle_identifier='com.jacky.pet',
    info_plist={
        'CFBundleName': 'Jacky',
        'CFBundleDisplayName': 'Jacky Desktop Pet',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSBackgroundOnly': False,
        'NSAccessibilityUsageDescription':
            'Jacky needs Accessibility permission to interact with your desktop windows '
            '(move, resize, peek, minimize). You can deny this and the pet will still '
            'walk, talk, and react — window interactions will just be disabled.',
        'NSMicrophoneUsageDescription':
            'Jacky can listen to your voice for speech-to-text input. '
            'Microphone access is optional.',
    },
)
