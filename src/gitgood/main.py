from __future__ import annotations

import sys

from gitgood.app import run


def main() -> None:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run(repo_path))


if __name__ == "__main__":
    main()
