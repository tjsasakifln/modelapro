# PyInstaller specification for the local Windows product.  It is consumed only
# on Windows by build_windows.py; importing this file must not be needed in tests.
import os
import json
import re
import runpy
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPEC).resolve().parents[2]
source_data_files = runpy.run_path(
    str(root / "packaging" / "comercial" / "source_data.py")
)["source_data_files"]
frontend_sources = [
    (str(path), str(path.parent.relative_to(root)))
    for path in sorted((root / "frontend").rglob("*.py"))
]
buyer_docs = (
    "operations_manual.md",
    "privacy.md",
    "support_and_maintenance.md",
)
native_root_value = os.environ.get("MODELA_WINDOWS_NATIVE_DIR", "").strip()
native_root = Path(native_root_value) if native_root_value else None
if not native_root or not native_root.is_dir():
    raise RuntimeError("MODELA_WINDOWS_NATIVE_DIR must identify the staged Windows native runtime")
native_dlls = sorted((native_root / "dlls").glob("*.dll"))
if not native_dlls:
    raise RuntimeError("staged Windows native runtime contains no DLLs")
native_binaries = [(str(path), ".") for path in native_dlls]
native_evidence = [
    (str(native_root / "native-runtime.json"), "native-runtime"),
    (str(native_root / "licenses"), "native-runtime/licenses"),
    (str(native_root / "fontconfig"), "native-runtime/fontconfig"),
]
module_datas = source_data_files(
    root,
    "modules",
    excluded_names=frozenset({"trusted_vendor_anchor.json"}),
)
frontend_datas = source_data_files(root, "frontend")
profile_datas = source_data_files(root, "profiles")
anchor_value = os.environ.get("MODELA_BUILD_TRUSTED_ANCHOR", "").strip()
trusted_anchor = (
    Path(anchor_value)
    if anchor_value
    else root / "modules" / "commercial_license" / "trusted_vendor_anchor.json"
)
if not trusted_anchor.is_file():
    raise RuntimeError("trusted vendor anchor resource is absent")
build_identity_value = os.environ.get("MODELA_BUILD_SOURCE_IDENTITY_FILE", "").strip()
build_identity = Path(build_identity_value) if build_identity_value else None
if not build_identity or not build_identity.is_file():
    raise RuntimeError("verified build source identity resource is absent")
build_identity_payload = json.loads(build_identity.read_text(encoding="utf-8"))
if (
    build_identity_payload.get("schema_version") != "MP-COM-BUILD-IDENTITY/1"
    or not re.fullmatch(r"[0-9a-f]{40}", str(build_identity_payload.get("source_sha") or ""))
    or not re.fullmatch(r"[0-9a-f]{40}", str(build_identity_payload.get("tree_sha") or ""))
):
    raise RuntimeError("verified build source identity resource is invalid")
datas = (
    frontend_datas
    + collect_data_files("streamlit")
    + copy_metadata("streamlit", recursive=True)
    + copy_metadata("modelapro")
    + module_datas
    + profile_datas
    + frontend_sources
    + native_evidence
    + [(str(trusted_anchor), "modules/commercial_license")]
    + [(str(build_identity), ".")]
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
    + collect_submodules("streamlit")
    + collect_submodules("pyhanko")
    + collect_submodules("pyhanko_certvalidator")
    + collect_submodules("pypdf")
    + ["c15_local.launcher"]
)

a = Analysis(
    [str(root / "scripts" / "c15_local" / "launcher.py")],
    pathex=[str(root)],
    binaries=native_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "packaging" / "comercial" / "windows_runtime.py")],
    excludes=["pytest", "playwright", "black", "flake8", "mypy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MODELA-PRO",
    console=False,
    contents_directory=".",
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="MODELA-PRO")
