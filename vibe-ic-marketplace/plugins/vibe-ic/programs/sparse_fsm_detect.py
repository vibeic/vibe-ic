#!/usr/bin/env python3
"""sparse_fsm_detect.py — find SPARSE FSM state registers in the design INPUT.

WHY (#2067). `synth` runs the `fsm` pass, whose `fsm_recode` sub-pass
RE-ASSIGNS the state encoding of every FSM it extracts — by default to
one-hot. A design that deliberately chose a Hamming-distance-separated
("sparse") encoding for fault-injection resistance loses exactly the
property the encoding exists for: the netlist is functionally equivalent
(LEC proves the key points) but it is no longer the design that was
specified. MEASURED on a 3-state, d_min=3, 5-bit reproducer with the
shipped image:

    without this   `wire [2:0] state_q`  reset 3'b001   (fsm_recode one-hot)
    with this      `wire [4:0] state_q`  reset 5'b01110 (the RTL constant)

This module is the DETECTOR half; it is PURE and reads ONLY the design
INPUT (RTL text), never a netlist, an oracle or a golden (§4.05).

THREE INDEPENDENT EVIDENCE KINDS, any one of which marks a register sparse:

  prim_sparse_fsm_flop_inst   a direct `prim_sparse_fsm_flop ... u (...)`
                              instantiation (the OpenTitan sparse-FSM flop);
                              the state register is the signal on `.state_i`.
  prim_flop_sparse_fsm_macro  a ``PRIM_FLOP_SPARSE_FSM(name, d, q, type, ...)``
                              macro use — the state register is `q`. The macro
                              is how OpenTitan RTL actually instantiates the
                              flop; matching only the module name finds the
                              macro DEFINITION and nothing else (measured on
                              the opentitan_aes corpus cell: 2 files name the
                              module, 7 use the macro).
  fsm_encoding_attr           an explicit `(* fsm_encoding = "..." *)` on a
                              register declaration — the author already said
                              "do not re-encode this".
  hamming_separated_enum      a state-constant group (SV `typedef enum` or a
                              `localparam` block) of >= MIN_STATES codes of
                              equal width whose MINIMUM PAIRWISE HAMMING
                              DISTANCE is >= MIN_HAMMING. A one-hot or
                              binary-count encoding has d_min = 1 or 2 and is
                              NOT matched; a sparse encoding has d_min >= 3 by
                              construction. Registers declared with that enum
                              type are the state registers.

Usage:
    python3 sparse_fsm_detect.py --rtl-dir <dir> [--json out.json]
    python3 sparse_fsm_detect.py <file.sv> ... [--json out.json]

Exit codes:
    0 = ran (whether or not anything was detected; detection is not a verdict)
    2 = usage / unreadable input
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from _atomic_artefact import write_text as atomic_write_text  # #1082
from _hdl_code_text import strip_hdl_comments_and_strings  # #731

# A sparse encoding is defined by its MINIMUM pairwise Hamming distance. The
# OpenTitan generator's own floor is 3 (`sparse-fsm-encode.py -d 3`), which is
# also the smallest distance that detects any single-bit fault. 2 would admit
# ordinary gray codes, so 3 is the honest floor, not a tuned one.
MIN_HAMMING = 3
# Two codes at distance >= 3 can be an accident of a 2-value flag; three is the
# smallest group for which "someone ran a sparse encoder" is the simple reading.
MIN_STATES = 3

RTL_SUFFIXES = (".sv", ".v", ".svh", ".vh")

_ENUM_RE = re.compile(
    r"typedef\s+enum\s+(?:logic|bit|reg)?\s*(?:\[[^\]]*\])?\s*\{(?P<body>.*?)\}"
    r"\s*(?P<name>\w+)\s*;",
    re.S)
_CONST_RE = re.compile(r"(?P<name>\w+)\s*=\s*(?P<w>\d+)'b(?P<bits>[01_]+)")
_LOCALPARAM_RE = re.compile(
    r"(?:localparam|parameter)\s+(?:logic|bit|reg)?\s*(?:\[[^\]]*\])?\s*"
    r"(?P<name>\w+)\s*=\s*(?P<w>\d+)'b(?P<bits>[01_]+)\s*;")
# `prim_sparse_fsm_flop #(...) u_x ( ... .state_i ( sig ) ... );`
_SPARSE_INST_RE = re.compile(
    r"\bprim_sparse_fsm_flop\b(?P<tail>.*?);", re.S)
_STATE_I_RE = re.compile(r"\.state_i\s*\(\s*(?P<sig>[\w\.\[\]]+)\s*\)")
_MACRO_RE = re.compile(
    r"`PRIM_FLOP_SPARSE_FSM\s*\(\s*(?P<name>\w+)\s*,\s*(?P<d>[\w\.]+)\s*,\s*"
    r"(?P<q>[\w\.]+)\s*,\s*(?P<type>\w+)", re.S)
_ATTR_DECL_RE = re.compile(
    r"\(\*[^*]*\bfsm_encoding\b[^*]*\*\)\s*"
    r"(?:logic|reg|wire|bit)?\s*(?:\[[^\]]*\])?\s*(?P<names>[\w\s,]+?)\s*;",
    re.S)
_MODULE_RE = re.compile(r"(?m)^\s*module\s+(\w+)")


def _strip_macro_definitions(text: str) -> str:
    """Remove ``\`define`` bodies (continued with trailing backslashes).

    MEASURED on the opentitan_aes corpus cell: `prim_flop_macros.sv` DEFINES
    ``PRIM_FLOP_SPARSE_FSM``, and its body instantiates
    ``prim_sparse_fsm_flop`` with the macro's own formal argument on
    `.state_i` — so scanning the definition reports the placeholder ``__d``
    as a state register of no module. A definition is not a use."""
    out, skip = [], False
    for line in text.splitlines():
        if not skip and re.match(r"\s*`define\b", line):
            skip = True
        if skip:
            out.append("")
            if not line.rstrip().endswith("\\"):
                skip = False
            continue
        out.append(line)
    return "\n".join(out)


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments. Sparse encodings are documented in a
    comment histogram right above the enum; leaving them in makes the
    constant regex match prose."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def hamming(a: str, b: str) -> int:
    """Pairwise Hamming distance of two equal-length bit strings."""
    return sum(1 for x, y in zip(a, b) if x != y)


