"""``python -m autoface`` — GUI with no arguments, CLI with them."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        from .cli import main as cli_main

        return cli_main(argv)

    try:
        from .gui.app import main as gui_main
    except ImportError as exc:  # PySide6 missing
        print(
            f"error: the desktop UI needs PySide6 ({exc}).\n"
            "Install it with: pip install PySide6\n"
            "Or run the self-test: python -m autoface --selftest",
            file=sys.stderr,
        )
        return 2
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
