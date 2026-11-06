"""The coverage of a SUITE is the union of its cases, not its first member's.

MEASURED, subservient x gf180mcuD, lane icsub2, r17 vs r18 — same RTL, same
denominators (135 line / 1752 toggle / 48 branch), one field different:

    r17  "testbench": <proj>/sim_unit/tb_subservient.v          80.74 / 93.55 / 91.67
    r18  "testbench": <proj>/phase2/stage1/sim/tb/blinky_hex.v  68.89 / 83.33 / 66.67

`_TB_DISCOVERY_ORDER` puts `phase2/stage1/sim/tb/*.v` ahead of
`sim_unit/tb_*.v`, and discovery took the FIRST candidate its stimulus audit
called driven. While those files were the generator's substance-floor scaffolds
they were inert, so selection fell through to the unit testbench. The moment a
real per-case oracle suite was authored into that directory the alphabetically
first member drove the design, selection stopped, and the run published
`blinky_hex`'s 68.89% as the design's coverage and failed a 70% floor with it.
Nothing about the design had changed; the verification had got BETTER.

The ten members individually span line 63.70%-97.78%. Their union is 98.52%.

AND THE TOOL CANNOT MERGE THEM. `verilator_coverage --write` over the ten
coverage.dat files returns a line total of 1350 — 135 x 10 — because the records
are byte-identical apart from the `h` field, which carries the TESTBENCH's
instance path. The same design point seen by two testbenches is two records.
That is why a union needs a key, and why a wrong union is worse than no union:
it multiplies the denominator by the number of runs.

Both directions are pinned, including every way this could go wrong quietly:
a member that fails to build, a format whose records cannot be keyed, an
explicit --tb, and a suite whose FIRST member is the inert one.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import verilator_coverage_measure as V  # noqa: E402


# ── record helpers: the real v5 shape, byte for byte ──────────────────────

def _rec(*, cat: str, src: str, line: int, point: str, hier: str,
         hits: int) -> str:
    blob = (f"\x01f\x02{src}\x01l\x02{line}\x01n\x0214"
            f"\x01t\x02{cat}\x01page\x02v_{cat}/dut"
            f"\x01o\x02{point}\x01h\x02{hier}")
    return f"C '{blob}' {hits}\n"


def _dat(tmp_path, name: str, hier: str, points) -> str:
    """One instrumented run's coverage.dat: `points` is (cat, line, name, hits)."""
    p = tmp_path / f"{name}.dat"
    p.write_text("".join(
        _rec(cat=c, src="/x/rtl/dut.v", line=ln, point=nm, hier=hier, hits=h)
        for c, ln, nm, h in points))
    return str(p)


# ── the key ───────────────────────────────────────────────────────────────

def test_the_same_point_seen_by_two_testbenches_is_one_point():
    a = "\x01f\x02/x/dut.v\x01l\x0210\x01page\x02v_line/dut\x01h\x02blinky.u_dut"
    b = "\x01f\x02/x/dut.v\x01l\x0210\x01page\x02v_line/dut\x01h\x02rv32i.u_dut"
    assert a != b
    assert V.coverage_point_key(a) == V.coverage_point_key(b)


def test_two_genuinely_different_points_stay_different():
    a = "\x01f\x02/x/dut.v\x01l\x0210\x01page\x02v_line/dut\x01h\x02t.u"
    b = "\x01f\x02/x/dut.v\x01l\x0211\x01page\x02v_line/dut\x01h\x02t.u"
    assert V.coverage_point_key(a) != V.coverage_point_key(b)


def test_a_record_with_no_hierarchy_cannot_be_keyed():
    """THE SAFETY PROPERTY. Returning the raw blob here would double every
    denominator instead of refusing."""
    assert V.coverage_point_key(
        "\x01f\x02/x/dut.v\x01l\x0210\x01page\x02v_line/dut") is None


# ── the union ─────────────────────────────────────────────────────────────

def test_a_point_covered_by_any_run_is_covered(tmp_path):
    a = _dat(tmp_path, "a", "a.u", [("line", 10, "p10", 3), ("line", 11, "p11", 0)])
    b = _dat(tmp_path, "b", "b.u", [("line", 10, "p10", 0), ("line", 11, "p11", 7)])
    u = V.union_coverage_dats([a, b])
    assert u["unionisable"] is True
    assert u["totals"]["line"] == {"covered": 2, "total": 2, "pct": 100.0}