def min_pairwise_hamming(codes: Sequence[str]) -> Optional[int]:
    """Minimum pairwise Hamming distance, or None when it is undefined
    (fewer than two codes, or codes of unequal width). None is NOT 0: an
    undefined distance must never read as "densely packed"."""
    codes = [c for c in codes if c]
    if len(codes) < 2:
        return None
    if len({len(c) for c in codes}) != 1:
        return None
    return min(hamming(a, b) for a, b in itertools.combinations(codes, 2))


def _module_at(text: str, pos: int) -> str:
    """Name of the module enclosing character offset `pos` ('' when none).

    vibe-ic#731: `// this module drives the round counter` matches
    `^\s*module\s+(\w+)` and mints an enclosing module that does not exist,
    which mis-groups the localparam constants this answer keys. Blanked, NOT
    deleted: `pos` is an offset into the CALLER's text, so the scan must keep
    the same offsets or the `m.start() > pos` cut moves.
    """
    text = strip_hdl_comments_and_strings(text)
    last = ""
    for m in _MODULE_RE.finditer(text):
        if m.start() > pos:
            break
        last = m.group(1)
    return last


def _sparse_enum_types(text: str) -> Dict[str, dict]:
    """{enum type name: evidence} for every enum whose constants are
    Hamming-separated.

    READS SYSTEMVERILOG DECLARATION GRAMMAR, NEVER PROSE. The only natural
    language anywhere in this input is the comment block in which OpenTitan
    documents its Hamming histogram, and this function strips comments ITSELF
    before the first match rather than trusting its callers to have done it —
    so the claim "no sentence reaches these regexes" is a property of the
    function, not of the two call sites. `_strip_comments` is idempotent, so
    the callers that already strip lose nothing. See the `_NOT_PROSE` entry
    for this function in `prose_polarity_consulted_check.py`."""
    text = _strip_comments(text)
    out: Dict[str, dict] = {}
    for m in _ENUM_RE.finditer(text):
        consts = [(c.group("name"), c.group("bits").replace("_", ""))
                  for c in _CONST_RE.finditer(m.group("body"))]
        if len(consts) < MIN_STATES:
            continue
        d = min_pairwise_hamming([b for _n, b in consts])
        if d is not None and d >= MIN_HAMMING:
            out[m.group("name")] = {
                "min_hamming": d,
                "states": {n: b for n, b in consts},
            }
    return out


def _sparse_localparam_groups(text: str) -> List[dict]:
    """Hamming-separated groups of equal-width `localparam` state constants
    (the plain-Verilog spelling of the same thing)."""
    consts = [(m.group("name"), m.group("bits").replace("_", ""),
               int(m.group("w")), m.start())
              for m in _LOCALPARAM_RE.finditer(text)]
    groups: Dict[Tuple[str, int], List[Tuple[str, str]]] = {}
    for name, bits, w, pos in consts:
        groups.setdefault((_module_at(text, pos), w), []).append((name, bits))
    out: List[dict] = []
    for (mod, _w), items in groups.items():
        if len(items) < MIN_STATES:
            continue
        d = min_pairwise_hamming([b for _n, b in items])
        if d is not None and d >= MIN_HAMMING:
            out.append({"module": mod, "min_hamming": d,
                        "states": {n: b for n, b in items}})
    return out


