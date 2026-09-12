# PyInstaller specification for the local Windows product.  It is consumed only
# on Windows by build_windows.py; importing this file must not be needed in tests.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("frontend") + collect_data_files("modules")
hiddenimports = (
    collect_submodules("backend")
    + collect_submodules("frontend")
    + collect_submodules("modules")
    + ["c15_local.launcher"]
)

a = Analysis(
    ["scripts/c15_local/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "playwright", "black", "flake8", "mypy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MODELA-PRO", console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="MODELA-PRO")
