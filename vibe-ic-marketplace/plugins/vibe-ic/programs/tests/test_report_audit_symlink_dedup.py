"""Regression: _discover must not count a report twice via its step symlink.

MEASURED DEFECT (sha256 x sky130A, plugin v1.9.76, round 11)
------------------------------------------------------------
The step runners publish each canonical report a SECOND time as a symlink
under ``steps/<phase>/<stage>/<step>/``.  ``_discover`` deduplicated on the
literal ``Path`` object, so the symlink and its target were two distinct keys
and BOTH survived — even though ``stat -L`` shows one inode and ``md5sum``
shows one file.  Every per-file quantity was then summed twice.

On the real run dir /home/<your-user>/_c_o_sha256_sky130A_run/g3:

    reports/phase3/drc_signoff.rpt                     inode 88639058
    steps/.../31_physical_verification.../drc_signoff.rpt -> same inode

    drc_report_check      real_violation_total = 22   <-- 11 counted twice
    tapeout_signoff_check violation count      = 11   <-- correct

i.e. two gates in the SAME run reported different counts for the same design.
The XML actually contains 11 ``<item>`` elements.

This does not flip the DRC verdict (any count > 0 is already an ERROR, and
0 * 2 == 0), so it is a REPORTING-accuracy defect, not a missed failure. It
is chip-AGNOSTIC: the symlink publication happens for every design and every
mode that eda_report_audit serves (drc/lvs/em/ir/sta/power).

Both directions are asserted below: the double-count fixture must collapse to
the true count, AND a genuinely distinct second report must still be counted
separately (so the fix cannot be "silently drop the second file").

THE KEY IS INODE IDENTITY (``(st_dev, st_ino)`` from a link-following
``stat()``), not resolved-path identity — see ``_identity``.  It is the wider
and the cheaper of the two: it also collapses a HARD-linked publication, which
``resolve()`` counts twice, and it leaves an unreadable path (dangling link,
symlink loop) on its own literal key, which is exactly the pre-dedup behaviour
for that path.  Both are pinned below.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
SCRIPT = PROGRAMS / 'eda_report_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as era  # noqa: E402


def _klayout_drc(n_items: int, top: str = "top") -> str:
    """A tool-authentic KLayout report database carrying exactly n_items."""
    items = "".join(
        """  <item>
   <category>'m5.1'</category>
   <cell>%s</cell>
   <values><value>edge-pair: (%d.0,1.0;%d.0,2.0)</value></values>
  </item>
""" % (top, i, i)
        for i in range(n_items)
    )
    return """<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>klayout DRC</description>
 <original-file>/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc</original-file>
 <top-cell>%s</top-cell>
 <categories><category><name>m5.1</name></category></categories>
 <items>
%s </items>
</report-database>
""" % (top, items)


def _audit(project: Path, out: Path):
    rc = subprocess.run(
        [sys.executable, str(PROGRAMS / 'drc_report_check.py'), str(project),
         '--mode', 'drc', '--json', str(out)],
        capture_output=True, text=True,
    )
    import json
    return rc, json.loads(out.read_text())['summary']


def test_step_symlink_is_not_counted_twice(tmp_path):
    """The canonical report + its step symlink are ONE physical file."""
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    step = tmp_path / 'steps/phase3/stage3/31_pv'
    step.mkdir(parents=True)

    rpt = tmp_path / 'reports/phase3/drc_signoff.rpt'
    rpt.write_text(_klayout_drc(3))
    (step / 'drc_signoff.rpt').symlink_to(rpt.resolve())   # what the runner publishes

    _, summary = _audit(tmp_path, tmp_path / 'out.json')

    assert summary['files_found'] == 1, (
        "the symlink and its target are one inode; discovering both double-counts "
        f"every per-file quantity (got files_found={summary['files_found']})"
    )
    assert summary['real_violation_total'] == 3, (
        "report carries 3 <item> elements; a path-keyed dedup reports 6 "
        f"(got {summary['real_violation_total']})"
    )


def test_genuinely_distinct_reports_are_still_counted_separately(tmp_path):
    """Negative control for the fix itself: two REAL files must stay two.

    Guards against 'fixing' the double-count by collapsing unrelated reports
    that merely share a basename.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    step = tmp_path / 'steps/phase3/stage3/31_pv'
    step.mkdir(parents=True)

    (tmp_path / 'reports/phase3/drc_signoff.rpt').write_text(_klayout_drc(3, "top_a"))
    (step / 'drc_signoff.rpt').write_text(_klayout_drc(4, "top_b"))  # real file, not a link

    _, summary = _audit(tmp_path, tmp_path / 'out.json')

    assert summary['files_found'] == 2, (
        f"two independent reports must both be audited (got {summary['files_found']})"
    )
    assert summary['real_violation_total'] == 7, (
        f"3 + 4 distinct violations must sum (got {summary['real_violation_total']})"
    )


