"""The guard that no OpenROAD invocation runs unmeasured. W5.

BIDIRECTIONAL, because a guard only ever seen to pass has not been shown to
check anything. Every property below is asserted in both directions on a
synthetic tree: the shape it must catch FAILS, and the shape it must accept
PASSES, on the same code path.

THE FOUR WAYS THIS CHECK COULD BE DISHONEST, each pinned:

* It could pass by seeing nothing. An empty scan is rc 2 NOT CHECKED, never 0.
* It could count a DOCSTRING that quotes a command as a call site, which would
  make the check unlandable and then make someone loosen it. Docstrings are
  skipped through `ast`, and that is asserted rather than assumed.
* It could accept a stale exemption forever. A register entry matching nothing
  is itself a failure.
* It could accept a rubber-stamp exemption. Reasons are length-floored.

It also pins the WIRED-VIA distinction: a literal `-metrics` and a command
routed through `openroad_metrics.with_metrics` are both wired, and the second is
the spelling the call sites actually use — a check that only understood the
literal would have reported the whole migrated tree as unwired.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

_SUBPROC_S = 60

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
REPO = PLUGIN.parent.parent.parent

sys.path.insert(0, str(PROGRAMS))
import openroad_metrics_wiring_check as wc  # noqa: E402


def _tree(tmp_path, name, source):
    """A minimal plugin-shaped tree with one shipped program in it."""
    d = tmp_path / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


UNWIRED = '''
    def run(container, tcl_c, out_dir_c):
        cmd = (f"export PATH=/foss/tools/openroad/bin:$PATH && "
               f"openroad -no_init -exit {tcl_c} 2>&1 | "
               f"tee {out_dir_c}/openroad.log")
        return cmd
    '''

WIRED_LITERAL = '''
    def run(container, tcl_c, out_dir_c):
        cmd = (f"export PATH=/foss/tools/openroad/bin:$PATH && "
               f"openroad -metrics {out_dir_c}/openroad.metrics.json "
               f"-no_init -exit {tcl_c} 2>&1 | "
               f"tee {out_dir_c}/openroad.log")
        return cmd
    '''

WIRED_VIA_WRAPPER = '''
    import openroad_metrics as _om

    def run(container, tcl_c, out_dir_c):
        cmd = _om.with_metrics(
              f"export PATH=/foss/tools/openroad/bin:$PATH && "
              f"openroad -no_init -exit {tcl_c} 2>&1 | "
              f"tee {out_dir_c}/openroad.log")
        return cmd
    '''

ONLY_A_DOCSTRING = '''
    """A note about the flow.

    The runner used to build `openroad -no_init -exit pnr.tcl 2>&1 | tee x.log`
    by hand, which is why this module exists.
    """
    VALUE = 1
    '''


# ---------------------------------------------------------------------------
# the negative direction — it must FAIL on the shape it exists to catch
# ---------------------------------------------------------------------------
def test_an_unwired_invocation_is_a_defect(tmp_path):
    rep = wc.audit(_tree(tmp_path, "runner.py", UNWIRED))
    assert rep["total"] == 1, rep
    assert len(rep["unwired"]) == 1, rep
    assert rep["defects"], rep
    assert "without `-metrics`" in rep["defects"][0]


# ---------------------------------------------------------------------------
# the positive direction — it must PASS on both wired spellings
# ---------------------------------------------------------------------------
def test_a_literal_metrics_flag_is_wired(tmp_path):
    rep = wc.audit(_tree(tmp_path, "runner.py", WIRED_LITERAL))
    assert rep["wired"] == 1 and not rep["unwired"], rep
    assert rep["sites"][0]["wired_via"] == "literal", rep["sites"]


def test_a_command_routed_through_the_wrapper_is_wired(tmp_path):
    """The spelling the real call sites use. A check that only understood the
    literal flag would have called the entire migrated tree unwired."""
    rep = wc.audit(_tree(tmp_path, "runner.py", WIRED_VIA_WRAPPER))
    assert rep["wired"] == 1 and not rep["unwired"], rep
    assert rep["sites"][0]["wired_via"] == wc.WRAPPER, rep["sites"]


def test_a_command_quoted_in_a_docstring_is_not_a_call_site(tmp_path):
    rep = wc.audit(_tree(tmp_path, "notes.py", ONLY_A_DOCSTRING))
    assert rep["total"] == 0, rep["sites"]


def test_a_test_file_is_not_held_to_the_rule(tmp_path):
    """A test whose FIXTURE is an unwired command is doing its job; forcing the
    flag into it would delete this file's own negative control."""
    root = tmp_path
    d = root / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests"
    d.mkdir(parents=True, exist_ok=True)
    (d / "test_x.py").write_text(textwrap.dedent(UNWIRED), encoding="utf-8")
    rep = wc.audit(root)
    assert rep["total"] == 0, rep["sites"]


# ---------------------------------------------------------------------------
# the register cannot rot or rubber-stamp
# ---------------------------------------------------------------------------
def test_every_shipped_exemption_states_a_real_reason():
    for ex in wc.EXEMPTIONS:
        assert len(ex["reason"]) >= wc.MIN_REASON_CHARS, ex
        assert ex["contains"] and ex["file"], ex


def test_a_stale_exemption_is_itself_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "EXEMPTIONS", [
        {"file": "programs/runner.py",
         "contains": "openroad -no_init -exit a_command_that_moved_away.tcl",
         "reason": "a reason long enough to clear the anti-rubber-stamp floor"},
    ])
    rep = wc.audit(_tree(tmp_path, "runner.py", WIRED_LITERAL))
    assert any("matches nothing any more" in d for d in rep["defects"]), rep


def test_a_rubber_stamp_reason_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "EXEMPTIONS", [
        {"file": "programs/runner.py",
         "contains": "openroad -no_init -exit", "reason": "ok"},
    ])
    rep = wc.audit(_tree(tmp_path, "runner.py", UNWIRED))
    assert any("rubber stamp" in d or "the floor is" in d
               for d in rep["defects"]), rep


# ---------------------------------------------------------------------------
# an empty scan is not a pass
# ---------------------------------------------------------------------------
def test_finding_nothing_at_all_exits_two_not_zero(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "openroad_metrics_wiring_check.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=_SUBPROC_S)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "NOT CHECKED" in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# the real tree
# ---------------------------------------------------------------------------
def test_the_shipped_tree_asks_openroad_for_its_numbers():
    """The property itself, on the tree that ships. This is the assertion that
    fails the moment a thirteenth call site is written without the flag."""
    rep = wc.audit(REPO)
    assert rep["total"] > 0, "the check saw no invocation at all"
    assert not rep["unwired"], [s["file"] + ":" + str(s["line"])
                                for s in rep["unwired"]]
    assert not rep["defects"], rep["defects"]
