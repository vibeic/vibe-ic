"""#635 — a published benchmark number whose composition was thrown away.

A `cvdp-open` regression sweep tried to diff its per-problem results against the
recorded baseline (202/302, v1.4.14) and could not: that run kept the gate
verdict and the responses, and nothing saying which problems passed. So it could
report that the score moved and never which problems moved.

MEASURED ACROSS THE PUBLISHED CORPUS, and the survey had to be redone once. The
first pass looked for `report.json` / `raw_result.json` / `*verdicts*` BY
FILENAME and found nothing anywhere, which was the probe failing rather than the
corpus being empty. By CONTENT:

    5 of 25 runs DO carry a per-problem structure
      rtllm/run_v1.3.26, run_v127, run_blind_v0126, run_cleanroom_v1388
                                  pass_at_1.json             results[50]
      cvdp/run_v1239_converge     score_final/passrate.json  detail[302]
    20 of 25 carry only a count

So the format did not need inventing — every RTLLM run already does the right
thing. The practice existed and was unenforced, which is why the ONE baseline a
sweep needed was among the twenty. `benchmark_run_manifest` normalises the two
shapes that occur and makes the presence of one checkable.

The strongest validation available is that extraction reproduces the SCORER'S OWN
aggregate on both, from the per-problem entries alone: 215/302 and 44/50.
"""
from __future__ import annotations

import importlib
import json
import pathlib

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

M = importlib.import_module("benchmark_run_manifest")

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_EVAL = _REPO / "benchmark-data" / "evaluation"


# ── extraction reads the shapes that actually occur ────────────────────────
def test_the_list_of_records_shape_is_read():
    """`{"results": [{"design": …, "verdict": "PASS"}]}` — every RTLLM run."""
    f = _EVAL / "rtllm" / "run_v1.3.26" / "pass_at_1.json"
    if not f.is_file():
        return
    doc = json.loads(f.read_text())
    got = M.extract_verdicts(doc)
    assert got is not None and len(got) == 50, got and len(got)
    # The aggregate REPRODUCED from the per-problem entries. If extraction were
    # picking up some other collection, this is where it would show.
    assert sum(1 for v in got.values() if v == "pass") == doc["passed"]


def test_the_id_keyed_mapping_shape_is_read():
    """`{"detail": {"<id>": {"pass": true}}}` — the one CVDP run that kept it."""
    f = _EVAL / "cvdp" / "run_v1239_converge" / "score_final" / "passrate.json"
    if not f.is_file():
        return
    doc = json.loads(f.read_text())
    got = M.extract_verdicts(doc)
    assert got is not None and len(got) == 302, got and len(got)
    assert sum(1 for v in got.values() if v == "pass") == doc["passed"]


def test_extraction_is_structural_not_named_after_a_benchmark():
    """A `cvdp_`/`rtllm_`-keyed extractor would be the overfit this repo
    forbids. Both real shapes are "a collection of per-problem entries, each
    with an identity and a verdict", and an invented third one with neither
    benchmark's vocabulary must read too."""
    doc = {"whatever": {"outer": {"task_alpha": {"outcome": "PASSED"},
                                  "task_beta": {"outcome": "FAILED"}}}}
    got = M.extract_verdicts(doc)
    assert got == {"task_alpha": "pass", "task_beta": "fail"}, got


def test_nothing_readable_is_None_not_an_empty_set():
    """LOAD-BEARING. An empty name set compares EQUAL to another empty one, so
    returning `{}` would make two unrelated runs look identical — the exact
    failure this program exists to prevent, reintroduced inside it."""
    assert M.extract_verdicts({"total": 302, "passed": 202}) is None
    assert M.extract_verdicts([]) is None
    assert M.extract_verdicts("nope") is None


def test_an_unrecognised_verdict_word_does_not_become_a_pass():
    """The fail-safe direction. A scorer emitting a word we have not seen must
    land in no bucket rather than in the reassuring one."""
    assert M.normalize_verdict("PASS") == "pass"
    assert M.normalize_verdict(True) == "pass"
    assert M.normalize_verdict(False) == "fail"
    assert M.normalize_verdict("ERROR") == "error"
    assert M.normalize_verdict("SKIPPED_FOR_REASONS") == "skipped_for_reasons"