def test_discover_keys_on_the_physical_file(tmp_path):
    """Unit-level: _discover collapses a symlink onto its target."""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    real = tmp_path / 'a' / 'x.rpt'
    real.write_text("klayout\n")
    (tmp_path / 'b' / 'x.rpt').symlink_to(real.resolve())

    found = era._discover(tmp_path, ['x.rpt'])
    assert len(found) == 1, f"symlink + target must collapse to one entry, got {found}"


def test_a_hard_link_is_the_same_physical_file_too(tmp_path):
    """`(st_dev, st_ino)`, not `resolve()`.

    A hard link IS the same inode and the same bytes — `md5sum` cannot tell
    the two apart — but `Path.resolve()` returns two different paths for it,
    so a resolved-path key counts the report twice exactly the way the literal
    key did. The corpus holds no hard-linked report today; the key is the
    wider one because being right about the second aliasing mechanism costs
    nothing and a `cp -l` publication step would otherwise reintroduce the
    whole defect silently.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    rpt = tmp_path / 'reports/phase3/drc_signoff.rpt'
    rpt.write_text(_klayout_drc(5))
    step = tmp_path / 'steps/phase3/stage3/31_pv'
    step.mkdir(parents=True)
    os.link(rpt, step / 'drc_signoff.rpt')          # hard link, not symlink

    assert (step / 'drc_signoff.rpt').stat().st_ino == rpt.stat().st_ino
    assert not (step / 'drc_signoff.rpt').is_symlink()

    _, summary = _audit(tmp_path, tmp_path / 'out.json')
    assert summary['files_found'] == 1, (
        f"a hard link is one inode and one file (got "
        f"files_found={summary['files_found']})")
    assert summary['real_violation_total'] == 5, (
        f"5 <item> elements, counted once (got "
        f"{summary['real_violation_total']})")


def test_two_broken_symlinks_are_not_merged_by_their_shared_dead_target(tmp_path):
    """An unreadable path is keyed on its LITERAL path — pre-dedup behaviour.

    `Path.resolve(strict=False)` happily returns the DANGLING target of a
    broken symlink, so a resolved-path key merges two DIFFERENT dead links
    that happen to name the same missing file — a merge that no measurement
    backs, on paths whose bytes nothing can read. `stat()` fails on both, so
    both keep their own key and the audit reports what is actually on disk.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    (tmp_path / 'reports/phase3/drc_signoff.rpt').write_text(_klayout_drc(2))
    for name in ('drc_dead_a.rpt', 'drc_dead_b.rpt'):
        (tmp_path / 'reports/phase3' / name).symlink_to('gone.rpt')

    found = era._discover(tmp_path, ['drc*.rpt'])
    assert sorted(p.name for p in found) == [
        'drc_dead_a.rpt', 'drc_dead_b.rpt', 'drc_signoff.rpt'], (
        f"two distinct dead links must stay two entries "
        f"(got {sorted(p.name for p in found)})")


# ── Ordering / degradation constraints the alias key imposes ───────────────
#
# Both are asserted through the REAL entry points, and both were measured
# before being fixed.


def _drc_loop_tree(tmp_path):
    """One readable sign-off report plus a mutually-pointing symlink pair."""
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    (tmp_path / 'reports/phase3/drc_signoff.rpt').write_text(_klayout_drc(11))
    a = tmp_path / 'reports/phase3/drc_a.rpt'
    b = tmp_path / 'reports/phase3/drc_b.rpt'
    a.symlink_to(b)
    b.symlink_to(a)


