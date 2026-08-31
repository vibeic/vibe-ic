#!/usr/bin/env python3
"""The auto-emitted chip_top copied the vendor defaults, so a stated value had no way in.

MEASURED DEFECT
===============
`design_one_shot_runner._autoemit_chip_top_wrapper` copies the DUT's
``#(parameter ...)`` header VERBATIM — defaults included — and then propagates
each name to the instance as ``.P(P)``. So the vendor default is always what
gets built.

Measured on a staged-vendor-RTL IC: the brief disabled a security parameter,
the wrapper emitted ``SecMasking = 1`` anyway, and synthesis aborted on the
variant that default selects — a module the corpus excludes ON PURPOSE.
``grep -rn chparam programs/`` is 0 hits, so this wrapper is the flow's only
lever.

THE LINE THIS MUST NOT CROSS
============================
#586 refuses to pick a variant for the operator — "Choosing a different PRESENT
variant would silently rewrite a parameter selection and is NOT done" — and
that refusal must survive. It is about the flow choosing for ITSELF. Here the
input NAMES the parameter and the value. Honouring a stated instruction is the
opposite of guessing, and nothing is inferred: an entry that is not marked as
an override must change nothing, and an override naming a parameter the DUT
does not declare must be recorded, never applied elsewhere. Both are pinned
below.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _path_layout as _pl  # noqa: E402
import design_one_shot_runner as D  # noqa: E402

BLOCK = """#(
  parameter bit          AES192Enable = 1,
  parameter bit          SecMasking   = 1,
  parameter sbox_impl_e  SecSBoxImpl  = SBoxImplDom
)"""


def _project(tmp_path: Path, params) -> Path:
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"parameters": params}))
    return tmp_path


def test_a_stated_override_rewrites_the_copied_default(tmp_path):
    project = _project(tmp_path, [
        {"name": "SecMasking", "value": "0", "override": True}])

    block, applied, unapplied = D._apply_l8_param_overrides(project, BLOCK)

    assert applied == {"SecMasking": "0"}
    assert unapplied == {}
    assert "SecMasking   = 0" in block, (
        "the wrapper still carries the vendor default, so the build ignores "
        "what the design input stated")
    assert "AES192Enable = 1" in block, "an untargeted parameter must not move"


def test_an_entry_not_marked_override_changes_nothing(tmp_path):
    """A DOCUMENTED DEFAULT must never rewrite the header."""
    project = _project(tmp_path, [
        {"name": "SecMasking", "value": "9", "default": "1"}])

    block, applied, unapplied = D._apply_l8_param_overrides(project, BLOCK)

    assert applied == {} and unapplied == {}
    assert "SecMasking   = 1" in block


def test_an_override_the_dut_does_not_declare_is_recorded_not_applied(tmp_path):
    project = _project(tmp_path, [
        {"name": "SecMasking", "value": "0", "override": True},
        {"name": "NoSuchParam", "value": "7", "override": True}])

    block, applied, unapplied = D._apply_l8_param_overrides(project, BLOCK)

    assert applied == {"SecMasking": "0"}
    assert unapplied == {"NoSuchParam": "7"}, (
        "an override for a parameter this DUT does not declare must be "
        "reported, never silently dropped and never applied elsewhere")
    assert "NoSuchParam" not in block


def test_an_absent_layer_is_a_no_op(tmp_path):
    block, applied, unapplied = D._apply_l8_param_overrides(tmp_path, BLOCK)
    assert (block, applied, unapplied) == (BLOCK, {}, {})
