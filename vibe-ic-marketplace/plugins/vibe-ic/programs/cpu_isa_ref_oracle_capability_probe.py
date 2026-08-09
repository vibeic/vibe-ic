#!/usr/bin/env python3
"""cpu_isa_ref_oracle_capability_probe.py — MEASURE the premise of the
`cap:cpu_functional_oracle` waiver instead of assuming it.

THE AUDITED RESIDUAL
--------------------
`cpu_functional_oracle_waiver_check.py` grants a connectivity-PASS /
functional-DEFERRED waiver whenever the runner stamps `cap:cpu_functional_oracle`
on `phase2/stage1/sim/results.xml`. That token asserts a CAPABILITY GAP: "a
per-IC functional oracle cannot be constructed here."

Nothing in the flow ever checks whether that assertion is true.

For a `processor_cpu`-class IC the assertion is decidable, and for the whole
RISC-V family it is FALSE in the flow's own environment: an ISA REFERENCE
SIMULATOR is a golden. Given a reference simulator for the declared ISA plus a
cross toolchain, a differential oracle is constructible with no per-IC golden
vectors at all — compile firmware once, execute it on the reference model,
execute the same image on the DUT, compare the architectural result.

A waiver whose premise is false is not a waiver; it is a false negative that
books an unbuilt generator as an unbuildable capability. This program decides
the premise from MEASUREMENT:

  * which ISA family does the design DECLARE (read, never guessed)
  * is a reference simulator for that family present in the run's container
  * is a cross toolchain for that family present in the run's container

and writes the answer as a structural artifact. It emits no verdict about the
design and runs no simulation.

CHIP-AGNOSTIC BY CONSTRUCTION
-----------------------------
The only vocabulary here is ISA-FAMILY names and TOOL names — a capability
vocabulary, never a chip / vendor / SKU / node / part-number literal. Adding a
family means adding a row to `ISA_FAMILIES`, never a per-chip branch.

EXIT CODES
----------
  0 = CONSTRUCTIBLE — a reference-ISA differential oracle can be built for the
      declared ISA with tools measured present. `cap:cpu_functional_oracle` is
      a GENERATOR gap, not a capability gap, and must NOT be waived.
  2 = NOT_APPLICABLE — the design does not declare an ISA this program knows a
      reference model for (or is not a processor class). No claim is made; the
      existing waiver path is untouched.
  3 = CAPABILITY_CONFIRMED — the declared ISA family is known, but the tools
      are measured ABSENT in this environment. The capability gap is REAL and
      the waiver is licensed.
  1 = ERROR — the probe could not run (bad container, unreadable project).
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
GATE = "cpu_isa_ref_oracle_capability_probe"
CAP_TOKEN = "cap:cpu_functional_oracle"

#: ISA FAMILY -> the reference model and cross toolchain that make a
#: differential oracle constructible. A capability vocabulary: family names and
#: tool names only. Extend by adding a row, never by branching on a design.
ISA_FAMILIES = {
    "riscv32": {
        "declared_patterns": [r"\brv32[iemafdcg]", r"\briscv32\b", r"\brv32\b"],
        "reference_model": ["spike"],
        "toolchain": ["riscv64-unknown-elf-gcc", "riscv32-unknown-elf-gcc",
                      "riscv-none-elf-gcc", "riscv64-elf-gcc"],
        "reference_model_role":
            "executes the SAME firmware image and yields the architectural "
            "result the DUT must reproduce",
    },
    "riscv64": {
        "declared_patterns": [r"\brv64[iemafdcg]", r"\briscv64\b"],
        "reference_model": ["spike"],
        "toolchain": ["riscv64-unknown-elf-gcc", "riscv64-elf-gcc",
                      "riscv-none-elf-gcc"],
        "reference_model_role":
            "executes the SAME firmware image and yields the architectural "
            "result the DUT must reproduce",
    },
}

#: Files, in priority order, whose text is scanned for the DECLARED ISA. The
#: declaration is READ; it is never inferred from module or signal names.
_DECLARATION_SOURCES = (
    "plugin_output/declaration.json",
    "phase2/stage1/declaration_contract.json",
    "phase1/generated_docs/L2_ARCHITECTURE.json",
    "phase1/generated_docs/L1_PRODUCT_METADATA.json",
    "input/docs/L2_architecture.md",
    "input/docs/L1_product_metadata.md",
)


def _read_text(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except Exception:
        return ""


def declared_isa_family(project: Path):
    """Return (family, source_path, matched_text) or (None, None, None).

    Reads the design's own declaration. Returns the FIRST family whose declared
    pattern appears in the highest-priority source that mentions any of them, so
    a design that declares rv32 is never silently promoted to rv64.
    """
    for rel in _DECLARATION_SOURCES:
        p = project / rel
        if not p.is_file():
            continue
        txt = _read_text(p)
        if not txt:
            continue
        low = txt.lower()
        for fam, spec in ISA_FAMILIES.items():
            for pat in spec["declared_patterns"]:
                m = re.search(pat, low)
                if m:
                    return fam, rel, m.group(0)
    return None, None, None


def ic_class_of(project: Path) -> str:
    p = project / "reports" / "ic_class.json"
    if not p.is_file():
        return ""
    try:
        d = json.loads(_read_text(p))
    except Exception:
        return ""
    for k in ("ic_class", "class", "detected_class"):
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def probe_tool(container: str, tool: str):
    """Return (found, resolved_path). MEASURED inside the container."""
    cmd = ["docker", "exec", container, "bash", "-lc",
           "command -v %s || true" % shlex.quote(tool)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return False, ""
    out = [ln.strip() for ln in r.stdout.splitlines()
           if ln.strip().startswith("/")]
    return (bool(out), out[-1] if out else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--container", required=True,
                    help="running EDA container the run itself uses")
    ap.add_argument("--out", default=None,
                    help="default <project>/reports/phase2/gates/"
                         "cpu_isa_ref_oracle_capability.json")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("ERROR: project is not a directory: %s" % project)
        return 1
    out = Path(args.out) if args.out else (
        project / "reports" / "phase2" / "gates"
        / "cpu_isa_ref_oracle_capability.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    rep = {
        "_schema_version": SCHEMA_VERSION,
        "gate": GATE,
        "capability_token_under_test": CAP_TOKEN,
        "project": str(project),
        "container": args.container,
        "ic_class": ic_class_of(project),
    }

    fam, src, matched = declared_isa_family(project)
    rep["declared_isa_family"] = fam
    rep["declared_isa_source"] = src
    rep["declared_isa_match"] = matched

    if fam is None:
        rep["verdict"] = "NOT_APPLICABLE"
        rep["reason"] = (
            "no source under %s declares an ISA this probe knows a reference "
            "model for; this probe makes NO claim and leaves the existing "
            "%s path untouched" % (list(_DECLARATION_SOURCES), CAP_TOKEN))
        out.write_text(json.dumps(rep, indent=2) + "\n")
        print("NOT_APPLICABLE: %s" % rep["reason"])
        return 2

    spec = ISA_FAMILIES[fam]
    ref_found, ref_path, ref_name = False, "", ""
    for t in spec["reference_model"]:
        ok, path = probe_tool(args.container, t)
        if ok:
            ref_found, ref_path, ref_name = True, path, t
            break
    tc_found, tc_path, tc_name = False, "", ""
    for t in spec["toolchain"]:
        ok, path = probe_tool(args.container, t)
        if ok:
            tc_found, tc_path, tc_name = True, path, t
            break

    rep["reference_model"] = {
        "candidates": spec["reference_model"], "found": ref_found,
        "tool": ref_name, "path": ref_path, "role": spec["reference_model_role"]}
    rep["toolchain"] = {
        "candidates": spec["toolchain"], "found": tc_found,
        "tool": tc_name, "path": tc_path}

    if ref_found and tc_found:
        rep["verdict"] = "CONSTRUCTIBLE"
        rep["oracle_shape"] = (
            "differential: compile firmware once, execute it on %s, execute "
            "the SAME image on the DUT, compare the architectural result. "
            "Needs NO per-IC golden vectors." % ref_name)
        rep["reason"] = (
            "the declared ISA family is %r and both a reference model (%s) and "
            "a cross toolchain (%s) are MEASURED PRESENT in the run's own "
            "container. %s asserts a capability that is not missing: it is a "
            "GENERATOR gap. Waiving it books an unbuilt generator as an "
            "unbuildable capability." % (fam, ref_path, tc_path, CAP_TOKEN))
        out.write_text(json.dumps(rep, indent=2) + "\n")
        print("CONSTRUCTIBLE: %s" % rep["reason"])
        return 0

    rep["verdict"] = "CAPABILITY_CONFIRMED"
    missing = []
    if not ref_found:
        missing.append("reference model (any of %s)" % spec["reference_model"])
    if not tc_found:
        missing.append("cross toolchain (any of %s)" % spec["toolchain"])
    rep["reason"] = (
        "declared ISA family %r is known, but %s is absent from the container; "
        "the %s capability gap is REAL here and the waiver is licensed"
        % (fam, " and ".join(missing), CAP_TOKEN))
    out.write_text(json.dumps(rep, indent=2) + "\n")
    print("CAPABILITY_CONFIRMED: %s" % rep["reason"])
    return 3


if __name__ == "__main__":
    sys.exit(main())
