#!/usr/bin/env python3
"""Flow stage check — wrapper for signoff_audit --mode flow."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from signoff_audit import main
if __name__ == "__main__":
    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "flow"]))
