# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('adapters/mv/ZZ_Translator_Bridge.js', 'adapters/mv')]
# 加密 MZ 功能的模組有些是 gui 函式內的延遲 import（只在執行到加密路徑才觸發），
# 明確列入 hiddenimports 以保證被打包，避免執行期才炸 ImportError。
hiddenimports = [
    'version',
    'core.mz_decrypt',
    'core.mz_extract',
    'core.translators.protect',
    'adapters.mz',
    'adapters.mz.pretranslate',
]
datas += collect_data_files('opencc')
hiddenimports += collect_submodules('opencc')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GameTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GameTranslator',
)
