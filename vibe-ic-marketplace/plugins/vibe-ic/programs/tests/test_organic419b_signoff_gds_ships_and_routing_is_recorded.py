#!/usr/bin/env python3
"""ORGANIC #419 follow-up — the size rule did not reach the signoff GDS, and a
routed-away artefact left no trace in the deliverable.

v1.6.61 replaced the publisher's extension drop with a size test. Measured
against that tip, on a synthetic run whose signoff GDS is 0.80 MB — three
orders of magnitude under the 50 MB ceiling and explicitly accepted by
`.gitignore` — the published cell contained ZERO layout artefacts and the
program printed "excluded raw: 0".

Both halves of that are true and neither is what a reader would conclude. The
size test only ever saw files inside the copied subtrees (phase1, phase2,
phase3/reports, reports); the signoff GDS lives in `phase3/stage4/gds/`, which
is not one of them, so the file was never offered to the predicate that would
have kept it. "Excluded 0" meant "the rule declined nothing", not "nothing was
omitted".

And in the other direction, an artefact genuinely over the ceiling was dropped
with its only record being a count on stdout — which is not part of the
deliverable. A reader of the cell could not distinguish "big, stored
elsewhere" from "never existed".

Each test below states which side it holds down. Neither assertion proves
anything alone: staging everything satisfies the first, staging nothing
satisfies the second.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
PROG = _PROGRAMS / "benchmark_evidence_publish.py"
sys.path.insert(0, str(_PROGRAMS))
import size_policy_drift_check as D  # noqa: E402

_REPO = _PROGRAMS.parents[3]
_CEILING = 50 * 1000 * 1000

# "<relpath> <int>B sha256:<64hex> <DECISION> <destination>"
_ROUTING_LINE = re.compile(
    r"^\S+ \d+B sha256:[0-9a-fA-F]{64} "
    r"(STAGED|ROUTED_AWAY|NOT_PUBLISHED) \S+$")


def _make_run(base: Path, gds_bytes: int = 800_000) -> Path:
    """A converged run whose signoff GDS is `gds_bytes` long."""
    run = base / "run"
    for d in ("reports/audit", "phase1/generated_docs", "phase2/stage2/synth",
              "phase3/reports", "reports/phase3", "phase3/stage4/gds",
              "input/docs"):
        (run / d).mkdir(parents=True, exist_ok=True)
    (run / "reports/audit/phase23_completion_audit.json").write_text(
        json.dumps({"verdict": "PASS_WITH_WAIVERS"}))
    (run / "RESULT.md").write_text(
        "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n")
    (run / "phase1/generated_docs/L1.json").write_text("{}")
    (run / "phase2/stage2/synth/netlist.v").write_text("module top; endmodule\n")
    (run / "phase3/reports/drc.rpt").write_text("clean\n")
    (run / "reports/phase3/sta.json").write_text("{}")
    (run / "provenance.jsonl").write_text('{"tool":"yosys"}\n')
    (run / "input/docs/L1.md").write_text("# spec\n")
    with (run / "phase3/stage4/gds/top.gds").open("wb") as fh:
        fh.truncate(gds_bytes)               # sparse: st_size without the disk
    return run


def _publish(run: Path, dest_root: Path, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), "--run-dir", str(run), "--ic", "widgetmul",
         "--pdk", "openpdkx", "--plugin-version", "9.9.9",
         "--dest-root", str(dest_root), *extra],
        capture_output=True, text=True)


def _cell(dest_root: Path) -> Path:
    return dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"


# ── direction 1: UNDER the ceiling MUST end up in the cell ──────────────────

def test_a_signoff_gds_under_the_ceiling_is_in_the_published_cell(tmp_path):
    """The half that was silently false at v1.6.61.

    0.80 MB is the size of a real reference cell's GDS. If this fails, the
    program again publishes less evidence than the cells it replaced.
    """
    run = _make_run(tmp_path, gds_bytes=800_000)
    dest_root = tmp_path / "benchmark-data"
    r = _publish(run, dest_root)
    assert r.returncode == 0, r.stdout + r.stderr

    gds = _cell(dest_root) / "phase3" / "stage4" / "gds" / "top.gds"
    assert gds.is_file(), (
        "a 0.80 MB signoff GDS is not in the published cell; the size rule "
        "never saw it")
    assert gds.stat().st_size == 800_000

    # and it agrees with the manifest line that describes it
    manifest = (gds.parent / "GDS_MANIFEST.txt").read_text().strip()
    assert manifest.startswith(f"top.gds {800_000}B sha256:"), manifest


def test_the_staged_gds_is_byte_identical_to_the_manifest_hash(tmp_path):
    """A blob beside a manifest that describes a DIFFERENT file is worse than
    no blob: it looks verified."""
    import hashlib
    run = _make_run(tmp_path, gds_bytes=4096)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    gdir = _cell(dest_root) / "phase3" / "stage4" / "gds"
    claimed = (gdir / "GDS_MANIFEST.txt").read_text().split("sha256:")[1].strip()
    actual = hashlib.sha256((gdir / "top.gds").read_bytes()).hexdigest()
    assert claimed == actual


# ── direction 2: OVER the ceiling MUST be absent AND recorded ───────────────

def test_an_oversized_artefact_is_absent_but_recorded_with_its_hash(tmp_path):
    """The paired half. Absence alone is satisfied by dropping everything;
    what makes it a routing decision rather than a silent loss is the record.
    """
    run = _make_run(tmp_path, gds_bytes=4096)
    big = run / "reports" / "phase3" / "routed.def"
    with big.open("wb") as fh:
        fh.truncate(_CEILING + 10_000_000)   # 60 MB, sparse
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    cell = _cell(dest_root)

    # the blob is NOT committed
    assert not (cell / "reports" / "phase3" / "routed.def").exists()

    # ...but the cell records that it existed, how big, its hash, and where it went
    routing = (cell / "LAYOUT_ROUTING.txt").read_text()
    line = [ln for ln in routing.splitlines()
            if ln.startswith("reports/phase3/routed.def ")]
    assert len(line) == 1, routing
    assert "ROUTED_AWAY" in line[0]
    assert f"{_CEILING + 10_000_000}B" in line[0]
    assert re.search(r"sha256:[0-9a-f]{64}", line[0]), line[0]


def test_an_oversized_signoff_gds_is_absent_but_the_manifest_still_carries_it(tmp_path):
    """The case the whole mechanism exists for: 89 bytes buys verifiability
    for an artefact too large to store."""
    run = _make_run(tmp_path, gds_bytes=_CEILING + 1)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    gdir = _cell(dest_root) / "phase3" / "stage4" / "gds"
    assert not (gdir / "top.gds").exists()
    assert (gdir / "GDS_MANIFEST.txt").read_text().startswith(
        f"top.gds {_CEILING + 1}B sha256:")
    routing = (_cell(dest_root) / "LAYOUT_ROUTING.txt").read_text()
    assert "phase3/stage4/gds/top.gds" in routing and "ROUTED_AWAY" in routing


# ── the record itself ───────────────────────────────────────────────────────

def test_the_routing_record_exists_even_when_nothing_was_routed_away(tmp_path):
    """A record that only appears on omission cannot be used to prove that
    nothing was omitted."""
    run = _make_run(tmp_path, gds_bytes=4096)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    routing = _cell(dest_root) / "LAYOUT_ROUTING.txt"
    assert routing.is_file()
    body = [ln for ln in routing.read_text().splitlines()
            if ln and not ln.startswith("#")]
    assert body and all("STAGED" in ln for ln in body), body


def test_every_routing_line_is_machine_checkable(tmp_path):
    """Prose in a deliverable rots. A fixed grammar can be validated."""
    run = _make_run(tmp_path, gds_bytes=4096)
    scratch = run / "phase3" / "stage3" / "pnr" / "unpublished.def"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("DESIGN top ;\n")
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    body = [ln for ln in (_cell(dest_root) / "LAYOUT_ROUTING.txt")
            .read_text().splitlines() if ln and not ln.startswith("#")]
    for ln in body:
        assert _ROUTING_LINE.match(ln), f"unparseable routing line: {ln!r}"


def test_an_artefact_outside_published_scope_is_recorded_not_erased(tmp_path):
    """`phase3/stage3` is not published — an evidence-policy call, not a size
    one. Saying so is what lets a reader tell it apart from "never existed",
    and the sha256 is what makes recovering it from a source host checkable.
    """
    run = _make_run(tmp_path, gds_bytes=4096)
    scratch = run / "phase3" / "stage3" / "pnr" / "routed.def"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("DESIGN top ;\n")
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    cell = _cell(dest_root)
    assert not (cell / "phase3" / "stage3" / "pnr" / "routed.def").exists()
    line = [ln for ln in (cell / "LAYOUT_ROUTING.txt").read_text().splitlines()
            if ln.startswith("phase3/stage3/pnr/routed.def ")]
    assert len(line) == 1 and "NOT_PUBLISHED" in line[0], line


def test_a_staged_input_artefact_is_not_mislabelled_not_published(tmp_path):
    """The shared design input usually sits UNDER the run, and it is staged to
    `ic/<IC>/input/` rather than into the cell. If the inventory ran before
    that copy it would sweep the same file up as NOT_PUBLISHED — a false line
    in the one file whose entire value is that it can be trusted.
    """
    run = _make_run(tmp_path, gds_bytes=4096)
    (run / "input" / "docs" / "reference.def").write_text("DESIGN top ;\n")
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    line = [ln for ln in (_cell(dest_root) / "LAYOUT_ROUTING.txt")
            .read_text().splitlines()
            if ln.startswith("input/docs/reference.def ")]
    assert len(line) == 1, line
    assert "NOT_PUBLISHED" not in line[0], line[0]
    assert line[0].endswith("STAGED shared-input"), line[0]
    assert (dest_root / "ic" / "widgetmul" / "input" / "docs"
            / "reference.def").is_file()


def test_no_artefact_is_recorded_twice(tmp_path):
    """Two passes over overlapping trees would double-count. A record that
    lists the same file under two decisions cannot be acted on."""
    run = _make_run(tmp_path, gds_bytes=4096)
    (run / "input" / "docs" / "reference.def").write_text("DESIGN top ;\n")
    scratch = run / "phase3" / "stage3" / "pnr" / "routed.def"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("DESIGN top ;\n")
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    paths = [ln.split(" ")[0] for ln in (_cell(dest_root) / "LAYOUT_ROUTING.txt")
             .read_text().splitlines() if ln and not ln.startswith("#")]
    assert len(paths) == len(set(paths)), paths


def test_a_symlinked_alias_does_not_double_record_the_same_blob(tmp_path):
    """REGRESSION — the shape `test_no_artefact_is_recorded_twice` misses.

    That test builds two DISTINCT files, so it passes whether or not the
    inventory dedupes. Real converged runs alias instead: the v1.5.58 source
    run carries 63 symlinks under `steps/` pointing back into
    `phase3/stage3/`, 8 of them layout artefacts. `rglob` yields the symlink
    and its target separately and `_record` resolves before building the path
    column, so each aliased blob emitted a BYTE-IDENTICAL second line.

    Measured on that run before the fix: 21 record lines for 14 distinct
    artefacts — 7 duplicates — and the summary printed "of 21 artefact(s)".
    Across the 25 converged runs on this host, 143 of 450 lines were
    duplicates. Nothing was lost; the record simply counted aliases as
    evidence.
    """
    run = _make_run(tmp_path, gds_bytes=4096)
    real = run / "phase3" / "stage3" / "pnr" / "routed.def"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("DESIGN top ;\n")
    step = run / "steps" / "21_routing_global_detailed"
    step.mkdir(parents=True, exist_ok=True)
    (step / "routed.def").symlink_to(real)          # the shape the runs have
    assert (step / "routed.def").is_file()

    dest_root = tmp_path / "benchmark-data"
    r = _publish(run, dest_root)
    assert r.returncode == 0, r.stdout + r.stderr

    body = [ln for ln in (_cell(dest_root) / "LAYOUT_ROUTING.txt")
            .read_text().splitlines() if ln and not ln.startswith("#")]
    assert len(body) == len(set(body)), (
        "the same blob was recorded twice through a symlink alias:\n"
        + "\n".join(sorted(body)))
    hits = [ln for ln in body if ln.startswith("phase3/stage3/pnr/routed.def ")]
    assert len(hits) == 1, hits

    # and the printed count agrees with the file it summarises
    m = re.search(r"of (\d+) artefact\(s\)", r.stdout)
    assert m, r.stdout
    assert int(m.group(1)) == len(body), (m.group(1), len(body))


@pytest.mark.parametrize("route", ["git-lfs", "github-release", "not-retained"])
def test_the_destination_is_recorded_not_assumed(tmp_path, route):
    """"Where to" is an operator claim. The default is the honest one."""
    run = _make_run(tmp_path, gds_bytes=_CEILING + 1)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root, "--oversize-route", route).returncode == 0
    line = [ln for ln in (_cell(dest_root) / "LAYOUT_ROUTING.txt")
            .read_text().splitlines()
            if "ROUTED_AWAY" in ln and not ln.startswith("#")]
    assert line and line[0].endswith(f" {route}"), line


def test_the_default_destination_is_not_retained(tmp_path):
    """A cell that honestly records "not retained" is a better deliverable
    than one that quietly implies an LFS copy nobody made."""
    run = _make_run(tmp_path, gds_bytes=_CEILING + 1)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    assert " ROUTED_AWAY not-retained" in (
        _cell(dest_root) / "LAYOUT_ROUTING.txt").read_text()


def test_the_json_summary_carries_the_same_decisions(tmp_path):
    run = _make_run(tmp_path, gds_bytes=_CEILING + 1)
    dest_root = tmp_path / "benchmark-data"
    out = tmp_path / "summary.json"
    assert _publish(run, dest_root, "--json", str(out)).returncode == 0
    data = json.loads(out.read_text())
    assert data["excluded_raw_files"] == 1
    assert data["oversize_route"] == "not-retained"
    decisions = {r["decision"] for r in data["layout_routing"]}
    assert decisions == {"ROUTED_AWAY"}, data["layout_routing"]


def test_dry_run_still_writes_nothing(tmp_path):
    run = _make_run(tmp_path, gds_bytes=4096)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root, "--dry-run").returncode == 0
    assert not dest_root.exists()


def test_the_published_cell_still_passes_its_own_structure_check(tmp_path):
    """Staging the GDS must not make the cell nonconformant — the publisher's
    post-stage self-check is what would catch that, so exercise it."""
    run = _make_run(tmp_path, gds_bytes=800_000)
    dest_root = tmp_path / "benchmark-data"
    r = _publish(run, dest_root)
    assert r.returncode == 0 and "self-check  : PASS" in r.stdout, r.stdout


# ── the drift check must not be a rubber stamp ──────────────────────────────

def _mutant(tmp_path: Path) -> Path:
    mut = tmp_path / "programs"
    mut.mkdir()
    for name in ("tracked_blob_size_guard.py", "benchmark_evidence_publish.py",
                 "benchmark_evidence_structure_check.py"):
        shutil.copy2(_PROGRAMS / name, mut / name)
    return mut


def test_an_extension_only_revert_is_caught_even_with_the_ceiling_declared(tmp_path):
    """THE anti-rubber-stamp test.

    Measured against the grep-only form of this gate, this exact mutant —
    `_excluded` reverted to the extension rule #419 removed, with
    `_SIZE_CEILING = 50 * 1000 * 1000` left spelled correctly beside it —
    returned PASS with zero findings. A declared constant is not a followed
    one, so the gate has to CALL the decider.
    """
    mut = _mutant(tmp_path)
    p = mut / "benchmark_evidence_publish.py"
    src = p.read_text()
    anchor = "return is_layout_artefact(p) and over_ceiling(p)"
    assert anchor in src, "publisher changed shape; update this mutant"
    p.write_text(src.replace(anchor, "return is_layout_artefact(p)"))

    assert "_SIZE_CEILING = 50 * 1000 * 1000" in p.read_text(), \
        "the mutant must keep the constant — that is the whole point"

    rep = D.audit(mut, _REPO / ".gitignore")
    assert rep["verdict"] == "FAIL", rep
    assert any(f.startswith("EXTENSION_RULE_RETURNED") for f in rep["findings"]), \
        rep["findings"]


def test_a_decider_that_ignores_its_ceiling_is_caught(tmp_path):
    """The opposite revert: accept everything. Without this half, "the probe
    fires" is satisfied by a probe that always fires."""
    mut = _mutant(tmp_path)
    p = mut / "benchmark_evidence_publish.py"
    p.write_text(p.read_text().replace(
        "return is_layout_artefact(p) and over_ceiling(p)", "return False"))
    rep = D.audit(mut, _REPO / ".gitignore")
    assert any(f.startswith("CEILING_NOT_ENFORCED") for f in rep["findings"]), \
        rep["findings"]


