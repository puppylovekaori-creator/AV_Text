# av_title_convert.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys

from avtext_service import run_one_shot, MODE_TITLE_ONLY


def main() -> int:
    result = run_one_shot(MODE_TITLE_ONLY, sys.argv[1:])
    if result.message:
        print(result.message)
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
