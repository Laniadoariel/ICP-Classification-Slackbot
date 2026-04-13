import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root / "src"))

from icp_bot.main import main  # noqa: E402

if __name__ == "__main__":
    main()

