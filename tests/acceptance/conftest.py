import sys
from pathlib import Path

ACCEPTANCE_DIR = Path(__file__).resolve().parent
ROOT = ACCEPTANCE_DIR.parents[1]
for path in (str(ROOT), str(ACCEPTANCE_DIR), str(ROOT / "tests" / "fixtures" / "independent")):
    if path not in sys.path:
        sys.path.insert(0, path)
