"""Entry script for the frozen KeepFrame.exe (PyInstaller needs a top-level script)."""

from keepframe.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