@pytest.mark.parametrize('extra,label', [
    ([], 'project-wide'),
    (['--under', 'reports/phase3/drc_signoff.rpt'], '--under'),
])
def test_symlink_loop_returns_a_verdict_not_a_traceback(tmp_path, extra, label):
    """A mutually-pointing pair of report-named symlinks must not abort the run.

    `Path.resolve()` raises a bare ``RuntimeError`` for ELOOP on CPython
    (``pathlib.check_eloop``), NOT an ``OSError`` — so an ``except OSError``
    written for exactly this case never fires. `_in_scope` had that narrow
    guard, and `_in_scope` runs on EVERY scoped call site: `--under` is what
    the DRC sign-off gate, router DRC, both STA gates and
    `drc_vacuous_pass_check` are invoked with in
    `flow/phase1_phase2_phase3.yaml`. Reproduced through the production
    command `drc_report_check.py . --mode drc --signoff --under
    reports/phase3/drc_signoff.rpt`::

        except OSError               json written: NO
                                     RuntimeError: Symlink loop from '.../drc_a.rpt'
        except (OSError, RuntimeError)
                                     json written: YES  files_found=1

    BOTH discovery modes are driven here. A single-mode test is how the
    project-wide path came to be guarded while the default path — the one the
    flow actually takes — still crashed.
    """
    _drc_loop_tree(tmp_path)

    out = tmp_path / 'out.json'
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / 'drc_report_check.py'), '.',
         '--mode', 'drc', *extra, '--json', str(out)],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert 'Traceback' not in r.stderr, (
        f"[{label}] the audit crashed instead of judging:\n{r.stderr}")
    assert out.exists(), f"[{label}] no verdict document was written"
    summary = json.loads(out.read_text())['summary']
    assert summary['real_violation_total'] == 11, (
        f"[{label}] the readable report's 11 items must still be counted "
        f"(got {summary['real_violation_total']})")


def test_symlink_loop_does_not_remove_readable_reports_from_discovery(tmp_path):
    """Project-wide, the loop's own paths stay in the file set.

    `stat()` reports ELOOP as a plain `OSError`, so `_identity` degrades to
    the literal path and the two dead links keep their own keys — nothing a
    looping symlink does can evict a readable report.
    """
    _drc_loop_tree(tmp_path)
    found = era._discover(tmp_path, ['drc*.rpt'])
    assert sorted(p.name for p in found) == [
        'drc_a.rpt', 'drc_b.rpt', 'drc_signoff.rpt'], (
        f"a symlink loop must not remove readable reports from discovery "
        f"(got {sorted(p.name for p in found)})")


