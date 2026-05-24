#!/usr/bin/env python3
"""LVS report check — wrapper for eda_report_audit --mode lvs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main
if __name__ == "__main__":
    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "lvs"]))
