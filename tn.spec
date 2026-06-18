# PyInstaller one-file build for the tn CLI.
#
# Build:  uv run --with pyinstaller pyinstaller tn.spec
# Output: dist/tn  (a single self-contained executable)
#
# Bake the build stamp BEFORE freezing so the frozen exe has a distinct cache
# identity (see build.py / docs/PACKAGING.md). Run first:
#   python scripts/stamp_build.py && uv run --with pyinstaller pyinstaller tn.spec
#
# What has to travel with the freeze (see resources.py for the runtime seam):
#   * trustworthy_notes package data — the bundled Charis SIL fonts and the
#     notes JSON Schema (collect_data_files over the package).
#   * the generated _build_stamp module — build.py imports it under a try; the
#     guarded import means PyInstaller's static analysis can miss it, so it is
#     named as a hidden import to guarantee it is bundled.
#   * pdfminer's cmap data — pdfminer reads these at runtime to decode text;
#     they are package data, not code, so a default freeze drops them.
#   * jsonschema's metadata — jsonschema discovers validator classes via its
#     installed-distribution metadata (entry points), which a freeze omits
#     unless the .dist-info is copied in.
#
# The equivalent one-liner (kept in sync with docs/PACKAGING.md) is:
#   uv run --with pyinstaller pyinstaller --onefile --name tn \
#       --collect-data trustworthy_notes --collect-data pdfminer \
#       --hidden-import trustworthy_notes._build_stamp \
#       --copy-metadata jsonschema src/trustworthy_notes/__main__.py

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = []
datas += collect_data_files("trustworthy_notes")  # fonts/ + schemas/
datas += collect_data_files("pdfminer")           # cmap data
datas += copy_metadata("jsonschema")              # validator entry points


a = Analysis(
    ["src/trustworthy_notes/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=["trustworthy_notes._build_stamp"],
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
    name="tn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
