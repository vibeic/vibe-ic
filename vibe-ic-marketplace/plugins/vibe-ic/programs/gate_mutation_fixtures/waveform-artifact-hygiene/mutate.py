#!/usr/bin/env python3
"""Drop a real simulation waveform dump inside the bundle.

Classification is by CONTENT, so the fixture writes a genuine VCD header
rather than an empty file with the suffix. It is generated, not committed:
the gate walks the filesystem, so a stored dump anywhere under the plugin is
a finding against the real tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VCD = (
    "$date\n   fixture\n$end\n"
    "$version\n   fixture\n$end\n"
    "$timescale 1ns $end\n"
    "$scope module top $end\n"
    "$var wire 1 ! clk $end\n"
    "$upscope $end\n"
    "$enddefinitions $end\n"
    "#0\n0!\n#1\n1!\n"
)


def main() -> int:
    tree = Path(sys.argv[1])
    (tree / "programs" / "leaked_wave.vcd").write_text(_VCD, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