def _regs_of_type(text: str, type_name: str) -> List[Tuple[str, str]]:
    """[(module, register)] for every declaration `type_name a, b;`."""
    out: List[Tuple[str, str]] = []
    for m in re.finditer(
            r"(?m)^\s*" + re.escape(type_name) + r"\s+(?P<names>[\w\s,]+?)\s*;",
            text):
        for nm in m.group("names").split(","):
            nm = nm.strip()
            if nm and nm.isidentifier():
                out.append((_module_at(text, m.start()), nm))
    return out


def detect_text(text: str, source: str = "") -> List[dict]:
    """Sparse state registers evidenced by ONE RTL text. PURE."""
    text = _strip_macro_definitions(_strip_comments(text))
    found: List[dict] = []

    def add(reg: str, module: str, kind: str, extra: Optional[dict] = None):
        rec = {"register": reg, "module": module, "evidence": kind,
               "source": source}
        if extra:
            rec.update(extra)
        found.append(rec)

    for m in _SPARSE_INST_RE.finditer(text):
        sig = _STATE_I_RE.search(m.group("tail"))
        if sig:
            inst = re.search(r"\)\s*(?P<i>\w+)\s*\(", m.group("tail"))
            add(sig.group("sig"), _module_at(text, m.start()),
                "prim_sparse_fsm_flop_inst",
                {"flop_instance": inst.group("i")} if inst else None)

    for m in _MACRO_RE.finditer(text):
        add(m.group("q"), _module_at(text, m.start()),
            "prim_flop_sparse_fsm_macro",
            {"state_type": m.group("type"), "flop_instance": m.group("name")})

    for m in _ATTR_DECL_RE.finditer(text):
        for nm in m.group("names").split(","):
            nm = nm.strip()
            if nm and nm.isidentifier():
                add(nm, _module_at(text, m.start()), "fsm_encoding_attr")

    for tname, ev in _sparse_enum_types(text).items():
        for mod, reg in _regs_of_type(text, tname):
            add(reg, mod, "hamming_separated_enum",
                {"state_type": tname, "min_hamming": ev["min_hamming"],
                 "states": ev["states"]})

    for grp in _sparse_localparam_groups(text):
        # A localparam group evidences a sparse ENCODING; the register that
        # holds it is whatever the case statement switches on. Report the
        # group and every register compared against one of its constants.
        for reg in sorted({r for r in re.findall(
                r"case\s*\(\s*([\w\.]+)\s*\)", text)}):
            add(reg, grp["module"], "hamming_separated_localparam",
                {"min_hamming": grp["min_hamming"], "states": grp["states"]})
    return found


def collect_rtl(paths: Sequence[Path]) -> List[Path]:
    """Every RTL file under the given files/dirs, sorted, de-duplicated."""
    out: List[Path] = []
    seen: Set[str] = set()
    for p in paths:
        cands = (sorted(p.rglob("*")) if p.is_dir() else [p])
        for c in cands:
            if c.is_file() and c.suffix in RTL_SUFFIXES:
                r = str(c.resolve())
                if r not in seen:
                    seen.add(r)
                    out.append(c)
    return out