def test_the_denominator_does_not_multiply_by_the_number_of_runs(tmp_path):
    """The exact defect `verilator_coverage --write` has: ten runs of a
    135-point design returned 1350."""
    pts = [("line", n, f"p{n}", 0) for n in range(10)]
    dats = [_dat(tmp_path, f"r{i}", f"tb{i}.u", pts) for i in range(10)]
    u = V.union_coverage_dats(dats)
    assert u["totals"]["line"]["total"] == 10, u["totals"]
    assert u["distinct_points"] == 10
    assert u["runs_unioned"] == 10


def test_an_uncovered_point_stays_uncovered(tmp_path):
    """The union may not invent coverage: a point no run hit is not covered."""
    a = _dat(tmp_path, "a", "a.u", [("line", 10, "p10", 1), ("line", 11, "p11", 0)])
    b = _dat(tmp_path, "b", "b.u", [("line", 10, "p10", 1), ("line", 11, "p11", 0)])
    u = V.union_coverage_dats([a, b])
    assert u["totals"]["line"] == {"covered": 1, "total": 2, "pct": 50.0}


def test_categories_are_kept_apart(tmp_path):
    a = _dat(tmp_path, "a", "a.u",
             [("line", 10, "p", 1), ("toggle", 10, "t", 0), ("branch", 10, "b", 1)])
    b = _dat(tmp_path, "b", "b.u",
             [("line", 10, "p", 0), ("toggle", 10, "t", 5), ("branch", 10, "b", 0)])
    u = V.union_coverage_dats([a, b])["totals"]
    assert u["line"]["covered"] == 1 and u["line"]["total"] == 1
    assert u["toggle"]["covered"] == 1 and u["toggle"]["total"] == 1
    assert u["branch"]["covered"] == 1 and u["branch"]["total"] == 1


def test_an_unkeyable_file_refuses_and_names_itself(tmp_path):
    good = _dat(tmp_path, "good", "a.u", [("line", 10, "p", 1)])
    bad = tmp_path / "bad.dat"
    bad.write_text("C '\x01f\x02/x/rtl/dut.v\x01l\x0210\x01page\x02v_line/dut' 1\n")
    u = V.union_coverage_dats([good, str(bad)])
    assert u["unionisable"] is False
    assert u["blocked_by"] == str(bad)
    assert "denominator" in u["reason"]


# ── discovery: the suite, not a member ────────────────────────────────────

def _project(tmp_path, *, unit_tb=True, cases=("blinky", "rv32i"),
             inert=()):
    p = tmp_path / "proj"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/dut.v").write_text(
        "module dut(input i_clk, input i_rst, input [7:0] i_data);\n"
        "endmodule\n")
    (p / "phase2/stage1/sim/tb").mkdir(parents=True)
    for name in cases:
        drives = "" if name in inert else "    i_data = 8'h5a;\n"
        (p / "phase2/stage1/sim/tb" / f"{name}.v").write_text(
            f"module {name};\n  reg i_clk; reg i_rst; reg [7:0] i_data;\n"
            f"  dut u_dut(.i_clk(i_clk), .i_rst(i_rst), .i_data(i_data));\n"
            f"  initial begin\n    i_clk = 0; i_rst = 1;\n{drives}  end\n"
            f"endmodule\n")
    if unit_tb:
        (p / "sim_unit").mkdir(parents=True)
        (p / "sim_unit/tb_dut.v").write_text(
            "module tb_dut;\n  reg i_clk; reg i_rst; reg [7:0] i_data;\n"
            "  dut u_dut(.i_clk(i_clk), .i_rst(i_rst), .i_data(i_data));\n"
            "  initial begin\n    i_clk = 0; i_rst = 1;\n"
            "    i_data = 8'hff;\n  end\nendmodule\n")
    return p


def _suite(project):
    """The suite the measurer will use, asked in a way BASE SOURCES can answer.

    On sources that have no suite selector at all, the suite IS the single
    testbench the one-TB rule picks — which is precisely the defect — so every
    assertion below fails on a NUMBER rather than on an AttributeError. A
    control that dies on a missing attribute proves the attribute is missing
    and nothing about the behaviour."""
    fn = getattr(V, "discover_measure_testbenches", None)
    if fn is not None:
        return fn(project)
    rtl, tb = V.discover_measure_inputs(project)
    return rtl, ([tb] if tb else [])


