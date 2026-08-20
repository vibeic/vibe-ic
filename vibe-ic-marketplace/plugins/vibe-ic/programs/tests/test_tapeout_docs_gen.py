"""tapeout_docs_gen must state a measurement or say NOT_MEASURED — never a default.

The documents this program writes are the ones a reader believes. So the tests
here are about the two ways a generated document lies:

  * it fills a gap with a plausible number, and the gap becomes invisible;
  * it assembles one document out of two different runs, and every figure is
    individually true while the document as a whole is false.

Both are measured failures, not hypotheticals — on 2026-08-20 the 0p5x0p5 die
that passed precheck and the 1x1 die that carries the full metrics were both
"spm on gf180mcuD", and only comparing their bounding boxes caught it.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "tapeout_docs_gen.py"

CLEAN = {
    "design__die__bbox": "0.0 0.0 3932.0 5122.0",
    "route__drc_errors": 0, "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0, "klayout__density_error__count": 0,
    "antenna__violating__nets": 0, "antenna__violating__pins": 0,
    "design__lvs_error__count": 0, "design__lvs_unmatched_device__count": 0,
    "design__lvs_unmatched_net__count": 0, "design__lvs_unmatched_pin__count": 0,
    "design__xor_difference__count": 0,
    "timing__setup__ws": 0.5, "timing__setup__tns": 0.0,
    "timing__hold__ws": 0.3, "timing__hold__tns": 0,
    "design__max_slew_violation__count": 0, "design__max_cap_violation__count": 0,
}


def run(tmp, metrics, extra=()):
    mp = tmp / "m.json"
    mp.write_text(json.dumps(metrics), encoding="utf-8")
    out = tmp / "out"
    r = subprocess.run(
        [sys.executable, str(PROG), "--metrics", str(mp), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(out), *extra],
        capture_output=True, text=True)
    return r, out


def test_a_clean_run_is_signed_off(tmp_path):
    r, out = run(tmp_path, CLEAN)
    assert r.returncode == 0, r.stderr
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "SIGNED OFF" in html and "PARTIAL" not in html


def test_a_timing_violation_blocks_generation_entirely(tmp_path):
    """Owner, 2026-08-20: 一定要全部 pass 才會開始生成.

    A release document for a failing run is worse than none -- it is a FILE, and
    files outlive the run they came from. So the program writes NOTHING and names
    what is not clean. The ABSENCE of the documents is the signal.
    """
    m = dict(CLEAN, **{"timing__setup__ws": -1.53})
    r, out = run(tmp_path, m)
    assert r.returncode != 0, "a failing run must not silently produce documents"
    assert not (out / "SIGNOFF_d_pdk.html").exists(), "no file may be written"
    assert "NOT RELEASABLE" in r.stderr
    assert "timing__setup__ws" in r.stderr, "it must name WHICH property"


def test_a_failing_run_can_be_drafted_but_the_file_says_so(tmp_path):
    """The escape hatch must not produce a document indistinguishable from a real one."""
    m = dict(CLEAN, **{"timing__setup__ws": -1.53})
    r, out = run(tmp_path, m, extra=("--allow-incomplete",))
    assert r.returncode == 0
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "DRAFT" in html, "a draft must be stamped in the FILE, not only on the console"
    assert "不可發布" in html


def test_a_failing_drc_blocks_generation(tmp_path):
    m = dict(CLEAN, **{"magic__drc_error__count": 7})
    r, out = run(tmp_path, m)
    assert r.returncode != 0
    assert not out.exists() or not list(out.glob("*.html"))


def test_a_missing_metric_blocks_generation_too(tmp_path):
    """"We did not look" and "we looked and it was fine" must not produce the same file."""
    m = {k: v for k, v in CLEAN.items() if k != "design__lvs_error__count"}
    r, out = run(tmp_path, m)
    assert r.returncode != 0, "an unmeasured property is not a passing one"
    assert "NOT_MEASURED" in r.stderr
    assert "design__lvs_error__count" in r.stderr


def test_an_unreadable_metrics_file_is_refused(tmp_path):
    mp = tmp_path / "m.json"
    mp.write_text("{not json", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROG), "--metrics", str(mp), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(tmp_path / "o")],
        capture_output=True, text=True)
    assert r.returncode != 0, "a document must not be written from an unreadable run"


def test_two_runs_in_one_project_are_refused(tmp_path):
    """Ambiguity is refused rather than resolved by picking one."""
    proj = tmp_path / "proj"
    for slot in ("a", "b"):
        d = proj / slot / "final"
        d.mkdir(parents=True)
        (d / "metrics.json").write_text(json.dumps(CLEAN), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(PROG), "--project", str(proj), "--design", "d",
         "--pdk", "pdk", "--out-dir", str(tmp_path / "o")],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "refusing to guess" in (r.stderr + r.stdout)


def test_the_scope_section_is_always_present(tmp_path):
    """Even on a clean run, what was NOT checked must be stated."""
    r, out = run(tmp_path, CLEAN)
    html = (out / "SIGNOFF_d_pdk.html").read_text(encoding="utf-8")
    assert "未簽核的部分" in html
    assert "矽上量測" in html, "silicon measurement is never covered and must say so"
