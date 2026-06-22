# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['glue_dispenser.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports = ['PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'matplotlib', 'pkg_resources.extern'],    
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='glue_dispenser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False if you don't want a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'
)
