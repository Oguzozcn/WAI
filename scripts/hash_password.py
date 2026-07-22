"""Print a bcrypt hash for a password, to paste into data/credentials.json.

Usage:
    python scripts/hash_password.py "newpassword"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.auth_store import hash_password

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python scripts/hash_password.py "newpassword"')
        raise SystemExit(2)
    print(hash_password(sys.argv[1]))