def test_discovery_returns_every_driving_testbench(tmp_path):
    p = _project(tmp_path)
    _rtl, tbs = _suite(p)
    names = [Path(t).name for t in tbs]
    assert "blinky.v" in names and "rv32i.v" in names
    assert "tb_dut.v" in names, "the unit testbench is part of the suite too"
    assert len(tbs) == len(set(tbs))


def test_the_one_testbench_selector_is_unchanged(tmp_path):
    """A LANDED CONTRACT. Callers that ask for one testbench still get one, and
    it is still the first driving candidate in the declared order."""
    p = _project(tmp_path)
    _rtl, tb = V.discover_measure_inputs(p)
    assert isinstance(tb, str)
    assert Path(tb).name == "blinky.v"


def test_an_inert_first_member_does_not_shrink_the_suite(tmp_path):
    p = _project(tmp_path, cases=("aaa_inert", "zzz_real"), inert=("aaa_inert",))
    _rtl, tbs = _suite(p)
    names = [Path(t).name for t in tbs]
    assert "aaa_inert.v" not in names
    assert "zzz_real.v" in names


def test_a_project_with_no_driving_stimulus_still_yields_a_candidate(tmp_path):
    p = _project(tmp_path, unit_tb=False, cases=("only",), inert=("only",))
    _rtl, tbs = _suite(p)
    assert [Path(t).name for t in tbs] == ["only.v"]


# ── the command ───────────────────────────────────────────────────────────

class _Args:
    def __init__(self, **kw):
        self.rtl = None
        self.tb = None
        self.project = None
        self.scope_file = None
        self.build_dir = None
        self.run_dir = None
        self.build_jobs = 0
        self.out = None
        # The synthetic records below carry LINE points only, so the toggle
        # and branch floors are set out of the way: this file is about WHICH
        # testbenches are measured and how their points are combined, and the
        # thresholding itself is pinned by the existing coverage suites.
        self.min_line = 70.0
        self.min_toggle = 0.0
        self.min_branch = 0.0
        self.container = ""
        self.__dict__.update(kw)


def _fake_builds(monkeypatch, tmp_path, coverage_by_tb, fail=()):
    made = []

    def _run(rtl, tb, build_dir, run_dir, exec_fn=None, build_jobs=0):
        made.append((tb, build_dir))
        if Path(tb).name in fail:
            raise SystemExit(f"verilator coverage build failed for {tb}")
        name = Path(tb).stem
        return _dat(tmp_path, f"cov_{name}", f"{name}.u", coverage_by_tb[name])

    monkeypatch.setattr(V, "verilate_tb_and_run", _run)
    monkeypatch.setattr(V, "_mounts_for", lambda c: None)
    return made


def test_the_command_publishes_the_union_and_every_member(tmp_path, monkeypatch):
    p = _project(tmp_path, unit_tb=False, cases=("blinky", "rv32i"))
    made = _fake_builds(monkeypatch, tmp_path, {
        "blinky": [("line", 10, "p10", 1), ("line", 11, "p11", 0)],
        "rv32i": [("line", 10, "p10", 0), ("line", 11, "p11", 4)]})
    out = tmp_path / "cov.json"
    rc = V.cmd_measure_tb(_Args(project=str(p), out=str(out),
                                build_dir=str(tmp_path / "b"),
                                scope_file=[str(p / "phase2/stage1/rtl/dut.v")]))
    data = json.loads(out.read_text())
    assert data["measurement_scope"] == "union-of-suite"
    assert data["totals"]["line"]["pct"] == 100.0, data["totals"]
    assert len(data["testbenches"]) == 2
    assert all(v["measured"] for v in data["per_testbench"].values())
    # each member keeps its own honest number beside the union
    per = {Path(k).stem: v["totals"]["line"]["pct"]
           for k, v in data["per_testbench"].items()}
    assert per == {"blinky": 50.0, "rv32i": 50.0}
    assert rc == 0
    # and each member was built in its OWN directory — a shared one would let a
    # later build overwrite an earlier coverage.dat
    assert len({b for _t, b in made}) == 2


