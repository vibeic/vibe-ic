#!/usr/bin/env python3
"""A gate cannot convict a layer of being undeclared when it read no declarations.

THE MEASURED DEFECT, on a real routed tree at v1.13.69. `macro_obs_load_parity_check`
resolves an OBS layer by asking whether any LEF it read DECLARES that layer. The file
that declares layers is the TECH LEF; a macro abstract declares none. When the PDK is
MOUNTED in the container — the normal case for this flow, where the tech LEF lives at
`/foss/pdks/...` and never enters the project — the gate's project-relative glob finds
only the generated hardmacro abstract, reads ZERO layer declarations, and then reports
every OBS layer as unresolvable:

    [FAIL] 1 macro(s) declare obstruction geometry that a reader CANNOT LOAD —
    82 of 82 parsed OBS rect(s) would be discarded ...
    NOT declared by any LEF read: Nwell, Metal1, Metal2, Metal3, Metal4, Metal5

Every one of those layers IS declared, by the tech LEF the run actually loaded. Handing
the gate that same file turns the run green with 0 lost. So rc=1 there was a statement
about the gate's search scope wearing the costume of a statement about the layout.

SECOND FACET, same scope. `discover_lefs` globbed `*.lef` only. A tech LEF is
conventionally `<lib>__nom.tlef`, so even a design that VENDORS one under `input/pdk/`
— the remedy this gate prints — was still invisible to it.

WHAT CHANGES AND WHAT DOES NOT. An empty declaration set now returns rc=2 (the question
could not be put), never rc=1. Everything else is untouched, and the tests below assert
that in both directions:

    the LEF set declares layers, one OBS layer is missing from it   -> rc=1  (unchanged)
    the LEF set declares every OBS layer                            -> rc=0  (unchanged)
    the set is empty BUT the reader's own log names the lost layer  -> rc=1  (unchanged)

That last row is the one that keeps this fix honest. This gate has two legs and only the
STATIC one depends on the declaration set; when the reader itself announced the loss, the
loss was OBSERVED and the static leg's blindness is irrelevant. So the measured leg keeps
its rc=1 and the new branch stands aside for it.

EXIT CODES ARE THE SUBJECT HERE, so every assertion is on a returncode from a real
subprocess: rc=0 pass, rc=1 the finding, rc=2 the question could not be put. rc=2 is not
a result and is never a pass.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _hostpaths  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_GATE = _PROGRAMS / "macro_obs_load_parity_check.py"

# ---------------------------------------------------------------- fixtures
# Synthesized neutral data. No design, PDK or vendor name appears: the layer
# names are invented and the rule under test is "referenced but not declared",
# so which names they are cannot matter.
_MACRO_LEF = """VERSION 5.8 ;

MACRO block_a
  CLASS BLOCK ;
  SIZE 40.000 BY 40.000 ;
  OBS
    LAYER metalA ;
      RECT 0.500 0.500 39.500 0.800 ;
      RECT 0.500 1.100 39.500 1.400 ;
  END
END block_a