def test_a_scoped_loop_cannot_buy_a_green(tmp_path):
    """The fail-safe direction of `_in_scope`'s degradation.

    An unresolvable path is not in scope, so the degradation can only SHRINK
    the discovered set — and an empty set is already an ERROR. A run whose
    ONLY declared artefact is a symlink loop must FAIL, not pass quietly on
    nothing.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    a = tmp_path / 'reports/phase3/drc_signoff.rpt'
    b = tmp_path / 'reports/phase3/drc_signoff_alt.rpt'
    a.symlink_to(b)
    b.symlink_to(a)

    out = tmp_path / 'out.json'
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / 'drc_report_check.py'), '.',
         '--mode', 'drc', '--under', 'reports/phase3/drc_signoff.rpt',
         '--json', str(out)],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert 'Traceback' not in r.stderr, r.stderr
    assert r.returncode == 1, "a run with no readable DRC report must not pass"
    doc = json.loads(out.read_text())
    assert doc['summary']['files_found'] == 0, doc['summary']
    assert 'DRC_REPORT_EXISTS' in {f.get('rule') for f in doc['findings']}, \
        doc['findings']


@pytest.mark.parametrize('alias_first', [True, False],
                         ids=['alias_first', 'canonical_first'])
def test_filtered_alias_does_not_burn_the_canonical_reports_key(
        tmp_path, monkeypatch, alias_first):
    """A backup alias reached FIRST must not consume the key its target needs.

    `_is_backup_path` keys on the LITERAL path, `seen` keys on the RESOLVED
    one. With `seen.add(key)` above the filters, a same-inode alias under a
    `*_bak/` directory claimed the resolved key and was then dropped, so the
    canonical report was skipped as a duplicate of a path that is not in the
    output. Measured, one report plus one alias::

        alias reached first   _discover -> []            files_found=0
        alias reached later   _discover -> [drc_signoff] files_found=1

    Only a path that SURVIVES the filters may claim the key.

    ORDER IS FORCED, NOT ASSUMED. This test used to build the "alias reached
    first" condition by asserting that `rglob` yields the shallower
    `backup_bak/` match before `reports/phase3/`. `Path.rglob` walks each
    directory in `os.scandir` order, which is filesystem-dependent, so that
    precondition is not a property of `rglob` at all -- on ext4 here the walk
    comes back `['reports/phase3/drc_signoff.rpt', 'backup_bak/drc_signoff.rpt']`
    and the test fails in its own fixture without ever reaching the behaviour it
    exists to check.

    Since the guarantee under test is that the verdict is INDEPENDENT of walk
    order, the order is now pinned explicitly and the property asserted in BOTH
    directions. That is strictly stronger than the original: it no longer needs
    a particular filesystem to construct the interesting case, and it now also
    covers the order the original could never reach.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    rpt = tmp_path / 'reports/phase3/drc_signoff.rpt'
    rpt.write_text(_klayout_drc(11))

    alias_dir = tmp_path / 'backup_bak'
    alias_dir.mkdir()
    (alias_dir / 'drc_signoff.rpt').symlink_to(rpt.resolve())

    # Pin the walk order instead of hoping the filesystem produces it. The
    # harness assertion below fails loudly if the ordering did not take, so a
    # silently-unordered run cannot masquerade as a pass.
    real_rglob = Path.rglob

    def _ordered_rglob(self, pattern):
        hits = list(real_rglob(self, pattern))
        hits.sort(key=lambda p: (0 if 'backup_bak' in p.parts else 1))
        if not alias_first:
            hits.reverse()
        return iter(hits)

    monkeypatch.setattr(Path, 'rglob', _ordered_rglob)

    walk = [str(p.relative_to(tmp_path)) for p in tmp_path.rglob('drc*.rpt')]
    wanted = 'backup_bak/' if alias_first else 'reports/'
    assert walk[0].startswith(wanted), (
        f"order harness did not take: wanted {wanted!r} first, got {walk}")

    found = era._discover(tmp_path, ['drc*.rpt'])
    assert [str(p.relative_to(tmp_path)) for p in found] == [
        'reports/phase3/drc_signoff.rpt'], (
        f"the canonical report must survive a filtered alias regardless of walk "
        f"order (alias_first={alias_first}, walk={walk}, got "
        f"{[str(p.relative_to(tmp_path)) for p in found]})")

    # The audit itself is a SUBPROCESS, so the in-process ordering patch above
    # does not reach it; these two assertions are therefore order-agnostic
    # properties of the shipped program, which is what we want from them.
    monkeypatch.setattr(Path, 'rglob', real_rglob)

    _, summary = _audit(tmp_path, tmp_path / 'out.json')
    assert summary['files_found'] == 1, (
        f"the report exists; a dropped alias must not hide it "
        f"(got files_found={summary['files_found']})")
    assert summary['real_violation_total'] == 11, (
        f"11 real violations must still be reported "
        f"(got {summary['real_violation_total']})")


