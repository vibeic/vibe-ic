"""Native Verilator Step 4 candidate; fixed simulator, shared canonical consumers."""
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from execution_step4 import main

if __name__ == '__main__':
    main('verilator')
