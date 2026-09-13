import os
import sys
from pathlib import Path

os.environ["MODELA_SKIP_DOTENV"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
for path in (str(REPO_ROOT), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