def test_backup_alias_is_still_filtered_when_reached_last(tmp_path):
    """Negative control: moving `seen.add` down must not RESURRECT backups.

    The alias is still a backup path; it must be dropped whichever order it is
    reached in, and it must not be counted a second time.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    rpt = tmp_path / 'reports/phase3/drc_signoff.rpt'
    rpt.write_text(_klayout_drc(11))
    alias_dir = tmp_path / 'reports/phase3/sub/backup_bak'   # deeper: reached last
    alias_dir.mkdir(parents=True)
    (alias_dir / 'drc_signoff.rpt').symlink_to(rpt.resolve())

    found = era._discover(tmp_path, ['drc*.rpt'])
    assert [str(p.relative_to(tmp_path)) for p in found] == [
        'reports/phase3/drc_signoff.rpt'], (
        f"the backup alias must stay filtered (got "
        f"{[str(p.relative_to(tmp_path)) for p in found]})")

    _, summary = _audit(tmp_path, tmp_path / 'out.json')
    assert summary['real_violation_total'] == 11, (
        f"the backup alias must not add a second count "
        f"(got {summary['real_violation_total']})")


# ── The same rule for the ONE filter that used to live outside _discover ───


def _sta(project: Path, out: Path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / 'sta_report_check.py'), str(project),
         '--mode', 'sta', '--json', str(out)],
        capture_output=True, text=True)
    doc = json.loads(out.read_text())
    return r.returncode, doc


_STA_MET = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\ndata arrival time: 2.34 ns\ndata required time: 2.49 ns\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n0.15   slack (MET)\n"
    "setup check: PASS\nhold check: PASS\n"
    + "# " + ("=" * 78 + "\n") * 20
)


def test_an_excluded_name_alias_does_not_erase_the_sta_report(tmp_path):
    """The name filter must run INSIDE `_discover`, for the same reason.

    `_check_sta` drops names carrying a foreign report class
    (`crosstalk`/`si_`/`noise`/`antenna`/`drc`/`lvs`/`_em.`/`ir_drop`/
    `power`). Applied to `_discover`'s RESULT, that filter is downstream of
    the alias dedup, so an alias whose basename carries an excluded token can
    claim the canonical report's key, evict it, and then be deleted by the
    filter — leaving the mode with ZERO files and a fabricated
    `STA_REPORT_EXISTS` FAIL for a design whose STA report is right there::

        filter downstream of _discover   passed=False files_found=0
                                         ['STA_REPORT_EXISTS']
        filter inside _discover          passed=True  files_found=1

    `step_output_collector` renames a mirrored artefact to
    `{parent.name}__{basename}` on a basename collision, so a mirror basename
    the canonical report does not have is a shape the flow itself produces.
    """
    (tmp_path / 'phase3/stage3/sta').mkdir(parents=True)
    rpt = tmp_path / 'phase3/stage3/sta/pre_pnr_timing.rpt'
    rpt.write_text(_STA_MET)

    # shallower than the canonical -> rglob yields it first
    step = tmp_path / 'steps'
    step.mkdir()
    (step / 'drc_lvs__pre_pnr_timing.rpt').symlink_to(rpt.resolve())

    walk = [str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*timing*.rpt')]
    assert walk[0].startswith('steps/'), (
        f"fixture precondition: the excluded-name alias must be walked first "
        f"(got {walk})")

    rc, doc = _sta(tmp_path, tmp_path / 'sta.json')
    rules = {f.get('rule') for f in doc.get('findings') or []}
    assert doc['summary']['files_found'] == 1, (
        f"the STA report exists; an alias the name filter deletes must not "
        f"take it with it (got {doc['summary']})")
    assert 'STA_REPORT_EXISTS' not in rules, rules
    assert rc == 0, rules


def test_the_excluded_name_filter_still_excludes(tmp_path):
    """Negative control: moving the filter must not stop it filtering.

    A genuine crosstalk report carries no OpenSTA signature and must stay out
    of the STA authenticity check — that is what the token list is FOR.
    """
    (tmp_path / 'reports/phase3').mkdir(parents=True)
    (tmp_path / 'reports/phase3/pre_pnr_timing.rpt').write_text(_STA_MET)
    (tmp_path / 'reports/phase3/si_crosstalk_sta.rpt').write_text(
        "KLayout SI noise summary\nvictim/aggressor pairs: 4\n" + "x" * 4000)

    rc, doc = _sta(tmp_path, tmp_path / 'sta.json')
    assert doc['summary']['files_found'] == 1, (
        f"the crosstalk report is not an STA report and must not be swept "
        f"into the STA check (got {doc['summary']})")
    assert doc['summary']['tool_authentic'] is True, doc['summary']
    assert rc == 0, [f.get('rule') for f in doc.get('findings') or []]
