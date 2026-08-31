#!/usr/bin/env python3
"""plugin_full_audit.py — deterministic D1 + D2 of the "have full test" audit.

Captured from the recurring 3-dimension audit (the user's standing "have full
test → full test + D1 + D2 + D3" request). The DETERMINISTIC dimensions live
here as a program (program-first doctrine); the full-test-audit SKILL invokes
this for D1+D2, runs the pytest suite + chip-AGNOSTIC guard for "full test", and
fans out the D3 skill-program-extractability audit (the irreducible LLM-judgment
dimension).

D1 — every program has a test:
  Every programs/*.py (non-helper) must be referenced by some programs/tests/
  test (dedicated test_<name>.py, import, invoke, or named). A *_protocol_synth
  is covered generically by test_all_protocol_synth_overlay.py and is reported
  separately (not a gap). Any OTHER unreferenced program is a D1 gap.

D2 — every step has a compliance checker:
  (a) no anti-fabrication self-assertion gate hole (delegates to
      gate_self_assertion_check.py);
  (b) the test tree is a single declared tree (delegates to
      single_testpath_guard.py);
  (c) every flow-YAML step's gate is more than file-presence — a files_exist-
      only gate is a gap UNLESS the step block carries an explicit
      "AUDIT NOTE (by-design" marker (substance verified downstream);
  (d) every program_exit_zero gate target exists on disk (no dangling ref).

Usage:
    python3 plugin_full_audit.py [<plugin_root>] [--json <out>]
Exit: 0 = D1 + D2 both clean / 1 = a real gap found / 2 = plugin_root not found.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _is_program(p: Path) -> bool:
    n = p.name
    return n.endswith(".py") and not n.startswith("__") and "/test" not in str(p)


def audit_d1(plugin: Path) -> dict:
    progs_dir = plugin / "programs"
    progs = [p.stem for p in progs_dir.glob("*.py")
             if not p.name.startswith("__")]
    test_blob = "\n".join(
        t.read_text(encoding="utf-8", errors="ignore")
        for t in (progs_dir / "tests").rglob("test_*.py"))

    # ONE PASS INSTEAD OF ONE SCAN PER PROGRAM (vibe-ic#1208).
    #
    # `referenced` is a pure OR of four conditions, so their ORDER cannot change
    # its result -- only its cost. It used to run up to three regex searches
    # over `test_blob` FOR EVERY PROGRAM. Measured on this tree: the blob is
    # 23,559,035 chars, one search over it costs 0.127 s, 374 programs reach the
    # regexes, and `plugin_full_audit` as a whole took 169.47 s of which the
    # profiler attributed 99.5% to `re.Pattern.search`.
    #
    # `\b<s>\b` asks exactly "is s a MAXIMAL run of word characters somewhere in
    # the blob", so the whole population of such runs can be collected in one
    # pass and answered by set membership. The equivalence needs s to be
    # word-characters-only, which is a property of the names this audit walks
    # (python module stems) and is ASSERTED below rather than assumed -- a stem
    # containing `-` or `.` would make the set answer a different question, and
    # falling back to the search keeps that case exact instead of wrong.
    #
    # The two remaining patterns are kept and still run, unchanged, for the
    # programs the set does not resolve. `{s}\.py\b` genuinely is not implied by
    # `\b{s}\b` -- it has no leading boundary, so it matches inside `myfoo.py`
    # where the word form does not -- and that is precisely why it is not folded
    # in here.
    _WORD = re.compile(r"\w+")
    _words = frozenset(_WORD.findall(test_blob))

    def referenced(s: str) -> bool:
        if (progs_dir / "tests" / f"test_{s}.py").exists():
            return True
        if _WORD.fullmatch(s):
            if s in _words:          # == re.search(rf"\b{re.escape(s)}\b", blob)
                return True
        elif re.search(rf"\b{re.escape(s)}\b", test_blob):
            return True
        if re.search(rf"\b(?:import|from)\s+{re.escape(s)}\b", test_blob):
            return True
        return bool(re.search(rf"{re.escape(s)}\.py\b", test_blob))

    untested = [s for s in progs if not referenced(s)]
    synth = sorted(s for s in untested if s.endswith("_protocol_synth"))
    gaps = sorted(s for s in untested if not s.endswith("_protocol_synth"))
    return {"total_programs": len(progs),
            "synth_overlay_covered": synth,
            "untested_gaps": gaps,
            "passed": not gaps}


def _walk_steps(doc):
    if isinstance(doc, dict):
        if isinstance(doc.get("steps"), list):
            return doc["steps"]
        for v in doc.values():
            r = _walk_steps(v)
            if r:
                return r
    return []


def audit_d2(plugin: Path) -> dict:
    progs_dir = plugin / "programs"
    findings = []

    # (a) + (b) + (e): delegate to the dedicated guards.
    #
    # vibe-ic#220 — a guard that COULD NOT RUN is not a clean guard. This loop
    # used to record a finding only on returncode 1, so a guard exiting 2
    # ("flow YAML not found", the operational tier) was indistinguishable from
    # one that ran and found nothing. Combined with the plugin-directory
    # argument these guards are invoked with, that made
    # gate_self_assertion_check inert here — silently — which is exactly the
    # self-disabling shape #220 is about, one level up from the flow YAML.
    for guard in ("gate_self_assertion_check", "single_testpath_guard",
                  "flow_condition_reachability_check"):
        gp = progs_dir / f"{guard}.py"
        if gp.is_file():
            r = subprocess.run([sys.executable, str(gp), str(plugin)],
                               capture_output=True, text=True)
            if r.returncode == 1:
                # THE WHOLE FINDING, not its first 300 characters.
                #
                # This used to be `r.stdout.strip()[:300]`, and the cap did not
                # trim decoration — it deleted the build-failing half of the
                # finding. `flow_condition_reachability_check` prints its
                # KNOWN-OPEN (baselined, reported-not-blocking) section FIRST and
                # its hard `FAIL: N NEW self-disabling condition(s)` section
                # SECOND. MEASURED on origin/main c9dacb8275: the guard exited 1
                # because of a NEW hole at step 23, and BOTH the console line and
                # the --json report showed only the DT2 known-open, cut off
                # mid-sentence at "flow-YAML". An operator reading this audit saw
                # a non-blocking entry and no sign of the blocking one.
                #
                # A truncated FAIL is the same defect class D2 exists to catch,
                # one level up: the report that would have told you is the thing
                # that went quiet. The full stdout is kept, and the console
                # renderer below indents it so multi-line findings stay readable.
                findings.append({"check": guard,
                                 "detail": r.stdout.strip(),
                                 "exit_code": r.returncode})
            elif r.returncode != 0:
                findings.append({
                    "check": guard,
                    "exit_code": r.returncode,
                    "detail": (f"guard could not run (exit {r.returncode}) — a "
                               f"guard that did not execute is NOT a pass: "
                               f"{(r.stderr or r.stdout).strip()}")})
        else:
            findings.append({"check": guard, "detail": "guard program missing"})

    # (c) + (d): scan the flow YAML
    flow = plugin / "flow" / "phase1_phase2_phase3.yaml"
    presence_only = []
    dangling = []
    if flow.is_file():
        import yaml
        text = flow.read_text()
        doc = yaml.safe_load(text)
        steps = _walk_steps(doc)
        # split the raw text into per-step blocks to look for the by-design note
        blocks = re.split(r"^  - id:", text, flags=re.M)
        block_by_id = {}
        for b in blocks:
            m = re.match(r"\s*(\S+)", b)
            if m:
                block_by_id[m.group(1).strip()] = b
        for st in steps:
            if not isinstance(st, dict):
                continue
            g = st.get("gate")
            if not g:
                continue
            gs = json.dumps(g)
            if ("files_exist" in gs and "program_exit_zero" not in gs
                    and "json_field_true" not in gs):
                blk = block_by_id.get(str(st.get("id")), "")
                if "AUDIT NOTE (by-design" not in blk:
                    presence_only.append(st.get("id"))
        # (d) dangling program_exit_zero targets
        cmds = set(re.findall(r'program_exit_zero:\s*"(\w+)', text)) | \
            set(re.findall(r'command:\s*"(\w+)', text))
        dangling = sorted(c for c in cmds if not (progs_dir / f"{c}.py").is_file())
    if presence_only:
        findings.append({"check": "file_presence_only_gate",
                         "detail": f"steps gated on files_exist only, no "
                         f"by-design AUDIT NOTE: {presence_only}"})
    if dangling:
        findings.append({"check": "dangling_gate_target",
                         "detail": f"program_exit_zero targets missing on disk: "
                         f"{dangling}"})
    return {"findings": findings, "passed": not findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plugin_root", nargs="?", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    plugin = Path(a.plugin_root) if a.plugin_root else \
        Path(__file__).resolve().parent.parent
    if not (plugin / "programs").is_dir():
        print(f"SKIP: no programs/ under {plugin}", file=sys.stderr)
        return 2

    d1 = audit_d1(plugin)
    d2 = audit_d2(plugin)
    passed = d1["passed"] and d2["passed"]
    report = {"audit": "plugin_full_audit", "passed": passed,
              "D1_program_test_coverage": d1, "D2_step_compliance_checker": d2,
              "note": "D3 (skill program-extractability) is the LLM-judgment "
                      "dimension — run via the full-test-audit skill workflow."}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")

    print("D1 program-test-coverage: "
          + ("PASS" if d1["passed"]
             else f"FAIL — untested non-synth programs: {d1['untested_gaps']}"))
    print(f"   ({d1['total_programs']} programs; "
          f"{len(d1['synth_overlay_covered'])} synth overlay-covered)")
    print("D2 step-compliance-checker: "
          + ("PASS" if d2["passed"] else "FAIL"))
    for f in d2["findings"]:
        # Multi-line details are printed whole and indented under their check,
        # rather than clipped to one line — see the note at the truncation site.
        _lines = str(f["detail"]).splitlines() or [""]
        print(f"   - {f['check']}: {_lines[0]}")
        for _l in _lines[1:]:
            print(f"     {_l}")
    print("=> deterministic audit " + ("PASS" if passed else "FAIL")
          + " (D3 = run the full-test-audit skill for the skill-extractability dimension)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
