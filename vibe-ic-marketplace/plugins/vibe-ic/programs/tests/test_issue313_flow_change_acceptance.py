#!/usr/bin/env python3
"""ORGANIC #313 — the flow-change acceptance standard, extracted INTO the
plugin, plus the program half of its §6.

The issue's own reasoning for filing it: the author first wrote these rules in
private notes, then judged that wrong — this is an open-source plugin, and a
standard that is not in the plugin does not exist for the people using it.

The program half here is `silent_decline_audit` (§6): a remedy that silently
declines is indistinguishable from a remedy that was never needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))
import silent_decline_audit as S  # noqa: E402

_SKILL = _PLUGIN / "skills" / "flow-change-acceptance"

_PRE_FIX = '''
def step():
    _lf = _route_feedback_loosen(w, h, log, i, a, d)
    if _lf is not None:
        w, h = _lf
'''
_AS_LANDED = '''
def step():
    _lf, _reason = _route_feedback_loosen_ex(w, h, log, i, a, d)
    if _lf is None:
        loosen_declines.append({"reason": _reason})
        print(f"ROUTE_LOOSEN_DECLINED reason={_reason}")
    if _lf is not None:
        w, h = _lf
'''


def test_313_detects_the_307_shape():
    """The exact pre-fix shape: a remedy refuses and nothing records it."""
    f = S.audit_source(_PRE_FIX, "x")
    assert len(f) == 1
    assert f[0]["remedy"] == "_route_feedback_loosen"
    assert "no else branch" in f[0]["why"]


def test_313_does_not_flag_the_fix_that_actually_landed():
    """FALSE-POSITIVE CONTROL, and the reason this matters: my first draft
    flagged the CORRECT #307 fix. §2 — a gate that fires on a legitimate state
    is a bug whose real cost is that people learn to ignore it."""
    assert S.audit_source(_AS_LANDED, "x") == []


def test_313_does_not_flag_disclosure_before_the_guard():
    """A real site (design_one_shot_runner eco_loop_remediation) records the
    decline BEFORE the guard:
        plan.append(StepResult(..., "PASS" if remediated else "SKIP", ...))
    The first draft flagged it; verified against the real file, then fixed."""
    src = '''
def step():
    remediated = _eco_remediate_with_hint(p, h)
    plan.append(StepResult("eco", "PASS" if remediated else "SKIP", 0.0, d))
    if remediated:
        go()
'''
    assert S.audit_source(src, "x") == []


def test_313_flags_an_else_that_says_nothing():
    src = '''
def step():
    _r = repair_attempt(x)
    if _r is not None:
        apply(_r)
    else:
        pass
'''
    f = S.audit_source(src, "x")
    assert len(f) == 1 and "discloses nothing" in f[0]["why"]


def test_313_accepts_an_else_that_discloses():
    src = '''
def step():
    _r = repair_attempt(x)
    if _r is not None:
        apply(_r)
    else:
        print("REPAIR_DECLINED")
'''
    assert S.audit_source(src, "x") == []


def test_313_scoped_to_remedy_semantics_not_every_optional():
    """Flagging every `if x is not None:` would produce exactly the noise §2
    warns about."""
    src = '''
def step():
    cfg = load_config(p)
    if cfg is not None:
        use(cfg)
'''
    assert S.audit_source(src, "x") == []


def test_313_runs_on_the_real_programs_dir_without_crashing():
    """Non-vacuous: it must survive the actual corpus, including files with
    syntax warnings, and return real sites."""
    files = sorted(p for p in _PROGRAMS.glob("*.py")
                   if not p.name.startswith("test_"))
    assert len(files) > 500
    rep = S.audit(files)
    assert rep["scanned"] == len(files)
    assert isinstance(rep["silent_declines"], list)


def test_313_skill_is_present_and_registered():
    """A standard that is not in the plugin does not exist for its users —
    the issue's own reason for filing."""
    import json
    assert (_SKILL / "SKILL.md").is_file()
    assert (_SKILL / "compliance.yaml").is_file()
    cls = json.loads((_PLUGIN / "skills" / "_classification.json").read_text())
    tier = cls["tiers"]["nl_primary"]
    names = tier["skills"] if isinstance(tier, dict) and "skills" in tier else tier
    assert "flow-change-acceptance" in names


def test_313_every_criterion_cites_its_measured_failure():
    """A standard without its scar is advice. Each section must name the issue
    it came from."""
    txt = (_SKILL / "SKILL.md").read_text()
    # The prose is the original author's (it narrates each failure in full);
    # the traceable issue ids were added on top so a reader can follow a
    # criterion back to the run that produced it.
    for issue in ("#295", "#298", "#306", "#307", "#309", "#312"):
        assert issue in txt, f"criterion set does not cite {issue}"
    # every criterion heading carries a provenance marker
    import re
    heads = re.findall(r"^### \d\.[^\n]*$", txt, re.M)
    assert len(heads) == 6, heads
    for h in heads:
        assert "measured:" in h or "enforced:" in h, h


def test_313_compliance_yaml_is_well_formed():
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load((_SKILL / "compliance.yaml").read_text())
    ids = [r["id"] for r in d["requirements"]]
    assert len(set(ids)) == len(ids)
    for r in d["requirements"]:
        assert r.get("evidence"), f"{r['id']} has no measured evidence"
