#!/usr/bin/env python3
r"""netlist_src_coord_canonicalize.py — make a synthesised netlist reproducible
(ORGANIC-20260531-yosys-write-verilog-nondeterministic-line-tagged-net-names).

Yosys' `write_verilog` mints auto-generated names that embed the SOURCE
COORDINATE of the construct that created them — e.g.

    $func$/abs/path/to/design.v:42$3
    \mux$/home/run-7/rtl/foo.v:118 .Y

The path prefix and `:line` make the netlist NON-deterministic: synthesise the
same RTL from a different absolute directory (or after an unrelated line shift)
and the byte content — and thus the provenance sha256 — changes even though the
logic is identical. That breaks reproducible-build / provenance-hash comparison.

This pass canonicalises those coordinates AWAY, chip-AGNOSTIC-ally:
  * a `$…$`-delimited auto-name carrying `<path>/<base>:<line>` is collapsed to
    its path-free, line-free `<base>` form;
  * a `\`-escaped identifier carrying the same coordinate is collapsed likewise.
Only the path prefix and the `:<digits>` line suffix are dropped — the basename
and the rest of the name are preserved, so distinct constructs stay distinct.
A netlist with no embedded coordinates is returned byte-identical (idempotent).

The regex matches the generic `<path>:<line>` coordinate shape, never a
chip/vendor token — so it is safe across every design.

Usage:
    python3 netlist_src_coord_canonicalize.py <netlist.v> [--in-place]
                                              [--out <path>] [--check]

    --in-place   rewrite the file in place (default if neither --out nor --check)
    --out PATH   write the canonicalised text to PATH instead
    --check      do not write; exit 1 if the file still carries a coordinate
                 (i.e. is not yet canonical), 0 if already clean

Exit codes:
    0  done (or --check: already canonical)
    1  --check: file still carries a source coordinate
    2  argument / I/O error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A source coordinate is "<something>:<one-or-more-digits>" where <something>
# looks like a path segment or a bare filename (no whitespace, no '$', no ':').
# We strip the directory prefix (everything up to and including the last '/')
# and the ":<line>" suffix, keeping the basename.
#
# 1) inside a yosys auto-name token  $…<path>/<base>:<line>…$
_COORD_IN_AUTONAME = re.compile(r"\$([^$\n]*?:\d+[^$\n]*?)\$")
# 2) a backslash-escaped Verilog identifier carrying a coordinate; an escaped
#    id runs from '\' to the next whitespace.
_COORD_IN_ESCID = re.compile(r"\\[^\s]*:\d+[^\s]*")
# Coordinate sub-patterns applied INSIDE the matched token only.
# _PATH_BASE_LINE uses a GREEDY `[^\s$]*/` so the WHOLE directory prefix
# (every segment, however many '/') is consumed up to the last slash before the
# basename — that is what makes the result path-invariant (same RTL synthesised
# from /home/runA/… and /tmp/run-7/… collapses to the identical basename).
_PATH_BASE_LINE = re.compile(r"[^\s$]*/([^\s$/:\\]+):\d+")        # <path>/<base>:<line> -> <base>
_BASE_LINE = re.compile(r"([^\s$/:\\]+):\d+")                     # <base>:<line>        -> <base>
# detection for --check (any surviving coordinate of either shape)
_ANY_COORD = re.compile(r"[^\s$:]*:\d+(?=[^\s]*[$\s])")


def _strip_coord(token: str) -> str:
    token = _PATH_BASE_LINE.sub(r"\1", token)
    token = _BASE_LINE.sub(r"\1", token)
    return token


def canonicalize(text: str) -> str:
    """Return text with every embedded `<path>:<line>` source coordinate in an
    auto-name (`$…$`) or escaped identifier (`\\…`) collapsed to its basename.
    Idempotent; a coordinate-free netlist is returned unchanged."""
    text = _COORD_IN_AUTONAME.sub(
        lambda m: "$" + _strip_coord(m.group(1)) + "$", text)
    text = _COORD_IN_ESCID.sub(lambda m: _strip_coord(m.group(0)), text)
    return text


def has_coordinate(text: str) -> bool:
    """True if text still carries a `$…:<line>…$` auto-name or `\\…:<line>`
    escaped-id coordinate."""
    return bool(_COORD_IN_AUTONAME.search(text) or _COORD_IN_ESCID.search(text))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Canonicalise yosys source-coordinate net names for "
                    "reproducible netlists (chip-AGNOSTIC).")
    ap.add_argument("netlist", help="path to the .v netlist")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite the file in place (default if no --out/--check)")
    ap.add_argument("--out", help="write canonicalised text here instead")
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if a coordinate survives")
    args = ap.parse_args(argv)

    p = Path(args.netlist)
    if not p.is_file():
        print(f"error: netlist not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text(errors="replace")
    except OSError as exc:
        print(f"error: cannot read {p}: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if has_coordinate(text):
            print(f"NOT-CANONICAL: {p} still carries a source coordinate "
                  "(<path>:<line>) in a net/cell name", file=sys.stderr)
            return 1
        print(f"CANONICAL: {p} has no embedded source coordinates")
        return 0

    out_text = canonicalize(text)
    dest = Path(args.out) if args.out else p
    try:
        dest.write_text(out_text)
    except OSError as exc:
        print(f"error: cannot write {dest}: {exc}", file=sys.stderr)
        return 2
    print(f"canonicalised {p} -> {dest} "
          f"({'unchanged' if out_text == text else 'rewritten'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