def test_a_missing_dataset_digests_to_None_not_to_a_hash_of_nothing():
    """`sha256("")` is a real, quotable hash; publishing it for an absent
    dataset states an identity for content that does not exist."""
    assert M.file_sha256(pathlib.Path("/nonexistent/dataset.jsonl")) is None


# ── the checker names what is missing ──────────────────────────────────────
def _man(**over):
    base = {"verdicts": {"a": "pass", "b": "fail"}, "total": 2,
            "dataset": {"path": "d.jsonl", "sha256": "0" * 64},
            "plugin_version": "1.9.51", "image": "ghcr.io/x:1",
            "scorer_argv": ["run_benchmark.py", "--all"]}
    base.update(over)
    return base


def test_a_complete_manifest_has_no_gaps():
    assert M.manifest_gaps(_man()) == []


def test_a_count_without_a_name_set_is_the_named_gap():
    gaps = M.manifest_gaps(_man(verdicts={}))
    assert any("composition is gone" in g for g in gaps), gaps


def test_a_missing_dataset_digest_is_a_gap_about_the_DENOMINATOR():
    """Not pedantry: a differently-filtered run producing a different total is
    otherwise indistinguishable from a real drop."""
    gaps = M.manifest_gaps(_man(dataset={"path": "d.jsonl", "sha256": None}))
    assert any("denominator" in g for g in gaps), gaps


def test_each_remaining_field_is_named_when_absent():
    for field, needle in (("plugin_version", "names no subject"),
                          ("image", "toolchain actually measured"),
                          ("scorer_argv", "cannot be repeated")):
        gaps = M.manifest_gaps(_man(**{field: "" if field != "scorer_argv" else []}))
        assert any(needle in g for g in gaps), (field, gaps)


def test_an_aggregate_disagreeing_with_its_composition_is_caught():
    """The two halves must describe the same run. A `total` that does not match
    the verdict count means one of them came from somewhere else."""
    gaps = M.manifest_gaps(_man(total=302))
    assert any("describe different" in g for g in gaps), gaps


# ── end to end on a real scorer output ─────────────────────────────────────
def test_emit_then_check_round_trips_on_a_real_run(tmp_path):
    f = _EVAL / "cvdp" / "run_v1239_converge" / "score_final" / "passrate.json"
    if not f.is_file():
        return
    ds = tmp_path / "dataset.jsonl"
    ds.write_text('{"id": "x"}\n', encoding="utf-8")
    rc = M.main(["emit", str(tmp_path), "--scorer-output", str(f),
                 "--dataset", str(ds), "--plugin-version", "1.9.51",
                 "--image", "ghcr.io/vibeic/vibeic-eda:0.2.54",
                 "--scorer-argv", "run_benchmark.py --all"])
    assert rc == 0
    rc2, msg = M.check_run(tmp_path)
    assert rc2 == 0, msg
    man = json.loads((tmp_path / M.MANIFEST_NAME).read_text())
    assert man["total"] == 302
    assert man["counts"]["pass"] == 302 - 87


def test_a_run_with_no_manifest_fails_the_check(tmp_path):
    rc, msg = M.check_run(tmp_path)
    assert rc == 1
    assert "point estimate moved" in msg


def test_emit_REFUSES_a_scorer_output_with_no_name_set(tmp_path, capsys):
    """Writing a manifest with an empty `verdicts` would satisfy the checker's
    presence test while carrying nothing — an absence wearing the shape of a
    record."""
    so = tmp_path / "agg.json"
    so.write_text('{"total": 302, "passed": 202}', encoding="utf-8")
    rc = M.main(["emit", str(tmp_path), "--scorer-output", str(so)])
    assert rc == 2
    assert not (tmp_path / M.MANIFEST_NAME).exists()


def test_an_unreadable_scorer_output_is_rc_2_not_a_manifest(tmp_path):
    so = tmp_path / "broken.json"
    so.write_text("{not json", encoding="utf-8")
    assert M.main(["emit", str(tmp_path), "--scorer-output", str(so)]) == 2
    assert not (tmp_path / M.MANIFEST_NAME).exists()