END LIBRARY
"""


def _tech_lef(*layers: str) -> str:
    body = "".join(f"LAYER {ly}\n  TYPE ROUTING ;\nEND {ly}\n\n" for ly in layers)
    return "VERSION 5.8 ;\n\n" + body + "END LIBRARY\n"


def _project(tmp_path: Path, *, tech: str | None = None,
             tech_name: str = "tech.lef", log: str | None = None) -> Path:
    """A project shaped the way the flow shapes one: the abstract under
    `phase3/stage4/hardmacro/`, the tech LEF (when the design vendors one)
    under `input/pdk/`."""
    root = tmp_path / "proj"
    hard = root / "phase3" / "stage4" / "hardmacro"
    hard.mkdir(parents=True)
    (hard / "blk.lef").write_text(_MACRO_LEF)
    if tech is not None:
        pdk = root / "input" / "pdk"
        pdk.mkdir(parents=True)
        (pdk / tech_name).write_text(tech)
    if log is not None:
        (root / "run.log").write_text(log)
    return root


def _rc(project: Path, *extra: str) -> int:
    """The gate's OWN exit code. Not a pipeline's, and not a later command's."""
    proc = subprocess.run(
        [sys.executable, str(_GATE), str(project), *extra],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode not in (143, 199), (
        f"rc={proc.returncode} is a KILL, not a result: {proc.stderr[-400:]}")
    return proc.returncode


def _stderr(project: Path) -> str:
    return subprocess.run(
        [sys.executable, str(_GATE), str(project)],
        capture_output=True, text=True, timeout=300).stderr


# ------------------------------------------------------- the defect itself
def test_an_empty_declaration_set_is_a_question_that_could_not_be_put(tmp_path):
    """THE REGRESSION. Pre-fix this returns 1 — a finding about geometry the gate
    had no means to resolve. It must be 2."""
    rc = _rc(_project(tmp_path))
    assert rc == 2, (
        f"gate returned rc={rc} on a project whose only LEF is a macro abstract; "
        "with zero layer declarations read, 'referenced but not declared' is true "
        "of every layer by construction, so this is rc=2 (could not determine), "
        "never rc=1 (a finding)")


def test_the_refusal_names_the_file_that_would_answer_it(tmp_path):
    """DEGRADE LOUDLY. A refusal that does not say what is missing sends the
    reader to the layout, which is where the answer is not."""
    log = ("[INFO ODB-0227] LEF file: /somewhere/pdk/libname__nom.tlef, "
           "created 15 layers, 56 vias\n")
    err = _stderr(_project(tmp_path, log=log))
    assert "CANNOT DETERMINE" in err, err
    assert "/somewhere/pdk/libname__nom.tlef" in err, (
        "the refusal must NAME the tech LEF the run's own log records loading; "
        f"got: {err}")
    assert "--lef" in err and "input/pdk/" in err, (
        f"the refusal must state both remedies; got: {err}")


def test_a_tlef_suffix_is_discovered(tmp_path):
    """SECOND FACET. A vendored tech LEF is conventionally `*.tlef`. If discovery
    cannot see that suffix, the remedy the gate prints does not work."""
    rc = _rc(_project(tmp_path, tech=_tech_lef("metalA"), tech_name="lib__nom.tlef"))
    assert rc == 0, (
        f"rc={rc}: a vendored `*.tlef` declaring the OBS layer must be read and "
        "must clear the finding")


# ------------------------- CONTROLS: green before AND after, or the fix is a mute
def test_a_genuinely_undeclared_layer_still_fires(tmp_path):
    """CONTROL. The declaration set is NOT empty and the OBS layer is missing from
    it — the real defect this gate exists for. Unchanged in both arms."""
    rc = _rc(_project(tmp_path, tech=_tech_lef("cutA")))
    assert rc == 1, (
        f"rc={rc}: with a non-empty declaration set that omits the OBS layer, the "
        "finding must still fire — this fix must not have muted the gate")


def test_a_complete_lef_set_still_passes(tmp_path):
    """CONTROL. Unchanged in both arms."""
    rc = _rc(_project(tmp_path, tech=_tech_lef("metalA")))
    assert rc == 0, f"rc={rc}: every OBS layer is declared; this is a pass"


def test_a_log_corroborated_loss_survives_an_empty_declaration_set(tmp_path):
    """CONTROL, and the one that keeps the fix honest. The static leg is blind
    here, but the reader ANNOUNCED the loss, so it was measured and the finding
    stands. Unchanged in both arms."""
    log = "[WARNING ODB-0176] error: undefined layer (metalA) referenced\n"
    rc = _rc(_project(tmp_path, log=log))
    assert rc == 1, (
        f"rc={rc}: the reader's own diagnostic names the lost layer, so the loss "
        "is measured and does not depend on this gate's static set")


def test_explicit_lef_still_answers_when_the_pdk_is_mounted(tmp_path):
    """CONTROL. The documented remedy for a mounted PDK — hand the gate the file
    — works in both arms, so the fix cannot be credited with it."""
    tech = tmp_path / "outside_the_project__nom.tlef"
    tech.write_text(_tech_lef("metalA"))
    proj = _project(tmp_path)
    assert _rc(proj, "--lef", str(proj / "phase3/stage4/hardmacro/blk.lef"),
               "--lef", str(tech)) == 0, (
        "with the tech LEF supplied explicitly, the same project resolves")


def test_without_that_file_the_same_project_cannot_be_judged(tmp_path):
    """THE DEFECT, stated as the other half of the control above: the SAME project
    minus the explicitly-supplied tech LEF must refuse, not convict."""
    rc = _rc(_project(tmp_path))
    assert rc == 2, (
        f"rc={rc}: the project is identical to the one that passes when the tech "
        "LEF is supplied; without it the gate has read nothing that could resolve "
        "a layer, so this is a refusal, not a finding")


# ------------------------------------------------- backed by a real artefact
def test_a_shipped_macro_abstract_declares_no_layers():
    """REAL ARTEFACT (§4). The premise of this whole fix, read off a checked-in
    file rather than a fixture authored alongside it: a macro abstract declares
    zero layers, so a LEF set consisting only of abstracts can never resolve one."""
    lef = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "l21_hollow_power_intent", "phase3", "analog", "hardmacro",
        "m_supply_probe", "m_supply_probe.lef")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mo_parity", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    declared = mod.declared_layers(lef.read_text())
    assert declared == set(), (
        f"a shipped macro abstract declared {sorted(declared)}; the premise of "
        "this fix is that abstracts declare no layers")


def test_no_run_root_is_convicted_by_an_empty_declaration_set(tmp_path):
    """CORPUS SWEEP (§2), when a corpus is configured. rc=1 is legitimate ONLY
    when the gate actually read some layer declarations. A conviction whose own
    record says `layer_declarations_absent` is the false alarm this fix removes,
    so the sweep asserts that set is empty."""
    import json as _json
    root = _hostpaths.corpus_root()
    if root is None:
        pytest.skip("set $VIBEIC_CORPUS_ROOT to a tree of run roots to sweep")
    roots = [p for p in sorted(root.glob("*")) if p.is_dir()][:24]
    roots += [p for p in sorted(root.glob("*/*")) if p.is_dir()][:24]
    if not roots:
        pytest.skip(f"no run roots under {root}")
    swept, blind_convictions = 0, []
    for i, r in enumerate(roots):
        out = tmp_path / f"rep{i}.json"
        proc = subprocess.run(
            [sys.executable, str(_GATE), str(r), "--json", str(out)],
            capture_output=True, text=True, timeout=600)
        assert proc.returncode not in (143, 199), (
            f"rc={proc.returncode} on {r} is a KILL, not a result")
        swept += 1
        if proc.returncode == 1 and out.is_file():
            rep = _json.loads(out.read_text())
            if rep.get("layer_declarations_absent") and not rep.get(
                    "undefined_layers_in_tool_log"):
                blind_convictions.append(str(r))
    assert swept, "the sweep read nothing, so it measured nothing"
    assert not blind_convictions, (
        "these run roots were convicted while the gate had read ZERO layer "
        f"declarations and no tool diagnostic: {blind_convictions}")
