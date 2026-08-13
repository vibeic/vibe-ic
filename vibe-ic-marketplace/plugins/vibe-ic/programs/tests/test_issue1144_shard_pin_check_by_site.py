"""Sharding the pin gate by site, without losing the denominator. vibe-ic#1144.

One landing run is 3399 s and `policy_direction_pin_check` is 671 s of it. Its
six argued sites are INDEPENDENT — each flips one literal in one file and runs
that site's own candidate tests — so they parallelise exactly.

WHAT THE MEASUREMENT CHANGED ABOUT THE DESIGN
=============================================
#1144 assumed "6 pin sites across 6 hosts: 671s -> ~120s". Measured on this
tree, one site per worktree, six in parallel:

    site                                   cost   secs
    matrix_mutation_ledger.py:2380            6    284
    phase3_one_shot_runner.py:8414          102    237
    payload_bit_position_check.py:111         2     67
    dft_test_coverage.py:180                  2     66
    phase3_one_shot_runner.py:4198            2     66
    atpg_untestable_fault_classify.py:331     2     65

    serial, same tree, same code                  518
    sharded critical path                         284

Two things fall out, and both are why this file exists rather than a one-line
`--only` loop:

  * `--only` CANNOT address a site. It matches a substring of the FILE, and
    `phase3_one_shot_runner.py` carries TWO argued sites. Sharding on it would
    put the two heaviest halves in one shard.
  * the cost PROXY (pytest invocations) has Spearman rho 0.89 against the
    clock: it sorts the two heavy sites above the four light ones and then
    INVERTS THE TOP TWO — the only pair whose order sets the critical path.
    Three slow test files beat thirty-four fast ones. So the weight is
    MEASURED, and the proxy is a declared fallback that names itself.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "policy_direction_pin_check.py"

sys.path.insert(0, str(PROGRAMS))
import policy_direction_pin_check as P  # noqa: E402

_T = 55


def _site(f: str, line: int, param: str = "on_conflict", alts=("a", "b")) -> dict:
    return {"file": f, "line": line, "param": param, "alternatives": list(alts)}


# --------------------------------------------------------------------------
# the partition
# --------------------------------------------------------------------------
def test_a_site_key_separates_two_sites_in_one_file():
    """The reason `--only` is not enough."""
    a = _site("phase3_one_shot_runner.py", 4198)
    b = _site("phase3_one_shot_runner.py", 8414, "override")
    assert P.site_key(a) != P.site_key(b)
    assert "4198" in P.site_key(a) and "8414" in P.site_key(b)


def test_every_site_lands_in_exactly_one_shard(tmp_path):
    """`--merge`'s denominator depends on this and nothing else."""
    sites = [_site(f"m{i}.py", i * 10) for i in range(7)]
    w = {P.site_key(s): float(i + 1) for i, s in enumerate(sites)}
    for n in (1, 2, 3, 6, 7, 9):
        shards = P.plan_shards(sites, n, tmp_path, w)
        assert len(shards) == n
        keys = [P.site_key(s) for sh in shards for s in sh]
        assert sorted(keys) == sorted(P.site_key(s) for s in sites), (n, keys)
        assert len(keys) == len(set(keys)), f"a site was duplicated at n={n}"


def test_the_heaviest_site_is_not_stacked_with_another(tmp_path):
    """An even split by COUNT is the mistake #1144 names: it leaves one host
    holding the long pole and the critical path does not move."""
    sites = [_site("heavy.py", 1), _site("a.py", 2), _site("b.py", 3),
             _site("c.py", 4)]
    w = {"heavy.py:1:on_conflict": 300.0, "a.py:2:on_conflict": 60.0,
         "b.py:3:on_conflict": 60.0, "c.py:4:on_conflict": 60.0}
    shards = P.plan_shards(sites, 2, tmp_path, w)
    heavy = [sh for sh in shards if any(s["file"] == "heavy.py" for s in sh)][0]
    assert len(heavy) == 1, (
        "the 300s site was packed with another; the critical path is now "
        f"300+ instead of 300: {[[P.site_key(s) for s in sh] for sh in shards]}")


def test_the_plan_is_deterministic_so_hosts_need_no_coordination(tmp_path):
    sites = [_site(f"m{i}.py", i) for i in range(6)]
    w = {P.site_key(s): float(i % 3 + 1) for i, s in enumerate(sites)}
    a = [[P.site_key(s) for s in sh] for sh in P.plan_shards(sites, 3, tmp_path, w)]
    b = [[P.site_key(s) for s in sh] for sh in P.plan_shards(sites, 3, tmp_path, w)]
    assert a == b


def test_measured_weight_beats_the_proxy_and_the_proxy_is_the_fallback(tmp_path):
    """Measured on the real tree, the proxy INVERTS the top two. A planner that
    silently used the proxy would put the wrong site on the critical path."""
    heavy_by_clock = _site("slow3files.py", 1)
    heavy_by_proxy = _site("fast34files.py", 2)
    measured = {P.site_key(heavy_by_clock): 284.0,
                P.site_key(heavy_by_proxy): 237.0}
    assert P.site_weight(heavy_by_clock, tmp_path, measured) == 284.0
    assert P.site_weight(heavy_by_proxy, tmp_path, measured) == 237.0
    # unmeasured -> proxy, never zero: a scheduler that treats an unknown item
    # as free is how one host ends up holding the long pole
    unknown = _site("new_site.py", 9)
    assert P.site_weight(unknown, tmp_path, {}) > 0


