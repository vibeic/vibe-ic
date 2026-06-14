#!/usr/bin/env python3
"""shape_b_sample_export.py — deterministic Shape-B sample-export (ORGANIC #678).

THE SOLE EMIT PATH for a Shape-B benchmark sample, analogous to
`benchmark/gates_atomic.py` for Shape C. Replaces the PROSE-ONLY blind-
instructions step 4 ("Find the module that matches the description's stated name
and copy it to `<RUNDIR>/samples/<leaf>.v`").

WHY THIS EXISTS (the gate↔scorer discrepancy this fixes)
--------------------------------------------------------
The runner's Phase-2 pipeline may fire `reset_clock_variant_alias` (#518): it
renames the TB-facing top to `<top>__rcvar_inner` IN PLACE and appends a wrapper
module `<top>` that exposes the canonical reset/clock port spelling and wires it
1:1 to the inner core. BOTH modules live in ONE RTL file, and only that complete
file PASSES the hidden testbench (which binds the canonical port name). The
SAME class applies to leaf-typo SYNONYM wrappers (#517): a `<canonical>` wrapper
around a misspelled `<leaf>` core, both in one file.

A prose "copy the module matching the description name" step extracts only the
un-wrapped INNER core (its ports use the prompt's original spelling), DROPPING
the wrapper the runner deterministically generated. The standalone
`iverilog_compile` gate (no TB) passes the inner → gate GREEN; the host scorer
binds the hidden TB against the CANONICAL port → COMPILE-ERROR ("port <rst_n> is
not a port of dut"). The deterministic fix the runner produced never reaches the
scorer — a gate-as-sole-emit-path failure (same disease as ORGANIC #529).

WHAT THIS DOES INSTEAD
----------------------
Copy the runner's COMPLETE TB-facing-top RTL FILE verbatim into
`<RUNDIR>/samples/<leaf>.v`, preserving every variant-alias / synonym wrapper
bundled with its inner children in that one file — rather than extracting a
single module whose ports match the prompt's stated names.

Selection rule (deterministic, chip-AGNOSTIC):
  * Prefer the module the runner designated as the TB-facing top — the alias
    WRAPPER (a `*__rcvar_inner` core's matching wrapper, or a leaf-typo synonym
    wrapper). When an alias wrapper is present, its FILE is the export source
    (it carries both the wrapper AND the inner core in one file).
  * Otherwise prefer the leaf/spec module name (the prompt's stated name) — the
    historical default. Its whole file is still copied verbatim (a design may
    legitimately span several modules in one file).

POST-EXPORT GUARD (chip-AGNOSTIC, structural)
---------------------------------------------
After writing `samples/<leaf>.v`:
  1. `iverilog -g2012` it STANDALONE — it must compile on its own (an export
     that dropped a wrapper's inner child fails "Unknown module type").
  2. Assert COMPLETENESS: for every `*__rcvar_inner` module present, its matching
     wrapper module (same name minus the `__rcvar_inner` suffix) must ALSO be
     present in the exported file — and vice-versa, every alias wrapper that
     instantiates a `*__rcvar_inner` must ship that inner. A wrapper-without-
     inner or inner-without-wrapper export is REJECTED.

chip-AGNOSTIC: deny-list/structural/registry-flag only. No chip / vendor / SKU /
foundry literal — it reuses the runner's existing alias metadata
(`reset_clock_variant_alias.parse_module_ports` + the runner's own naming
conventions `__rcvar_inner` / the `#517`/`#518` generated-by header markers).

Usage:
    python3 shape_b_sample_export.py --project <RUNDIR>/work/<leaf> \\
        --leaf <leaf> --samples <RUNDIR>/samples [--module <spec_module_name>]

    # or point directly at the runner's RTL dir
    python3 shape_b_sample_export.py --rtl-dir <project>/phase2/stage1/rtl \\
        --leaf <leaf> --samples <RUNDIR>/samples [--module <spec_module_name>]

Exit codes:
    0  PASS — sample exported + guard passed
    1  FAIL — export guard rejected the sample (incomplete / non-compiling)
    2  argument / I-O error / nothing to export
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _path_layout as _pl  # noqa: E402
import reset_clock_variant_alias as _rcv  # noqa: E402

# The runner's own inner-rename suffix (step_reset_clock_variant_aliases,
# phase2_one_shot_runner.py). chip-AGNOSTIC structural token, not a chip name.
RCVAR_INNER_SUFFIX = "__rcvar_inner"

# Comment/string-stripping reused from the alias program so a `module X` token
# inside a doc-header comment or a `$display` string is never mis-counted.
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip(txt: str) -> str:
    return _STRING_RE.sub('""', _rcv._strip_comments(txt))


def _module_names(txt: str) -> List[str]:
    """All `module <name>` declarations in `txt` (comment/string-stripped)."""
    return re.findall(r"\bmodule\s+([A-Za-z_]\w*)\b", _strip(txt))


def _file_modules(rtl_dir: Path) -> Dict[str, Tuple[Path, str]]:
    """Map module-name -> (file, full_file_text) over rtl_dir/*.{v,sv}.
    First declaration wins (mirrors the runner's _rcvar_module_bodies)."""
    out: Dict[str, Tuple[Path, str]] = {}
    for f in sorted(rtl_dir.rglob("*")):
        if f.suffix not in (".v", ".sv") or not f.is_file():
            continue
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        for name in _module_names(txt):
            out.setdefault(name, (f, txt))
    return out


def _instantiates(parent_body: str, child: str) -> bool:
    """True iff `parent_body` instantiates module `child` (best-effort,
    comment/string-stripped). Reuses the runner's instantiation grammar."""
    return _rcv_instantiates(parent_body, child)


def _rcv_instantiates(body: str, child: str) -> bool:
    # `<child> <inst_name> (` — the standard Verilog instantiation, optionally
    # with a `#(...)` parameter override before the instance name.
    pat = re.compile(
        rf"\b{re.escape(child)}\b\s*(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\(")
    return bool(pat.search(body))


def _module_body(txt: str, module: str) -> str:
    """Comment/string-stripped body text between `module <module>` and its
    matching `endmodule` (best-effort)."""
    s = _strip(txt)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", s)
    if not m:
        return ""
    me = re.search(r"\bendmodule\b", s[m.end():])
    return s[m.end():m.end() + me.start()] if me else s[m.end():]


def resolve_tb_facing_file(rtl_dir: Path, leaf: str,
                           spec_module: Optional[str] = None
                           ) -> Tuple[Optional[Path], Optional[str], str]:
    """Resolve (file, tb_facing_top, note) — the COMPLETE RTL file to export and
    the module name the hidden TB binds against.

    Selection rule (deterministic):
      1. If any `*__rcvar_inner` module exists, the TB-facing top is its WRAPPER
         (the same name minus the suffix). Export THAT wrapper's FILE — it
         carries both wrapper and inner core in one file (#518).
      2. Else prefer the spec-stated module name, else the leaf. Its whole file
         is exported verbatim (it may legitimately span several modules — e.g. a
         #517 leaf-typo synonym wrapper + its core).
    Returns (None, None, note) when no candidate module is found."""
    if not rtl_dir.is_dir():
        return (None, None, f"no rtl/ directory at {rtl_dir}")
    mods = _file_modules(rtl_dir)
    if not mods:
        return (None, None, f"no Verilog modules under {rtl_dir}")

    # 1. reset/clock variant-alias wrapper (#518) — the TB-facing top is the
    #    wrapper exposing the canonical reset/clock spelling.
    inners = [m for m in mods if m.endswith(RCVAR_INNER_SUFFIX)]
    for inner in sorted(inners):
        wrapper = inner[: -len(RCVAR_INNER_SUFFIX)]
        if wrapper in mods:
            wf, _wtxt = mods[wrapper]
            return (wf, wrapper,
                    f"reset/clock variant-alias wrapper {wrapper!r} (inner "
                    f"{inner!r}) is the TB-facing top; exporting its complete "
                    f"file verbatim")

    # 2. spec/leaf module — whole file verbatim.
    for cand in (spec_module, leaf):
        if cand and cand in mods:
            cf, _ctxt = mods[cand]
            return (cf, cand,
                    f"spec/leaf top {cand!r}; exporting its complete file "
                    f"verbatim")

    # 3. fall-back: a single-author-leaf project whose top differs from the leaf
    #    name. Prefer a module that is NOT instantiated by any other (a root).
    roots = [m for m in mods
             if not any(_instantiates(_module_body(t, p), m)
                        for p, (_f, t) in mods.items() if p != m)]
    if len(roots) == 1:
        rf, _rtxt = mods[roots[0]]
        return (rf, roots[0],
                f"single instantiation-root {roots[0]!r} (leaf {leaf!r} not a "
                f"declared module); exporting its complete file verbatim")
    return (None, None,
            f"could not unambiguously resolve a TB-facing top in {rtl_dir} "
            f"(modules={sorted(mods)}); refusing to guess")


def _iverilog_available() -> bool:
    try:
        return subprocess.run(["which", "iverilog"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def guard_export(sample: Path) -> Tuple[bool, List[str]]:
    """Post-export guard (chip-AGNOSTIC, structural). Returns (ok, problems).

    Checks:
      A. STANDALONE compile — `iverilog -g2012` the sample alone (no TB). It must
         compile; an export that dropped a wrapper's inner child fails "Unknown
         module type". Skipped (with a note) only when iverilog is unavailable.
      B. variant-alias COMPLETENESS — for every `*__rcvar_inner` present, its
         matching wrapper (same name minus the suffix) must ALSO be present, AND
         vice-versa: every wrapper that instantiates a `*__rcvar_inner` must ship
         that inner. A wrapper-without-inner OR inner-without-wrapper is rejected.
    """
    problems: List[str] = []
    if not sample.is_file():
        return (False, [f"sample not written: {sample}"])
    txt = sample.read_text(errors="replace")
    present = set(_module_names(txt))

    # B. variant-alias completeness (structural; runs even without iverilog).
    inners = {m for m in present if m.endswith(RCVAR_INNER_SUFFIX)}
    for inner in sorted(inners):
        wrapper = inner[: -len(RCVAR_INNER_SUFFIX)]
        if wrapper not in present:
            problems.append(
                f"incomplete export: inner core {inner!r} is present but its "
                f"alias wrapper {wrapper!r} (the TB-facing top) was DROPPED — "
                f"the hidden TB binds the wrapper's canonical port and will "
                f"COMPILE-ERROR against the bare inner")
    # vice-versa: an alias wrapper that instantiates a `*__rcvar_inner` but ships
    # without it (Unknown module type at scoring).
    for mod in sorted(present):
        body = _module_body(txt, mod)
        for inner in sorted(inners | {f"{mod}{RCVAR_INNER_SUFFIX}"}):
            if inner != mod and _instantiates(body, inner) and inner not in present:
                problems.append(
                    f"incomplete export: wrapper {mod!r} instantiates inner "
                    f"{inner!r} which is NOT in the exported file — scorer hits "
                    f"'Unknown module type: {inner}'")

    # A. standalone compile. An unavailable tool is a NOTE, never a hard FAIL —
    # the structural completeness check (B) still governs the verdict.
    notes: List[str] = []
    if _iverilog_available():
        with tempfile.TemporaryDirectory() as td:
            binp = Path(td) / "syn.bin"
            r = subprocess.run(
                ["iverilog", "-g2012", "-o", str(binp), str(sample)],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                problems.append(
                    "standalone iverilog -g2012 compile FAILED — the exported "
                    "file does not elaborate on its own (likely a dropped "
                    f"wrapper/child): {(r.stdout + r.stderr).strip()[-400:]}")
    else:
        notes.append(
            "NOTE: iverilog unavailable — standalone-compile check skipped "
            "(structural completeness check still enforced)")
    return (not problems, problems + notes)


def export(rtl_dir: Path, leaf: str, samples_dir: Path,
           spec_module: Optional[str] = None) -> dict:
    """Deterministic Shape-B export. Returns a result dict; writes
    `samples/<leaf>.v` verbatim on a passing guard. Never mutates rtl_dir."""
    src, top, note = resolve_tb_facing_file(rtl_dir, leaf, spec_module)
    if src is None:
        return {"verdict": "FAIL", "reason": "no_tb_facing_top", "note": note,
                "exported": None}
    samples_dir.mkdir(parents=True, exist_ok=True)
    dst = samples_dir / f"{leaf}.v"
    dst.write_text(src.read_text(errors="replace"))
    ok, problems = guard_export(dst)
    if not ok:
        # The guard FAILed — REJECT: do not leave a broken sample that scores as
        # a false-green gate. Remove it so the scorer reports no_sample (honest)
        # rather than compile_error on a half-shipped file.
        try:
            dst.unlink()
        except OSError:
            pass
        return {"verdict": "FAIL", "reason": "guard_rejected",
                "tb_facing_top": top, "source_file": str(src),
                "note": note, "problems": problems, "exported": None}
    return {"verdict": "PASS", "tb_facing_top": top,
            "source_file": str(src), "note": note,
            "exported": str(dst),
            "guard_notes": [p for p in problems if p.startswith("NOTE:")]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", help="per-design Path-A project "
                    "(<RUNDIR>/work/<leaf>); rtl_dir resolved via _path_layout")
    ap.add_argument("--rtl-dir", help="runner RTL dir (overrides --project)")
    ap.add_argument("--leaf", required=True,
                    help="design leaf (last path component of <design>); the "
                         "sample is written to <samples>/<leaf>.v")
    ap.add_argument("--samples", required=True,
                    help="<RUNDIR>/samples destination dir")
    ap.add_argument("--module", default=None,
                    help="optional spec-stated module name (RTLLM 'Module "
                         "name:' line); preferred over the bare leaf when no "
                         "alias wrapper is present")
    ap.add_argument("--json", default=None, help="write the result dict here")
    a = ap.parse_args(argv)

    if a.rtl_dir:
        rtl_dir = Path(a.rtl_dir)
    elif a.project:
        rtl_dir = _pl.rtl_dir(Path(a.project))
    else:
        print("error: pass --rtl-dir or --project", file=sys.stderr)
        return 2

    res = export(rtl_dir, a.leaf, Path(a.samples), a.module)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
