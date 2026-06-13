#!/usr/bin/env python3
"""IR-drop report check — wrapper for eda_report_audit --mode ir_drop."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main
if __name__ == "__main__":
    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "ir_drop"]))