# --------------------------------------------------------------------------
# the denominator — a shard that dies must fail the run
# --------------------------------------------------------------------------
def _report(tmp_path: Path, name: str, inventory, sites) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"shard_inventory": inventory, "sites": sites}))
    return p


def _done(f, line, state="PINNED", param="on_conflict"):
    return {"file": f, "line": line, "param": param, "argued": True,
            "pin": {"state": state, "why": "" if state == "PINNED" else "survived"}}


def test_merge_states_its_denominator_and_passes_when_complete(tmp_path):
    inv = ["a.py:1:on_conflict", "b.py:2:on_conflict"]
    r1 = _report(tmp_path, "r1.json", inv, [_done("a.py", 1)])
    r2 = _report(tmp_path, "r2.json", inv, [_done("b.py", 2)])
    rc, lines = P.merge_shard_reports([r1, r2])
    assert rc == 0, lines
    assert "2 of 2 argued site(s) verified" in "\n".join(lines)


def test_a_missing_shard_REFUSES_and_never_silently_reduces_coverage(tmp_path):
    inv = ["a.py:1:on_conflict", "b.py:2:on_conflict"]
    r1 = _report(tmp_path, "r1.json", inv, [_done("a.py", 1)])
    rc, lines = P.merge_shard_reports([r1])
    assert rc == 2, lines
    txt = "\n".join(lines)
    assert "covered by NO shard" in txt, txt
    assert "b.py:2:on_conflict" in txt, "the uncovered site is not NAMED"


def test_an_unreadable_shard_report_REFUSES(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    rc, lines = P.merge_shard_reports([bad])
    assert rc == 2 and "unreadable" in "\n".join(lines)


def test_a_report_that_declares_no_inventory_REFUSES(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"sites": [_done("a.py", 1)]}))
    rc, lines = P.merge_shard_reports([p])
    assert rc == 2 and "declares no shard_inventory" in "\n".join(lines)


def test_shards_planned_against_DIFFERENT_TREES_are_refused(tmp_path):
    """Two hosts that disagree about how many sites exist are not two shards of
    one run — they are two runs, and merging them would invent a denominator."""
    r1 = _report(tmp_path, "r1.json", ["a.py:1:on_conflict"], [_done("a.py", 1)])
    r2 = _report(tmp_path, "r2.json",
                 ["a.py:1:on_conflict", "b.py:2:on_conflict"], [_done("b.py", 2)])
    rc, lines = P.merge_shard_reports([r1, r2])
    assert rc == 2 and "disagree about how many argued sites" in "\n".join(lines)


def test_a_duplicated_site_is_refused(tmp_path):
    inv = ["a.py:1:on_conflict"]
    r1 = _report(tmp_path, "r1.json", inv, [_done("a.py", 1)])
    r2 = _report(tmp_path, "r2.json", inv, [_done("a.py", 1)])
    rc, lines = P.merge_shard_reports([r1, r2])
    assert rc == 2 and "two shards" in "\n".join(lines)


def test_merge_REDDENS_on_an_unpinned_site(tmp_path):
    """PAIRED GUARD. A sharded gate that cannot fail is worse than the slow
    one — it would report PASS over a landing it never blocked."""
    inv = ["a.py:1:on_conflict", "b.py:2:on_conflict"]
    r1 = _report(tmp_path, "r1.json", inv, [_done("a.py", 1)])
    r2 = _report(tmp_path, "r2.json", inv, [_done("b.py", 2, "UNPINNED")])
    rc, lines = P.merge_shard_reports([r1, r2])
    assert rc == 1, lines
    assert "survive being flipped" in "\n".join(lines)


def test_merge_refuses_on_an_abstained_site(tmp_path):
    inv = ["a.py:1:on_conflict"]
    r1 = _report(tmp_path, "r1.json", inv, [_done("a.py", 1, "ABSTAIN")])
    rc, _ = P.merge_shard_reports([r1])
    assert rc == 2


# --------------------------------------------------------------------------
# the worktree rule — not a style note
# --------------------------------------------------------------------------
def test_shard_REFUSES_without_the_worktree_acknowledgement(tmp_path):
    """This gate rewrites tracked source and has a confirmed case of failing to
    restore it (#1089, #1029). Two shards in one tree flip the same file
    underneath each other."""
    p = subprocess.run(
        [sys.executable, str(GATE), str(PROGRAMS), "--verify-pins",
         "--shard", "1/6"], capture_output=True, text=True, timeout=_T * 4)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "--shard-worktree-ack" in p.stdout + p.stderr


def test_an_unknown_site_REFUSES_rather_than_verifying_nothing(tmp_path):
    """Answering "0/0, PASS" to a question about a site that does not exist is
    the vacuous pass this whole program is about."""
    p = subprocess.run(
        [sys.executable, str(GATE), str(PROGRAMS), "--verify-pins",
         "--site", "no_such_file.py:1"], capture_output=True, text=True,
        timeout=_T * 4)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "does not have" in p.stdout + p.stderr


def test_list_sites_emits_the_inventory_a_scheduler_needs():
    p = subprocess.run([sys.executable, str(GATE), str(PROGRAMS), "--list-sites"],
                       capture_output=True, text=True, timeout=_T * 6)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "argued site(s), total cost" in p.stdout
    assert "phase3_one_shot_runner.py:8414" in p.stdout, (
        "the inventory does not name sites by key, so a scheduler cannot "
        "address them")