def test_an_explicit_testbench_still_measures_exactly_that_one(tmp_path, monkeypatch):
    p = _project(tmp_path, unit_tb=False, cases=("blinky", "rv32i"))
    _fake_builds(monkeypatch, tmp_path, {
        "blinky": [("line", 10, "p10", 1), ("line", 11, "p11", 0)]})
    out = tmp_path / "cov.json"
    V.cmd_measure_tb(_Args(project=str(p), out=str(out),
                           tb=str(p / "phase2/stage1/sim/tb/blinky.v"),
                           build_dir=str(tmp_path / "b"),
                           scope_file=[str(p / "phase2/stage1/rtl/dut.v")]))
    data = json.loads(out.read_text())
    assert data["measurement_scope"] == "single-testbench"
    assert data["totals"]["line"]["pct"] == 50.0
    assert Path(data["testbench"]).name == "blinky.v"


def test_a_member_that_would_not_build_is_disclosed_not_dropped(
        tmp_path, monkeypatch):
    p = _project(tmp_path, unit_tb=False, cases=("blinky", "rv32i"))
    _fake_builds(monkeypatch, tmp_path, {
        "rv32i": [("line", 10, "p10", 1), ("line", 11, "p11", 1)]},
        fail=("blinky.v",))
    out = tmp_path / "cov.json"
    rc = V.cmd_measure_tb(_Args(project=str(p), out=str(out),
                                build_dir=str(tmp_path / "b"),
                                scope_file=[str(p / "phase2/stage1/rtl/dut.v")]))
    data = json.loads(out.read_text())
    failed = [v for k, v in data["per_testbench"].items()
              if Path(k).name == "blinky.v"][0]
    assert failed["measured"] is False
    assert "build failed" in failed["reason"]
    assert [Path(t).name for t in data["testbenches"]] == ["rv32i.v"]
    assert rc == 0


def test_no_member_that_built_is_a_refusal_not_a_zero(tmp_path, monkeypatch):
    p = _project(tmp_path, unit_tb=False, cases=("blinky",))
    _fake_builds(monkeypatch, tmp_path, {}, fail=("blinky.v",))
    out = tmp_path / "cov.json"
    rc = V.cmd_measure_tb(_Args(project=str(p), out=str(out),
                                build_dir=str(tmp_path / "b")))
    assert rc == 1
    assert not out.exists()


def test_an_unkeyable_format_falls_back_to_one_member_and_says_so(
        tmp_path, monkeypatch):
    """Reporting a concatenated denominator would be worse than reporting one
    member's honest number — but it may not do it silently."""
    p = _project(tmp_path, unit_tb=False, cases=("blinky", "rv32i"))

    def _run(rtl, tb, build_dir, run_dir, exec_fn=None, build_jobs=0):
        name = Path(tb).stem
        d = tmp_path / f"nokey_{name}.dat"
        d.write_text("C '\x01f\x02/x/rtl/dut.v\x01l\x0210"
                     "\x01page\x02v_line/dut' 1\n")
        return str(d)

    monkeypatch.setattr(V, "verilate_tb_and_run", _run)
    monkeypatch.setattr(V, "_mounts_for", lambda c: None)
    out = tmp_path / "cov.json"
    V.cmd_measure_tb(_Args(project=str(p), out=str(out),
                           build_dir=str(tmp_path / "b"),
                           scope_file=["/x/rtl/dut.v"]))
    data = json.loads(out.read_text())
    assert data["measurement_scope"] == "single-testbench"
    assert "could not be unioned" in data["union_refused"]
    assert data["totals"]["line"]["total"] == 1, "the denominator did not double"


# ── the judging side ──────────────────────────────────────────────────────

