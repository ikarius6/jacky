# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Jacky Desktop Pet.

Build command:
    .\venv\Scripts\pyinstaller.exe jacky.spec

Output: dist/Jacky/Jacky.exe
"""

import os
import sys

block_cipher = None
PROJECT_ROOT = os.path.abspath('.')

_hidden = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
]
if sys.platform == 'win32':
    _hidden += ['win32api', 'win32gui', 'win32con', 'win32process', 'pywintypes']

a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        # Bundle sprites (all character packs)
        # NOTE: After implementing the character shop, you can reduce bundle size
        # by only bundling specific character packs instead of the whole sprites folder.
        # Example: ('sprites/Forest_Ranger_1', 'sprites/Forest_Ranger_2')
        # Users can download other packs from the shop at runtime.
        ('sprites', 'sprites'),
        # Bundle locale files (i18n)
        ('locales', 'locales'),
        # Bundle config.json as a template (user copy lives next to .exe)
        ('config.json', '.'),
    ],
    hiddenimports=_hidden,
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
    upx=True,
    console=False,  # No console window — it's a GUI app
    # icon='icon.ico',  # Uncomment and set path if you have an .ico file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Jacky',
)
