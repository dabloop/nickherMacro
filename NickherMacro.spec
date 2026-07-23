# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Nickher Macro.

Do NOT use collect_all('PySide6') here. It drags in every Qt module including
Qt6WebEngineCore (a full Chromium, ~200 MB) and its debug .pak resources, for
an app that only ever imports QtWidgets/QtCore/QtGui. PyInstaller's built-in
PySide6 hook already pulls exactly what the imports need.
"""

datas = [('ncicon.ico', '.')]

hiddenimports = [
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
]

#: Qt modules this app never touches. Excluding them keeps the binary small
#: and keeps the build stable if Qt bundles more optional pieces later.
excludes = [
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtSerialPort',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
    'PySide6.QtSpatialAudio', 'PySide6.QtStateMachine', 'PySide6.QtSvgWidgets',
    'PySide6.QtTextToSpeech', 'PySide6.QtHttpServer',
    # Scientific stack, occasionally pulled in transitively
    'numpy', 'scipy', 'pandas', 'matplotlib', 'PIL',
    'tkinter', 'unittest', 'pydoc_data', 'lib2to3',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NickherMacro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ncicon.ico'],
)
