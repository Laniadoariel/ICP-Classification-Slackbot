import sys
from pathlib import Path

# Allow `import icp_bot` in tests without requiring packaging work yet.
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))

