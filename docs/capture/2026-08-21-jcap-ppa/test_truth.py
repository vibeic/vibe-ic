from __future__ import annotations

import hashlib
import ast
import base64
import json
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _truth


_REPO = HERE.parents[2]
sys.path.insert(0, str(
    _REPO / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "tests"
))
from _hostpaths import require_repo

ROOT = require_repo(".")
RESULT = require_repo(
    "docs", "capture", "2026-08-21-jcap-ppa", "RESULT.md"
).read_text()
EXCLUDED = "324435d94a65f7ef1c8d2b8e4b66407cf778220d"
RESULT_PATH = pathlib.PurePosixPath("docs/capture/2026-08-21-jcap-ppa/RESULT.md")
EXCLUDED_RESULT_SHA256 = \
    "e36e633bb62c23ae2a2f4eca980dd3e941d8391490d3159bece48070fb78fdec"


@pytest.mark.parametrize("case", ["authentic", "missing", "wrong_path", "tampered", "wrong_claim",
                                "current_extra", "wrong_tip", "missing_tip_object"])
def test_routing_checks_execute_and_refuse_missing_or_mismatched_history(tmp_path, case):
    """Execute the verifier's actual routing block, with local Git unavailable.

    The normal complete verifier is also exercised by the native acceptance
    packet. Here the isolated block makes absence and corruption deterministic.
    """
    import re
    import types
    archive = tmp_path / "CAPTURE_ROUTING_IDENTITY.json"
    proof = json.loads((HERE / archive.name).read_text())
    if case == "wrong_path":
        proof["path"] = "another/CAPTURE_ROUTING.json"
    if case == "tampered":
        for item in proof["objects"].values():
            if item["type"] == "blob":
                item["base64"] = base64.b64encode(b"{}").decode()
    if case != "missing":
        archive.write_text(json.dumps(proof))
    tip_archive = tmp_path / "CAPTURE_ROUTING_RECEIPT_IDENTITY.json"
    tip_proof = json.loads((HERE / tip_archive.name).read_text())
    if case == "missing_tip_object":
        tip_proof["objects"].pop("58d5efd79cf60d75bfa156b83cecd1c63e78728f")
    tip_archive.write_text(json.dumps(tip_proof))
    md = RESULT
    if case == "wrong_claim":
        md = re.sub(r"gains \*\*\d+\*\* steps", "gains **999** steps", md, count=1)
        assert md != RESULT
    tree = ast.parse((HERE / "verify.py").read_text())
    start = next(i for i, node in enumerate(tree.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_bR" for t in node.targets))
    count = next(i for i in range(start, len(tree.body))
                 if isinstance(tree.body[i], ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_cost"
                         for t in tree.body[i].targets))
    observed = []
    controls = []
    env = {"_sp2": types.SimpleNamespace(run=lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", "missing")),
           "_base": "6dd97611eafa2af2d1aacc13dae88bd40c3c0e8b",
           "_receipt_tip": ("0" * 40 if case == "wrong_tip" else
                            "58d5efd79cf60d75bfa156b83cecd1c63e78728f"),
           "ROOT": ROOT, "HERE": tmp_path, "_truth": _truth,
           "pathlib": pathlib, "json": json, "re": re, "MD": md,
           "ROUTING": json.loads((ROOT / "vibe-ic-marketplace/plugins/vibe-ic/benchmark/CAPTURE_ROUTING.json").read_text()),
           "RECS": json.loads((HERE / "recoveries.json").read_text()),
           "check": lambda name, ok, detail="": observed.append((name, bool(ok), detail)),
           "control": lambda name, ok: controls.append((name, bool(ok)))}
    if case == "current_extra":
        env["ROUTING"]["steps"]["test.later_route"] = {
            "bucket_A_program": "programs/test_later_route.py"}
    exec(compile(ast.Module(body=tree.body[start:count], type_ignores=[]), str(HERE / "verify.py"), "exec"), env)
    expected = ["the quoted distinct-target-program count is the routed one",
                "the quoted routing figures are derived from the two routing files"]
    assert [row[0] for row in observed] == expected, observed
    assert all(ok for _, ok in controls), controls
    if case in {"authentic", "current_extra"}:
        assert env["_routing_error"] == ""
        assert env["_projection"] == (0, 0, 49)
        assert all(row[1] for row in observed), observed
    else:
        assert observed[1][1] is False, observed


def _portable_history_repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    archive = tmp_path / RESULT_PATH.parent / 'HISTORICAL_CHECKPOINTS.json'
    archive.parent.mkdir(parents=True)
    archive.write_bytes((HERE / 'HISTORICAL_CHECKPOINTS.json').read_bytes())
    return archive


def test_history_checkpoints_are_authenticated_in_an_empty_clean_clone(tmp_path):
    _portable_history_repo(tmp_path)
    checkpoints = _truth.strip_labeled_history(RESULT)[1]
    before = subprocess.check_output(['git', '-C', str(tmp_path), 'count-objects', '-v'])
    for checkpoint in checkpoints:
        assert subprocess.run(['git', '-C', str(tmp_path), 'cat-file', '-e', checkpoint.sha],
                              capture_output=True).returncode != 0
    assert _truth.validate_history_checkpoints(tmp_path, RESULT_PATH, checkpoints) == []
    assert subprocess.check_output(['git', '-C', str(tmp_path), 'count-objects', '-v']) == before


@pytest.mark.parametrize('kind', ['commit', 'tree', 'blob'])
def test_history_archive_rejects_modified_authenticated_object(tmp_path, kind):
    archive = _portable_history_repo(tmp_path)
    proof = json.loads(archive.read_text())
    # Corrupt every object of this type so the requested proof path necessarily
    # encounters one; retain all claimed object/commit identities.
    for item in proof['objects'].values():
        if item['type'] == kind:
            item['base64'] = base64.b64encode(base64.b64decode(item['base64']) + b'X').decode()
    archive.write_text(json.dumps(proof))
    errors = _truth.validate_history_checkpoints(tmp_path, RESULT_PATH, _truth.strip_labeled_history(RESULT)[1])
    assert errors and all('invalid Git identity' in error for error in errors)


@pytest.mark.parametrize('mutation', ['missing_archive', 'wrong_path', 'unregistered_sha', 'missing_object'])
def test_history_archive_cannot_waive_missing_or_mismatched_evidence(tmp_path, mutation):
    archive = _portable_history_repo(tmp_path)
    checkpoints = _truth.strip_labeled_history(RESULT)[1]
    proof = json.loads(archive.read_text())
    if mutation == 'missing_archive':
        archive.unlink()
    else:
        if mutation == 'wrong_path':
            proof['path'] = 'another/RESULT.md'
        elif mutation == 'unregistered_sha':
            proof['checkpoints'] = []
        else:
            proof['objects'] = {}
        archive.write_text(json.dumps(proof))
    errors = _truth.validate_history_checkpoints(tmp_path, RESULT_PATH, checkpoints)
    assert len(errors) == len(checkpoints)
    assert all('does not resolve to authenticated' in error for error in errors)


def test_authentic_history_still_rejects_a_false_claim_pair(tmp_path):
    _portable_history_repo(tmp_path)
    actual = _truth.strip_labeled_history(RESULT)[1][0]
    changed = _truth.HistoryCheckpoint(actual.sha, _truth.ClaimPair(actual.pair.claims + 1, actual.pair.holding))
    errors = _truth.validate_history_checkpoints(tmp_path, RESULT_PATH, [changed])
    assert len(errors) == 1 and 'but its tables derive' in errors[0]


def test_capture_plugin_identity_matches_original_backlogs_without_git_objects(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    before = subprocess.check_output(['git', '-C', str(tmp_path), 'count-objects', '-v'])
    sha = '6dd97611eafa2af2d1aacc13dae88bd40c3c0e8b'
    assert subprocess.run(['git', '-C', str(tmp_path), 'cat-file', '-e', sha],
                          capture_output=True).returncode != 0
    version = _truth.capture_plugin_version(tmp_path, HERE, sha)
    assert version == '1.11.71'
    inputs = sorted((HERE / 'candidates').rglob('*.yaml'))
    assert len(inputs) == 3
    for item in inputs:
        assert f'plugin_version: "{version}"' in item.read_text()
    assert subprocess.check_output(['git', '-C', str(tmp_path), 'count-objects', '-v']) == before


@pytest.mark.parametrize('mutation', ['missing', 'wrong_path', 'tampered_blob'])
def test_capture_plugin_identity_refuses_unproven_version(tmp_path, mutation):
    proof = json.loads((HERE / 'CAPTURE_PLUGIN_IDENTITY.json').read_text())
    if mutation == 'wrong_path':
        proof['path'] = 'unrelated/plugin.json'
    elif mutation == 'tampered_blob':
        for obj in proof['objects'].values():
            if obj['type'] == 'blob':
                obj['base64'] = base64.b64encode(b'{"version":"1.11.71"}').decode()
    if mutation != 'missing':
        (tmp_path / 'CAPTURE_PLUGIN_IDENTITY.json').write_text(json.dumps(proof))
    with pytest.raises((OSError, ValueError)):
        _truth.capture_plugin_version(tmp_path, tmp_path, '6dd97611eafa2af2d1aacc13dae88bd40c3c0e8b')


@pytest.mark.parametrize('coverage,rc,extra,declared,expected', [
    ('MEASURED', 1, False, '1.11.71', True),
    ('NOT_MEASURED', 1, False, '1.11.71', False),
    (None, 1, False, '1.11.71', False),
    ('MEASURED', 2, False, '1.11.71', False),
    ('MEASURED', 1, True, '1.11.71', False),
    ('MEASURED', 1, False, '0.0.0', False),
])
def test_historical_version_reconciliation_keeps_content_refusals(coverage, rc, extra, declared, expected):
    report = {'findings': [{'category': 'PLUGIN_VERSION_MISMATCH'}]}
    if coverage is not None:
        report['nda_codename_rule'] = coverage
    if extra:
        report['findings'].append({'category': 'MISSING_FIELD'})
    assert _truth.historical_backlog_version_only(report, rc, declared, '1.11.71') is expected
    assert not _truth.historical_backlog_version_only(report, rc, declared, None)




def _excluded_source_result() -> str:
    """Rebuild the exact excluded result without needing a dangling Git object.

    ``EXCLUDED`` is an immutable lane commit that was squash-landed, so a fresh
    clone cannot select it.  Keep the reverse control byte-exact and portable
    by carrying its small reverse delta from the current result, then bind the
    reconstructed bytes to the source blob's independently recorded digest.
    """
    replacements = [
        (
            """tree.** The first table also includes the smaller `jsonschema` item, which is not
one of the eighteen; the second table adds nine classes drawn from the six lane
records. Together those two tables are the current source of truth: **twenty-one claims
examined — twenty hold and one, F-2, is disproven by execution** because its
guard's predicate is satisfied by a production fallback and cannot fail. No
duplicate record was produced for these claims; the disproven one is folded into
the more general A-3 record.
""",
            """tree.** Add the smaller `jsonschema` item, which is not one of the eighteen, and
four more classes drawn from the six lane records, and the count is
**11 + 1 + 6 = 18** claims examined — of which **seventeen hold and one, F-2, is
disproven by execution**: its guard's predicate is satisfied by a production
fallback and cannot fail. Those sixteen produced no record; duplicating them would be
worse than skipping them.
""",
        ),
        (
            """Twelve are ALREADY-PROGRAM:
eleven of the eighteen end-to-end findings plus the smaller `jsonschema` claim.
For each, the program or census test that enforces it now was checked by reading
it, not by trusting the fix note.
""",
            """Eleven are ALREADY-PROGRAM. For each, the program or census test that enforces
it now — checked by reading it, not by trusting the fix note.
""",
        ),
        (
            """<!-- already-program-history-start checkpoint=d6ea69acfdac0d1a9810a1d554ed608802011df5 claims=16 holding=15 -->

> Historical checkpoint (exact):
> `d6ea69acfdac0d1a9810a1d554ed608802011df5`. This section preserves that
> checkpoint's 16-claim mutation campaign, where 15 claims held. Its counts are
> historical measurements, not the current totals.

""",
            "",
        ),
        (
            "\n<!-- already-program-history-end -->\n\n## The brief's own requirements",
            "\n## The brief's own requirements",
        ),
        (
            "zero D. 21 ALREADY-PROGRAM claims examined, 20 holding and 1 (F-2) disproven by",
            "zero D. 18 ALREADY-PROGRAM claims examined, 17 holding and 1 (F-2) disproven by",
        ),
        (
            "| ALREADY-PROGRAM | 21 claims, **20 hold** |",
            "| ALREADY-PROGRAM | 18 claims, **17 hold** |",
        ),
        (
            """<!-- already-program-history-start checkpoint=4f2d47cf848bd2e69e95f82adba5d6dba5c2fbc1 claims=19 holding=18 -->

""",
            "",
        ),
        (
            """<!-- already-program-history-end -->

<!-- already-program-history-start checkpoint=afbf611ceb1965d0ebcbeb298991f925c43a59d3 claims=20 holding=19 -->

""",
            "",
        ),
        (
            "\n<!-- already-program-history-end -->\n\nThe three staleness guards",
            "\nThe three staleness guards",
        ),
    ]
    excluded = RESULT
    for current, historical in replacements:
        assert excluded.count(current) == 1, \
            "excluded-source reverse delta no longer selects exactly once"
        excluded = excluded.replace(current, historical, 1)
    digest = hashlib.sha256(excluded.encode()).hexdigest()
    assert digest == EXCLUDED_RESULT_SHA256, \
        f"reconstructed excluded source {EXCLUDED} has digest {digest}"
    return excluded


def _validate(md: str) -> list[str]:
    _, _, checkpoints, errors = _truth.validate_current_claim_counts(md)
    errors.extend(_truth.validate_history_checkpoints(ROOT, RESULT_PATH, checkpoints))
    return errors


def _replace_line(md: str, prefix: str, transform) -> str:
    lines = md.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    assert len(hits) == 1
    lines[hits[0]] = transform(lines[hits[0]])
    return "".join(lines)


def _drop_first_table_row(md: str) -> str:
    return _replace_line(md, "| (smaller) `jsonschema`", lambda _: "")


MUTATIONS = [
    ("title claim number-word", lambda md: md.replace("the twenty-one already-program", "the twenty-two already-program", 1), "title"),
    ("title holding number-word", lambda md: md.replace("of which twenty hold", "of which nineteen hold", 1), "title"),
    ("cross-line introduction claim", lambda md: md.replace("**twenty-one claims\nexamined", "**twenty-two claims\nexamined", 1), "introduction"),
    ("introduction holding number-word", lambda md: md.replace("examined — twenty hold", "examined — nineteen hold", 1), "introduction"),
    ("summary claims", lambda md: md.replace(". 21 ALREADY-PROGRAM claims examined", ". 22 ALREADY-PROGRAM claims examined", 1), "summary"),
    ("summary holding", lambda md: md.replace("claims examined, 20 holding", "claims examined, 19 holding", 1), "summary"),
    ("ladder claims", lambda md: md.replace("| ALREADY-PROGRAM | 21 claims", "| ALREADY-PROGRAM | 22 claims", 1), "ladder"),
    ("ladder holding", lambda md: md.replace("21 claims, **20 hold**", "21 claims, **19 hold**", 1), "ladder"),
    ("finding-table row", _drop_first_table_row, "finding-table introduction"),
    ("disproven row", lambda md: md.replace("DISPROVEN by execution", "DISPROVEN at a checkpoint", 1), "disproven claim rows"),
]


def test_current_pair_is_derived_and_every_surface_agrees():
    pair, surfaces, checkpoints, errors = _truth.validate_current_claim_counts(RESULT)
    errors.extend(_truth.validate_history_checkpoints(ROOT, RESULT_PATH, checkpoints))
    assert not errors
    assert pair is not None
    assert surfaces and all(surface == pair for surface in surfaces.values())


def test_historical_coverage_citations_resolve_the_real_relocated_sources():
    import re
    sources = set(re.findall(r"`(ppa-[a-z0-9]+/[A-Za-z0-9_./-]+\.md)`", RESULT))
    assert len(sources) == 4
    for source in sources:
        resolved = _truth.coverage_source_path(ROOT, source)
        assert resolved is not None, source
        assert resolved == ROOT / "docs" / "campaigns" / source


@pytest.mark.parametrize("case", ["legacy", "relocated", "missing", "wrong_root",
                                  "basename_elsewhere", "external_symlink"])
def test_coverage_source_relocation_never_substitutes_unrelated_evidence(tmp_path, case):
    repo = tmp_path / "repo"
    repo.mkdir()
    if case != "wrong_root":
        (repo / "vibe-ic-marketplace/plugins/vibe-ic").mkdir(parents=True)
    relative = "ppa-neutral/RESULT.md"
    target = repo / "docs/campaigns" / relative
    if case == "legacy":
        target = repo / relative
    if case == "basename_elsewhere":
        target = repo / "other/RESULT.md"
    if case != "missing":
        target.parent.mkdir(parents=True, exist_ok=True)
        if case == "external_symlink":
            outside = tmp_path / "outside.md"
            outside.write_text("not repository evidence")
            target.symlink_to(outside)
        else:
            target.write_text("source evidence")
    result = _truth.coverage_source_path(repo, relative)
    if case in ("legacy", "relocated"):
        assert result == target
    else:
        assert result is None


@pytest.mark.parametrize(("name", "mutate", "expected"), MUTATIONS, ids=[x[0] for x in MUTATIONS])
def test_each_count_surface_mutation_is_rejected(name, mutate, expected):
    mutated = mutate(RESULT)
    assert mutated != RESULT, f"mutation did not alter the document: {name}"
    errors = _validate(mutated)
    assert any(expected in error for error in errors), errors


def test_excluded_source_is_the_reverse_control():
    old = _excluded_source_result()
    errors = _validate(old)
    for surface in ("introduction", "summary", "ladder"):
        assert any(surface in error for error in errors), errors


def test_old_pair_needs_an_exact_checkpoint_label():
    checkpoint = _truth.strip_labeled_history(RESULT)[1][0]
    inverse = {value: word for word, value in _truth.NUMBER_WORDS.items()}
    historical_surface = (
        "Historical copy, current source of truth: **"
        f"{inverse[checkpoint.pair.claims]} claims\nexamined — "
        f"{inverse[checkpoint.pair.holding]} hold at that checkpoint.**\n"
    )
    unlabelled = RESULT.replace("## Summary", historical_surface + "\n## Summary", 1)
    assert any("introduction" in error for error in _validate(unlabelled))

    marker = (
        "<!-- already-program-history-start "
        f"checkpoint={checkpoint.sha} claims={checkpoint.pair.claims} "
        f"holding={checkpoint.pair.holding} -->\n"
        + historical_surface
        + _truth.HISTORY_END
        + "\n\n"
    )
    labelled = RESULT.replace("## Summary", marker + "## Summary", 1)
    assert not _validate(labelled)


def _run(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: pathlib.Path, message: str) -> str:
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def test_lane_tip_receipt_ignores_other_lane_program_but_catches_ours(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.name", "truth-control")
    _run(repo, "config", "user.email", "truth-control@example.invalid")
    (repo / "README").write_text("base\n")
    base = _commit(repo, "base")

    docs = repo / "docs" / "capture" / "lane"
    docs.mkdir(parents=True)
    (docs / "RESULT.md").write_text("source\n")
    source = _commit(repo, "excluded source")
    (docs / "RESULT.md").write_text("candidate\n")
    candidate = _commit(repo, "truth repair")

    _run(repo, "checkout", "-q", "-b", "other", base)
    other_program = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "other.py"
    other_program.parent.mkdir(parents=True)
    other_program.write_text("OTHER = True\n")
    _commit(repo, "other lane program")
    _run(repo, "merge", "--no-ff", "--no-edit", candidate)
    union = _run(repo, "rev-parse", "HEAD")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=union, lane_tip=candidate, lane_base=base, excluded_source=source,
    )
    assert not errors

    # A squash has the received blobs but not the received commit as ancestor.
    # That is the repository's normal landing shape and must remain provable.
    _run(repo, "checkout", "-q", "-b", "squash", base)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RESULT.md").write_text("candidate\n")
    squash = _commit(repo, "squash-equivalent landing")
    errors, detail = _truth.lane_constraint_errors(
        repo, head=squash, lane_tip=candidate, lane_base=base,
        excluded_source=source,
    )
    assert not errors, errors
    assert any("squash-equivalent" in item for item in detail), detail

    (docs / "RESULT.md").write_text("mutated after receipt\n")
    harmed_squash = _commit(repo, "harm received content")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=harmed_squash, lane_tip=candidate, lane_base=base,
        excluded_source=source,
    )
    assert any("neither an ancestor nor squash-equivalent" in error
               for error in errors), errors

    _run(repo, "checkout", "-q", "-b", "lane-bad", candidate)
    lane_program = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "lane.py"
    lane_program.parent.mkdir(parents=True)
    lane_program.write_text("LANE = True\n")
    bad_tip = _commit(repo, "lane adds a program")
    errors, _ = _truth.lane_constraint_errors(
        repo, head=bad_tip, lane_tip=bad_tip, lane_base=base, excluded_source=source,
    )
    assert any("program file(s) added by lane" in error for error in errors), errors
