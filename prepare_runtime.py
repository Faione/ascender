#!/usr/bin/env python3
"""Runtime configuration entry point; does not start containers."""
from ascender.cli import main

if __name__ == "__main__":
    raise SystemExit(main("runtime"))
