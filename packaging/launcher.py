"""PyInstaller entry script.

PyInstaller runs the entry script as a package-less ``__main__``, which breaks
relative imports in ``autoface/__main__.py``. Importing the module by its full
name keeps the package context intact.
"""

import sys

from autoface.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