def test_removing_the_named_predicate_is_caught(tmp_path):
    """The policy has to stay callable. If it goes back to being inline, the
    only thing left to check is spelling."""
    mut = _mutant(tmp_path)
    p = mut / "benchmark_evidence_structure_check.py"
    p.write_text(p.read_text().replace("def check_folder(", "def _inlined("))
    rep = D.audit(mut, _REPO / ".gitignore")
    assert any(f.startswith("NO_PREDICATE") for f in rep["findings"]), \
        rep["findings"]


def test_breaking_a_helper_under_the_decider_is_caught_too(tmp_path):
    """Renaming a helper the decider CALLS is not a NO_PREDICATE — the entry
    point is still there — but it must not be a PASS either. It surfaces as
    PREDICATE_RAISED, which is still a finding and still rc=1."""
    mut = _mutant(tmp_path)
    p = mut / "benchmark_evidence_structure_check.py"
    p.write_text(p.read_text().replace("def over_ceiling(", "def _inlined("))
    rep = D.audit(mut, _REPO / ".gitignore")
    assert rep["verdict"] == "FAIL", rep
    assert any(f.startswith("PREDICATE_RAISED") for f in rep["findings"]), \
        rep["findings"]


def test_the_structure_checks_real_decision_is_what_gets_probed(tmp_path):
    """REGRESSION, and the reason `_DECIDERS` names `check_folder`.

    The first version of this gate probed `over_ceiling`, a three-line pure
    size test. The structure check's actual decision lives in `check_folder`.
    Reverting THAT to the pre-#419 extension-only rule — while leaving
    `over_ceiling` defined and correct beside it — returned PASS with zero
    findings, and made all three real reference cells non-conformant with a
    message calling a 1 MB file 'over the 50 MB commit ceiling'.
    """
    mut = _mutant(tmp_path)
    p = mut / "benchmark_evidence_structure_check.py"
    src = p.read_text()
    anchor = ("    for p in layout:\n"
              "        try:\n"
              "            if over_ceiling(p):\n"
              "                over.append((p, p.stat().st_size))\n"
              "        except OSError:\n"
              "            continue")
    assert anchor in src, "structure check changed shape; update this mutant"
    p.write_text(src.replace(
        anchor,
        "    for p in layout:\n"
        "        try:\n"
        "            over.append((p, p.stat().st_size))\n"
        "        except OSError:\n"
        "            continue"))
    # The helper is untouched: this mutant is invisible to a probe of it.
    assert "def over_ceiling(" in p.read_text()

    rep = D.audit(mut, _REPO / ".gitignore")
    assert rep["verdict"] == "FAIL", rep
    assert any(f.startswith("EXTENSION_RULE_RETURNED") for f in rep["findings"]), \
        rep["findings"]


def test_the_shipped_tree_passes_the_behavioural_probe():
    """Pairs with every mutant above: they prove the probe can fail, this
    proves it does not fail on the tree being shipped."""
    rep = D.audit(_PROGRAMS, _REPO / ".gitignore")
    assert rep["verdict"] == "PASS", rep["findings"]


def test_a_module_that_cannot_be_imported_is_a_finding_not_a_pass(tmp_path):
    """A probe that swallows an import error reports a clean bill of health
    for a tree it never examined."""
    mut = _mutant(tmp_path)
    (mut / "benchmark_evidence_publish.py").write_text(
        "_SIZE_CEILING = 50 * 1000 * 1000\nraise RuntimeError('boom')\n")
    rep = D.audit(mut, _REPO / ".gitignore")
    assert any(f.startswith("UNIMPORTABLE") for f in rep["findings"]), \
        rep["findings"]