# ── the gate mode, proven on a real git repo in both directions ────────────
def _repo(tmp_path):
    def g(*a):
        # 30 s, MEASURED not guessed: the whole fixture (init + config + add +
        # commit on a two-file repo) runs in 0.01 s. The ceiling that matters is
        # the harness's 180 s — an inner bound above 60 s can outlive it and
        # kill the SESSION instead of the test, which
        # `ci_harness_timeout_ceiling_check` failed this file on.
        return _pr.run(["git", "-C", str(tmp_path), *a],
                              capture_output=True, text=True)
    g("init", "-q", ".")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    g("add", "seed.txt")
    g("commit", "-q", "-m", "base")
    base = g("rev-parse", "HEAD").stdout.strip()
    return g, base


def test_a_NEW_run_that_publishes_a_number_without_its_composition_FAILS(tmp_path,
                                                                        capsys):
    """THE GATE, proven by injection rather than by reading it. Without this the
    program is available and nothing asks it."""
    import os
    g, base = _repo(tmp_path)
    d = tmp_path / "benchmark-data/evaluation/cvdp/run_probe"
    d.mkdir(parents=True)
    (d / "passrate.json").write_text('{"total": 302, "passed": 202}',
                                     encoding="utf-8")
    g("add", "benchmark-data")
    g("commit", "-q", "-m", "publish a number")
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        rc = M.main(["check", "--tree", "benchmark-data",
                     "--changed-since", base])
    finally:
        os.chdir(cwd)
    assert rc == 1
    assert "point estimate moved" in capsys.readouterr().out


def test_the_same_run_PASSES_once_it_carries_the_name_set(tmp_path):
    import json as _j
    import os
    g, base = _repo(tmp_path)
    d = tmp_path / "benchmark-data/evaluation/cvdp/run_probe"
    d.mkdir(parents=True)
    so = d / "passrate.json"
    so.write_text(_j.dumps({"total": 302, "passed": 202,
                            "detail": {f"p{i:03d}": {"pass": i < 202}
                                       for i in range(302)}}), encoding="utf-8")
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert M.main(["emit", str(d), "--scorer-output", str(so),
                       "--dataset", "seed.txt", "--plugin-version", "1.9.51",
                       "--image", "ghcr.io/x:1",
                       "--scorer-argv", "run_benchmark.py --all"]) == 0
        g("add", "benchmark-data")
        g("commit", "-q", "-m", "with the composition")
        assert M.main(["check", "--tree", "benchmark-data",
                       "--changed-since", base]) == 0
    finally:
        os.chdir(cwd)


def test_a_run_that_published_NO_number_is_not_asked_for_one(tmp_path, capsys):
    """The narrow-refusal half. A probe or partial run that scored nothing has
    no composition to keep, and demanding one would make the gate fire on work
    it has no claim over."""
    import os
    g, base = _repo(tmp_path)
    d = tmp_path / "benchmark-data/evaluation/cvdp/run_probe"
    d.mkdir(parents=True)
    (d / "notes.txt").write_text("scratch\n", encoding="utf-8")
    g("add", "benchmark-data")
    g("commit", "-q", "-m", "no score")
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        rc = M.main(["check", "--tree", "benchmark-data",
                     "--changed-since", base])
    finally:
        os.chdir(cwd)
    assert rc == 0
    assert "none publishes an aggregate" in capsys.readouterr().out


def test_the_twenty_ALREADY_PUBLISHED_runs_are_not_retroactively_failed():
    """Scoped like `benchmark_evidence_structure_check --changed-since`, and for
    the same reason: 20 of 25 published runs carry no name set, and a gate
    applied retroactively would fail every landing over work nobody is doing.
    What must not happen again is a NEW number arriving without its
    composition."""
    src = pathlib.Path(M.__file__).read_text(encoding="utf-8")
    seg = src[src.index("def changed_run_dirs"):]
    seg = seg[:seg.index("\ndef ", 10)]
    assert "f\"{base}...HEAD\"" in seg, seg
