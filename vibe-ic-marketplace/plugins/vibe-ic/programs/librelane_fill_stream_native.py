"""Run the installed LibreLane stream producer with native fill retention.

The installed source and its license/header are retained. Legacy cell-clearing
APIs are adapted without changing the installed script.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from librelane_fill_stream import native_script, patched_native_source

if __name__ == '__main__':
    original = native_script()
    source = patched_native_source(original.read_text())
    sys.argv[0] = str(original)
    exec(compile(source, str(original), 'exec'), {'__name__': '__main__', '__file__': str(original)})
