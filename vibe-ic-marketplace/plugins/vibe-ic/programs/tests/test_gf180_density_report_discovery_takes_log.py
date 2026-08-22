"""Handed a project directory, the density gate could not find the density.

MEASURED, gf180mcuD chip path 2026-08-22. `general_precheck` delegates to this
gate with the reports DIRECTORY as its positional argument. On a project whose
per-layer densities were sitting in that very directory, it returned:

    {"verdict": "IO_ERROR", "error": "no density report at .../reports/phase3"}

i.e. rc 2 — which the caller reads as "could not measure" and reports as
`Checker.KLayoutDensity NOT_DETERMINED`.

The cause is which extensions the directory scan looks at. A KLayout density
deck writes its per-layer ratios ONLY into its run transcript:

    2026-08-20 08:26:51 +0000: Memory Usage (2018068K) : Metal1 ratio: 43.81 %

while the `.json` beside it is a per-RULE violation tally (`{"DCF.1b": 0, ...}`)
with no per-layer density in it at all. The scan accepted
`*density*layer*.json`, `*metal*density*.json`, `*density*.rpt` and
`*density*.txt` — and not `.log`.

`.log` is ordered LAST so every existing preference still wins, and a transcript
that carries no per-layer density still FAILs on the "no per-layer metal density
found" branch. Widening the scan cannot fabricate a verdict.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import metal_layer_density_check as M  # noqa: E402

_KLAYOUT_TRANSCRIPT = "".join(
    f"2026-08-20 08:26:51 +0000: Memory Usage (2018068K) : {k} ratio: {v} %\n"
    for k, v in (("COMP", 46.50), ("Metal1", 43.81), ("Metal2", 41.57),
                 ("Metal3", 46.85), ("Metal4", 51.69), ("Metal5", 43.86)))
#: What sits beside it, and why it is not a substitute: a per-RULE tally.
_RULE_TALLY = json.dumps({"DCF.1b": 0, "PL.8": 0, "M1.4": 0}, indent=1)


def _reports_dir(tmp_path, **files):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / name.replace("__", ".")).write_text(body)
    return d


def test_CONTROL_the_json_beside_it_carries_no_per_layer_density(tmp_path):
    """Establishes that the `.log` is not redundant — without it there is
    genuinely nothing in the directory to read."""
    d = _reports_dir(tmp_path, density__klayout__json=_RULE_TALLY)
    res = M.check(d, {}, None, None)
    assert res["verdict"] in ("IO_ERROR", "FAIL"), res
    assert "per_layer" not in res or not res["per_layer"], res


def test_a_klayout_density_transcript_in_the_directory_IS_FOUND(tmp_path):
    """THE DEFECT: rc 2 IO_ERROR on a directory that holds the densities."""
    d = _reports_dir(tmp_path,
                     density__klayout__json=_RULE_TALLY,
                     density__klayout__log=_KLAYOUT_TRANSCRIPT)
    res = M.check(d, {}, None, None)
    assert res["verdict"] != "IO_ERROR", res
    assert Path(str(res["report"])).name == "density.klayout.log", res
    assert set(res["per_layer"]) == {f"metal{i}" for i in range(1, 6)}, res


def test_the_found_transcript_is_actually_judged(tmp_path):
    """Finding it is only half; the ratios must reach a verdict."""
    d = _reports_dir(tmp_path, density__klayout__log=_KLAYOUT_TRANSCRIPT)
    # A TWO-SIDED window on purpose. A one-sided one would only be judged with
    # the per-bound change that lives on a DIFFERENT branch, and a test that
    # silently depends on another branch is a test that goes dark the moment the
    # two land in the wrong order. This branch stands alone.
    win = {f"metal{i}": (0.30, 0.70) for i in range(1, 6)}
    res = M.check(d, win, None, None)
    assert res["verdict"] == "PASS", res
    assert res["per_layer"]["metal4"]["density"] == 0.5169, res


def test_NEGATIVE_a_log_with_no_per_layer_density_still_FAILS(tmp_path):
    """Widening the scan must not fabricate a verdict. An unrelated `.log` that
    happens to match the glob is read, found to carry nothing, and REFUSED —
    never passed, and never reported as a clean zero."""
    d = _reports_dir(tmp_path,
                     density__klayout__log="starting deck\nfinished deck\n")
    res = M.check(d, {}, None, None)
    assert res["verdict"] == "FAIL", res
    assert "no per-layer metal density" in str(res.get("detail", "")), res


def test_CONTROL_an_rpt_still_wins_over_a_log(tmp_path):
    """`.log` is ordered LAST; the pre-existing preferences must be unchanged."""
    d = _reports_dir(tmp_path,
                     density__rpt=_KLAYOUT_TRANSCRIPT,
                     density__klayout__log=_KLAYOUT_TRANSCRIPT)
    res = M.check(d, {}, None, None)
    assert Path(str(res["report"])).name == "density.rpt", res


def test_CONTROL_an_empty_directory_is_still_an_IO_ERROR(tmp_path):
    """A directory with nothing in it has not been measured, and says so."""
    d = _reports_dir(tmp_path)
    res = M.check(d, {}, None, None)
    assert res["verdict"] == "IO_ERROR", res
