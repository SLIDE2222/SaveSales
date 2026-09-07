"""Compatibility launcher: all PCs now use the same LAN client."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("main.py")), run_name="__main__")
