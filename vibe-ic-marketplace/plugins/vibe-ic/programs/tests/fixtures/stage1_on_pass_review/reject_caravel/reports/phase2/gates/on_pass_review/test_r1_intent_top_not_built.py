#!/usr/bin/env python3
"""AUTO-EMITTED by `stage_on_pass_review` from a stage-stage1 ON-PASS review rejection.

    the intent names top module 'caravel_user_project' ('l1_ic_name_fallback', no_top_module_in_input=False), and the stage's own RTL declares 3 module(s), none of them 'caravel_user_project' (counter, user_proj_example, user_project_wrapper). 1 stage report(s) stamp design_identity.top='caravel_user_project', so the stage certifies a subject this design does not contain.

This test FAILS while that is true of this run tree and PASSES once it is
repaired. It reads only this run's own INTENT and ARTEFACT — no oracle, no
harness, no golden — and it re-derives nothing: it runs no tool and rebuilds no
artefact.

REPAIR is one of exactly two things, and which one is a design decision this
test does not make:
  * the stage builds the module the intent names, or
  * the intent is corrected to name the module the design actually tops out
    at, and the 1 report(s) carrying design_identity.top are
    regenerated from it.
"""
import json
import re
import sys
from pathlib import Path

INTENT_REL = 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
RTL_RELS = ['phase2/stage1/rtl']
_MODULE_RE = re.compile(r"(?m)^[ \t]*module\s+([A-Za-z_]\w*)")


def run_root() -> Path:
    for d in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
        if (d / "phase1" / "generated_docs").is_dir():
            return d
    raise AssertionError("no run root above %s" % __file__)


def test_the_intent_names_a_top_module_this_run_actually_builds():
    root = run_root()
    intent = json.loads((root / INTENT_REL).read_text(encoding="utf-8",
                                                      errors="replace"))
    declared = intent.get("top_module")
    modules = set()
    for rel in RTL_RELS:
        d = root / rel
        if not d.is_dir():
            continue
        for ext in ("*.v", "*.sv", "*.vh", "*.svh"):
            for f in sorted(d.glob(ext)):
                modules |= set(_MODULE_RE.findall(
                    f.read_text(encoding="utf-8", errors="replace")))
    assert modules, (
        "%s staged no readable module; this test refutes nothing over an empty "
        "artefact" % ", ".join(RTL_RELS))
    assert declared, "%s declares no top_module" % INTENT_REL
    assert declared in modules, (
        "%s declares top_module=%r and this run builds %d module(s), none of "
        "them %r: %s" % (INTENT_REL, declared, len(modules), declared,
                         ", ".join(sorted(modules))))


if __name__ == "__main__":
    try:
        test_the_intent_names_a_top_module_this_run_actually_builds()
    except AssertionError as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS: the intent names a top module this run builds")
