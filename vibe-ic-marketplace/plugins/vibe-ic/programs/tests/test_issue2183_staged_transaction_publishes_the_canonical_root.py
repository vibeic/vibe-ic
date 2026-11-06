"""The staging transaction remapped the StepResult and never the FILES.

#2158 found that `step_rtl_gen` snapshots the project into
`<TMPDIR>/vibeic-rtl-step-XXXX/<name>`, runs every generator against THAT root
and commits the delta back, and that the remap bringing paths home was
boundary-buggy. It repaired the boundary and applied the remap to
`result.detail`, `result.output_files` and `result.extras`.

Those three are the StepResult. They are not the files the transaction
publishes, and no remap ever reached those. So a generator that records its own
project root inside an artefact writes the scratch directory, and the commit
copies that string into the canonical tree — where it outlives the directory it
names. #2183 is that half, and it is the SAME root as #2158, not a third one:
one staging transaction, two halves, one of them covered.

MEASURED on `main` 2692e510fae5 by driving the real runner (lane cz2180, 8HD-9).
`step_rtl_gen` handed `/tmp/vibeic-rtl-step-1jyxxaff/demo_proj` to
`_stage_author_knowledge_digests` and to `spec_declaration_emit.stage_contract`,
and BOTH published artefacts came out carrying it:

    phase2/stage1/declaration_contract.json    "project": "/tmp/vibeic-rtl-step-…/demo_proj"
    phase2/stage1/lessons_scoring_record.json  "project": "/tmp/vibeic-rtl-step-…/demo_proj"

The property these tests hold to is not "the string equals the project root".
It is **the recorded root EXISTS when a reader opens the artefact** — which is
what a stale citation actually costs, and which a string comparison alone would
still satisfy if the transaction started recording some other dead path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R          # noqa: E402

_L_DOCS = {
    "L1_SPEC.json": {"fields": {"top_module": "demo_top"}},
    "L3_CMD_PROTOCOL.json": {"no_opcodes_in_input": True},
    "L6_CONTROL_LOGIC.json": {"fields": {}},
    "L8_RTL_CONSTANTS.json": {"fields": {}},
}

_PUBLISHED = (
    Path("phase2") / "stage1" / "declaration_contract.json",
    Path("phase2") / "stage1" / "lessons_scoring_record.json",
)


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "demo_proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(
        "# demo\nA register that captures an 8-bit input on a rising edge.\n")
    for name, body in _L_DOCS.items():
        (proj / "phase1" / "generated_docs" / name).write_text(json.dumps(body))
    return proj


def _run(proj: Path):
    """Drive the REAL step, recording the root the writers were handed."""
    seen = []
    original = R._stage_author_knowledge_digests

    def spy(project):
        seen.append(str(project))
        return original(project)

    R._stage_author_knowledge_digests = spy
    try:
        result = R.step_rtl_gen(proj, "unknown_protocol_class")
    finally:
        R._stage_author_knowledge_digests = original
    return result, seen


def test_the_writers_are_still_handed_the_stage_root(tmp_path):
    """The behaviour that must NOT change. The generators keep writing into the
    isolated stage — that is the transaction's whole purpose — so a test that
    passed by making them write to the live tree would have broken the thing it
    was guarding."""
    proj = _project(tmp_path)
    _result, seen = _run(proj)
    assert seen, "the digest stager was never reached"
    assert all("vibeic-rtl-step-" in s for s in seen), seen
    assert all(not s.startswith(str(proj)) for s in seen), seen


def test_the_published_artefact_names_a_root_that_exists(tmp_path):
    """The property, stated as the reader experiences it."""
    proj = _project(tmp_path)
    _run(proj)
    found = 0
    for rel in _PUBLISHED:
        f = proj / rel
        if not f.is_file():
            continue
        found += 1
        recorded = json.loads(f.read_text()).get("project")
        assert recorded, f"{rel} records no project root"
        assert Path(recorded).is_dir(), (
            f"{rel} names {recorded!r}, which does not exist")
        assert Path(recorded) == proj
        assert "vibeic-rtl-step-" not in recorded
    assert found == len(_PUBLISHED), (
        f"only {found} of {len(_PUBLISHED)} published artefacts were written")


def test_no_published_file_carries_the_stage_root_anywhere(tmp_path):
    """MEMBERSHIP over the whole published tree, not just the two files the
    issue happened to name. A remap that fixed the named two and missed a third
    would pass the test above and fail this one."""
    proj = _project(tmp_path)
    _run(proj)
    offenders = []
    for f in sorted(proj.rglob("*")):
        if not f.is_file() or f.is_symlink():
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        if "vibeic-rtl-step-" in text:
            offenders.append(str(f.relative_to(proj)))
    assert offenders == [], offenders


def test_the_rewrite_is_disclosed_by_name(tmp_path):
    """A silent rewrite inside a held transaction is the version of this idea
    nobody could audit. The StepResult names the files it touched."""
    proj = _project(tmp_path)
    result, _seen = _run(proj)
    extras = result.extras if isinstance(result.extras, dict) else {}
    named = extras.get("stage_path_rewritten_in")
    assert named, f"nothing disclosed; extras keys = {sorted(extras)}"
    for rel in named:
        assert (proj / rel).is_file(), rel


# ── the narrowing: what the rewrite must NOT touch ──
