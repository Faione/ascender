#!/usr/bin/env python3
"""Build entry point; no installation or third-party Python packages required."""
from ascender.cli import main

if __name__ == "__main__":
    raise SystemExit(main("build"))