def detect_paths(paths: Sequence[Path]) -> dict:
    """Run the detector over files/dirs. Reports unreadable files by name —
    "could not read it" is never "read it and it was empty"."""
    files = collect_rtl(paths)
    regs: List[dict] = []
    unreadable: List[str] = []
    # Design-wide enum table. A macro use names its state TYPE, but the
    # `typedef enum` with the constants usually lives in a package file
    # (measured: `aes_ctr_e` is used in aes_ctr_fsm.sv and defined in
    # aes_pkg.sv), so the codes can only be attached by a cross-file join.
    enum_table: Dict[str, dict] = {}
    for f in files:
        try:
            txt = f.read_text(errors="replace")
        except OSError as e:  # pragma: no cover - filesystem-dependent
            unreadable.append(f"{f}: {e}")
            continue
        enum_table.update(_sparse_enum_types(
            _strip_macro_definitions(_strip_comments(txt))))
        regs.extend(detect_text(txt, source=str(f)))
    for r in regs:
        ev = enum_table.get(r.get("state_type", ""))
        if ev and not r.get("states"):
            r["states"] = ev["states"]
            r["min_hamming"] = ev["min_hamming"]
    # de-duplicate by (module, register), keeping every evidence kind
    by_key: Dict[Tuple[str, str], dict] = {}
    for r in regs:
        k = (r.get("module", ""), r["register"])
        cur = by_key.setdefault(k, {"module": k[0], "register": k[1],
                                    "evidence": [], "sources": [],
                                    "states": {}})
        if r["evidence"] not in cur["evidence"]:
            cur["evidence"].append(r["evidence"])
        if r.get("source") and r["source"] not in cur["sources"]:
            cur["sources"].append(r["source"])
        if r.get("states"):
            cur["states"] = r["states"]
        if r.get("min_hamming") is not None:
            cur["min_hamming"] = r["min_hamming"]
        if r.get("state_type"):
            cur["state_type"] = r["state_type"]
        if r.get("flop_instance"):
            cur["flop_instance"] = r["flop_instance"]
    ordered = [by_key[k] for k in sorted(by_key)]
    return {
        "tool": "sparse_fsm_detect",
        "files_scanned": len(files),
        "unreadable": unreadable,
        "sparse_state_registers": ordered,
        "register_names": sorted({r["register"] for r in ordered}),
        "flop_instances": sorted({r["flop_instance"] for r in ordered
                                  if r.get("flop_instance")}),
        "declares_sparse_fsm": bool(ordered),
    }


def yosys_setattr_cmd(register_names: Sequence[str],
                      flop_instances: Sequence[str] = ()) -> Optional[str]:
    """The single `setattr` command that marks these state registers
    "do not re-encode", or None when there is nothing to mark.

    TWO SELECTION SHAPES, because the state register is not always where the
    RTL names it. MEASURED on the opentitan_aes `aes_ctr_fsm` block with the
    shipped image: the register `fsm_recode` actually re-encoded was
    ``u_state_regs.u_state_flop.q_o`` — the sparse FLOP's own output, not the
    RTL's ``aes_ctr_cs``. So we select both the declared register name AND a
    wildcard anchored on the sparse-flop INSTANCE name the RTL gave, which
    after `flatten` is the prefix of the real state wire. Anchoring on the
    instance keeps the selection to the FSMs the design declared sparse; a
    bare `w:*q_o*` would have covered every flop in the design."""
    names = [n for n in dict.fromkeys(register_names)
             if n and re.fullmatch(r"[A-Za-z_][\w$]*", n)]
    insts = [i for i in dict.fromkeys(flop_instances)
             if i and re.fullmatch(r"[A-Za-z_][\w$]*", i)]
    sel = [f"w:{n}" for n in names] + [f"w:*{i}*" for i in insts]
    if not sel:
        return None
    return 'setattr -set fsm_encoding "none" ' + " ".join(sel)


def yosys_encoding_preserve_cmds(register_names: Sequence[str],
                                 flop_instances: Sequence[str] = (),
                                 top: Optional[str] = None) -> List[str]:
    """The yosys commands that make `fsm_recode` LEAVE these registers alone.

    `(* fsm_encoding = "none" *)` on the state wire is what `fsm_detect` reads
    to skip an FSM, so setting that attribute is a PER-REGISTER opt-out: every
    OTHER FSM in the design keeps its normal optimisation. That is why this is
    preferred over `synth -nofsm`, which disables the pass design-wide.

    `proc` must run first (the register must be a wire) and `flatten` must run
    before the attribute is set, because the wire that is actually re-encoded
    lives INSIDE the sparse flop and only carries its instance-path name once
    the design is flat (measured, see `yosys_setattr_cmd`). `synth -flatten`
    flattens again, idempotently.

    Returns [] for an empty detection — a design with no sparse FSM gets a
    BYTE-IDENTICAL yosys script."""
    cmd = yosys_setattr_cmd(register_names, flop_instances)
    if cmd is None:
        return []
    pre = [f"hierarchy -top {top}"] if top else []
    return pre + ["proc", "flatten", cmd]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="RTL files or directories")
    ap.add_argument("--rtl-dir", action="append", default=[],
                    help="directory to scan recursively")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    paths = [Path(p) for p in list(a.files) + list(a.rtl_dir)]
    if not paths:
        print("error: no RTL files or --rtl-dir given", file=sys.stderr)
        return 2
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("error: does not exist: " + ", ".join(missing), file=sys.stderr)
        return 2
    rep = detect_paths(paths)
    txt = json.dumps(rep, indent=2, sort_keys=True)
    if a.json:
        atomic_write_text(Path(a.json), txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
