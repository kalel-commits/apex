"""Build the reproducible deliverable ZIP without caches or local environments."""
from __future__ import annotations
from pathlib import Path
import zipfile

PROJECT=Path(__file__).resolve().parents[1]
OUTPUT=PROJECT.parent/"io_signal_sudoku_industry_upgrade.zip"
EXCLUDED_DIRS={".git",".pytest_cache","__pycache__",".venv","venv",".mypy_cache",".ruff_cache"}
EXCLUDED_SUFFIXES={".pyc",".pyo"}

def main()->None:
    with zipfile.ZipFile(OUTPUT,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
        for path in sorted(PROJECT.rglob("*")):
            if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.relative_to(PROJECT).parts): continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES or path.name==".coverage": continue
            archive.write(path,Path(PROJECT.name)/path.relative_to(PROJECT))
    with zipfile.ZipFile(OUTPUT) as archive:
        bad=archive.testzip()
        if bad: raise RuntimeError(f"ZIP CRC verification failed for {bad}")
    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size} bytes)")

if __name__=="__main__": main()