def test_a_suite_is_driven_when_any_member_drives(tmp_path, capsys):
    """Refusing a suite because its FIRST member is inert would re-introduce,
    on the judging side, the one-member-stands-for-the-whole error the
    measuring side just stopped making."""
    p = _project(tmp_path, unit_tb=False, cases=("aaa_inert", "zzz_real"),
                 inert=("aaa_inert",))
    tbs = [str(p / "phase2/stage1/sim/tb/aaa_inert.v"),
           str(p / "phase2/stage1/sim/tb/zzz_real.v")]
    dat = tmp_path / "x.dat"
    dat.write_text(_rec(cat="line", src="/x/rtl/dut.v", line=10, point="p",
                        hier="zzz_real.u_dut", hits=1))
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps({
        "tool": "verilator", "measurement_mode": "measure-tb",
        "coverage_dat": str(dat),
        "testbench": tbs[0], "testbenches": tbs,
        "measurement_scope": "union-of-suite",
        "rtl_sources": [str(p / "phase2/stage1/rtl/dut.v")],
        "scope_files": [str(p / "phase2/stage1/rtl/dut.v")],
        "totals": {"line": {"covered": 9, "total": 10, "pct": 90.0},
                   "toggle": {"covered": 9, "total": 10, "pct": 90.0},
                   "branch": {"covered": 9, "total": 10, "pct": 90.0}},
        "per_file": {}, "format_detected": "v5",
        "path_namespace": {"reported_in": "host"}}))
    rc = V.cmd_check(_Args(coverage_json=str(cov)))
    text = capsys.readouterr()
    assert rc == 0, text.out + text.err
    assert "not instrumented" not in (text.out + text.err)


# ── the whole-project control ─────────────────────────────────────────────
# A REAL project's shape, BUILT HERE. The measured case that produced this fix
# had testbenches in TWO discovery roots at once — nine authored L10 oracles in
# `phase2/stage1/sim/tb` and the unit testbench in `sim_unit` — and the defect
# was precisely that the first root won outright. A control that only ever sees
# one root cannot fail that way, so this one spans the roots.

def test_a_whole_project_suite_is_discovered_across_every_root(tmp_path):
    """The suite is the union of the discovery ROOTS, de-duplicated, and the
    one-testbench selector's pick is a MEMBER of it — never a set the suite
    does not contain."""
    p = _project(tmp_path, unit_tb=True,
                 cases=("blinky_hex", "hello_hex", "rv32i_40", "zifencei"))
    # a third root, the connectivity harness the discovery order puts FIRST
    (p / "phase2/stage1/sim_full_stack").mkdir(parents=True)
    (p / "phase2/stage1/sim_full_stack/tb_dut_full.v").write_text(
        "module tb_dut_full;\n  reg i_clk; reg i_rst; reg [7:0] i_data;\n"
        "  dut u_dut(.i_clk(i_clk), .i_rst(i_rst), .i_data(i_data));\n"
        "  initial begin\n    i_clk = 0; i_rst = 1;\n  end\nendmodule\n")

    _rtl, tbs = _suite(p)
    names = sorted(Path(t).name for t in tbs)
    assert names == ["blinky_hex.v", "hello_hex.v", "rv32i_40.v",
                     "tb_dut.v", "zifencei.v"], names
    assert len(tbs) > 1, "this control needs a SUITE, not one testbench"
    assert len(tbs) == len(set(tbs)), "a testbench was counted twice"
    # the inert connectivity harness is in the tree and is NOT in the suite
    assert "tb_dut_full.v" not in names
    # and the one-testbench selector's pick is one of these, not a sixth thing
    one = V.discover_measure_inputs(p)[1]
    assert one in tbs
    assert Path(one).name == "blinky_hex.v"


def test_the_suite_spans_roots_that_the_first_match_rule_would_have_cut(tmp_path):
    """THE DEFECT, in project shape: `phase2/stage1/sim/tb` comes before
    `sim_unit` in the discovery order, so the one-testbench rule stops at the
    first root that has a driving member and never reaches the second. The
    suite must contain BOTH."""
    p = _project(tmp_path, unit_tb=True, cases=("aaa_case",))
    _rtl, tbs = _suite(p)
    roots = {Path(t).parent.name for t in tbs}
    assert roots == {"tb", "sim_unit"}, roots
    assert V.discover_measure_inputs(p)[1].endswith("aaa_case.v")


# ── THE PRODUCER THE FLOW ACTUALLY RUNS ───────────────────────────────────
# The fix above first landed in `verilator_coverage_measure`'s CLI, and every
# real run was unaffected: `design_one_shot_runner.step_verilator_coverage`
# held a SECOND copy of the same logic and called the one-testbench selector.
# MEASURED on subservient r21, on a main carrying the landed union code —
# `measurement_scope: None`, `testbenches: 0`, totals still `blinky_hex`'s
# 68.89 / 83.33 / 66.67. A test that only drives the CLI cannot see that, so
# this one drives the step.
