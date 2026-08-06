from __future__ import annotations

import sys


def main() -> int:
    print(
        "此判重入口已废弃；正式判重只能使用 "
        "scripts/check_eight_consecutive_duplicates.py 和 .tmp/recent_10_cache.json。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
