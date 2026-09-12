# PyInstaller specification for the local Windows product.  It is consumed only
# on Windows by build_windows.py; importing this file must not be needed in tests.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPEC).resolve().parents[2]
frontend_sources = [
    (str(path), str(path.parent.relative_to(root)))
    for path in sorted((root / "frontend").rglob("*.py"))
]
buyer_docs = (
    "operations_manual.md",
    "privacy.md",
    "support_and_maintenance.md",
)
datas = (
    collect_data_files("frontend")
    + collect_data_files("modules")
    + collect_data_files("profiles")
    + frontend_sources
    + [
        (str(root / "THIRD_PARTY_NOTICES.md"), "."),
        (str(root / "SECURITY.md"), "."),
    ]
    + [
        (str(root / "docs" / "comercial" / "c04" / name), "docs")
        for name in buyer_docs
    ]
)
hiddenimports = (
    collect_submodules("backend")
    + collect_submodules("frontend")
    + collect_submodules("modules")
    + collect_submodules("pyhanko")
    + collect_submodules("pyhanko_certvalidator")
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
