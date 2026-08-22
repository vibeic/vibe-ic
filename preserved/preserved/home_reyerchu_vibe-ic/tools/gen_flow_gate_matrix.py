#!/usr/bin/env python3
"""Regenerate every per-cell figure on ``flow-gate.html`` from the live suite.

WHY THIS EXISTS
===============
``tools/gen_flow_gate_header.py`` already recomputes the page's five header
figures, and it says in its own docstring what it deliberately does NOT
recompute::

    The eight per-dimension E/W/n distributions are NOT recomputed. […] They
    are carried forward untouched.

That was an honest refusal at the time, and it aged exactly the way an
un-recomputed number ages. Measured 2026-08-09 against ``origin/main`` at
``c3d3b4a56`` (plugin v1.10.11), the carried-forward half of the page had
drifted in eight separate places:

* the score tile published ``481 enforced``;
* the eight dimension rows published ``E`` totals summing to **478**, and ``W``
  totals summing to **14** — the page disagreed with its own headline, on the
  same screen, and had for three days;
* two rows were individually stale: ``d2 59/3/1`` (tree: ``60/2/1``) and
  ``d5 59/3/1`` (tree: ``61/1/1``);
* two of the 504 matrix glyphs were wrong — step 12's waiver moved from
  dimension 2 to dimension 5 and the grid still drew it on 2;
* the WAIVED section grouped step 12 under dimension 2, listed a waiver
  (``A8/d3``) that was removed on 2026-08-06, and omitted dimension 5 entirely;
* the prose asserted "dimension 8's 61 cells are measured with a stand-in gate"
  when ``substitution_census()`` says 45 are substituted and 16 are measured
  against the step's own mechanism;
* the prose asserted "all 504 cells have been reddened by a real mutation"
  while ``matrix_mutation_ledger.py --census``, printed two paragraphs above it,
  sums to 481;
* the footer published ``plugin v1.9.86`` while the header on the same page
  published ``v1.10.2`` and the tree was on ``v1.10.11``.

So the refusal is withdrawn, because the predicates it was refusing to guess at
no longer have to be guessed at: dimensions 1-8 each answer for their own cells
through ``test_matrix_63x8_coverage``, and this program only renders what they
say. It adds no opinion.

WHAT IT COMPUTES, and how
-------------------------
* Per-cell state — ``state_census()``: the CONFIGURATION axis. How a cell is
  set up. Never quoted alone; see below.
* Per-cell live outcome joined against that state — ``enforcement_census()``,
  the two-axis census that ``state_census()``'s own docstring names as the one
  to quote. A cell configured ENFORCED whose predicate is currently red is
  surfaced as ``ENFORCED-CONTRADICTED`` rather than absorbed (vibe-ic#888).
* The ENFORCED split — ``substitution_census()``: own mechanism / substituted
  stand-in / undeclared (vibe-ic#889).
* Waiver groups — ``matrix_63x8.waivers.WAIVERS``, grouped by the dimension the
  REGISTRY records, not by the dimension a page author remembered.
* Step ids, names and stage order — ``matrix_63x8.flowref``, read live from the
  flow yaml.

WHAT IT REFUSES
---------------
**A single "enforced" total.** This is the same refusal
``gen_matrix_63x8_census.py`` makes for the README, for the same reason and now
for a second reason on top of it. ``481`` was two erasures stacked:

  1. it added 16 own-mechanism cells to 45 substituted ones to 420 that never
     answered the question, and
  2. it counted 26 cells whose predicate was red at the moment of printing.

Both halves are published separately here and neither is summed with the other.
The score tiles carry four numbers that add to 504 and no fifth number that
adds two of them together.

**Writing when it scanned nothing.** A census over zero cells would render an
empty grid, four zeroes, and a green ``--check`` (vibe-ic#447).

**A timestamp inside the generated blocks.** A block that changes every run
cannot be diffed for drift, so ``--check`` would be meaningless the day it
mattered. The timestamp belongs to the header, which
``gen_flow_gate_header.py`` owns.

Run::

    export VIBEIC_FLOW_GATE_PAGE=/path/to/flow-gate.html
    python3 tools/gen_flow_gate_matrix.py           # rewrite the blocks
    python3 tools/gen_flow_gate_matrix.py --check   # exit 1 on drift
"""
from __future__ import annotations

import argparse
import collections
import html
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"

_TAG = "tools/gen_flow_gate_matrix.py"


def _markers(name: str) -> Tuple[str, str]:
    return (f"<!-- BEGIN GENERATED {name} — {_TAG} — DO NOT EDIT BY HAND -->",
            f"<!-- END GENERATED {name} -->")


BLOCKS = ("META", "SCORE", "DIMENSIONS", "MATRIX", "WAIVERS", "LIMITS",
          "MUTATION", "FOOTER")

#: The page is bilingual-ish in the site's house style: a Chinese label with the
#: English machine name beside it. These are the page's own words, kept so the
#: regenerated table reads identically to the one it replaces.
DIM_ZH = {
    1: ("接線", "Wiring", "gate 有沒有被三個管道之一呼叫到"),
    2: ("跑得動", "Runnable", "實跑拿真 rc；且它有沒有可能失敗"),
    3: ("產出", "Outputs", "required_outputs 真的存在且非空"),
    4: ("判準", "Criteria", "量的東西是否對得上它宣稱要量的"),
    5: ("依賴", "Deps", "blocks_on 宣告對不對"),
    6: ("Skip", "Skip", "SKIPPED-CONDITION 有沒有被濫用"),
    7: ("清單", "List", "required_outputs 清單本身完不完整"),
    8: ("抓漏", "Catcher", "output 沒出來時，哪個機制該抓沒抓到"),
}

STAGE_ZH = {
    "stage_phase1": "Phase 1",
    "stage1": "Stage 1 · RTL",
    "stage2": "Stage 2 · Synth/DFT",
    "stage3": "Stage 3 · PD",
    "stage4": "Stage 4 · Sign-off",
    "stage5_manufacturing": "Stage 5 · Mfg",
    "stage_analog": "Analog",
    "stage_mixed_signal": "Mixed-signal",
}

#: glyph + css class + tooltip, per two-axis label.
LABEL_UI = {
    "ENFORCED": ("E", "s-ENFORCED", "謂詞現算、現跑、通過"),
    "ENFORCED-CONTRADICTED": (
        "!", "s-CONTRADICTED",
        "宣告 ENFORCED，但現跑的謂詞是紅的 —— 這一格被算成覆蓋，卻沒有覆蓋任何東西"),
    "WAIVED": ("W", "s-WAIVED", "已知缺口 · xfail(strict)"),
    "NA": ("n", "s-NA", "斷言 NA 的前提現在仍然成立"),
}

SUB_ZH = {
    "OWN": "對該步驟自己的機制量的",
    "SUBSTITUTED": "對替身 stand-in 量的，不是這一格名字所指的機制",
    "UNDECLARED": "該維度沒有回答「量的是誰」這個問題",
}


def _load():
    """Import the coverage meta-test with the plugin's own import posture.

    Identical to ``gen_matrix_63x8_census.py._load``:
    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` matches the suite's documented
    invocation, without which a stray third-party pytest plugin breaks the
    subprocess collection both censuses depend on.
    """
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    for p in (PLUGIN_ROOT / "programs" / "tests", PLUGIN_ROOT / "programs"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    import test_matrix_63x8_coverage as CV  # noqa: E402
    from matrix_63x8 import flowref as F, waivers as W  # noqa: E402
    from matrix_63x8.cells import DIMENSIONS  # noqa: E402
    return CV, F, W, DIMENSIONS


class Census:
    """Everything the page publishes, recomputed. No opinion of its own."""

    def __init__(self):
        CV, F, W, DIMENSIONS = _load()
        self.F, self.W, self.DIMENSIONS = F, W, DIMENSIONS
        joined = CV.enforcement_census()
        subs = CV.substitution_census()

        self.steps = [
            {"id": F.normalize_id(s),
             "name": F.step_name(s),
             "stage": F.step_stage(s)}
            for s in F.step_ids()
        ]
        self.cells: Dict[Tuple[str, int], Dict] = {}
        for key, verdict in joined.items():
            self.cells[key] = {
                "label": verdict.label,
                "state": verdict.state,
                "outcomes": tuple(verdict.outcomes),
                "sub": subs.get(key),
            }

        self.counts = collections.Counter(c["label"] for c in self.cells.values())
        #: The substitution split, restricted to cells whose predicate is
        #: ACTUALLY green. Splitting the state axis instead would publish a
        #: bucket for 26 cells that are red — the erasure one level down.
        self.split = collections.Counter(
            c["sub"] for c in self.cells.values()
            if c["label"] == "ENFORCED" and c["sub"])
        self.total = len(self.cells)

    def per_dim(self, dim: int) -> collections.Counter:
        return collections.Counter(
            c["label"] for (s, d), c in self.cells.items() if d == dim)

    def per_dim_split(self, dim: int) -> collections.Counter:
        return collections.Counter(
            c["sub"] for (s, d), c in self.cells.items()
            if d == dim and c["label"] == "ENFORCED" and c["sub"])

    def waiver(self, step: str, dim: int):
        return self.W.waiver_for(step, dim)


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _clip(text: str, n: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


# ══════════════════════════════════════════════════════════════════════
# RENDERERS — one per marked block
# ══════════════════════════════════════════════════════════════════════
def render_score(c: Census) -> str:
    """Four tiles that add to 504, and deliberately no fifth that adds two.

    ``enforced`` and ``contradicted`` are shown side by side because the second
    is drawn ENTIRELY from what the first used to contain: every contradicted
    cell is configured ENFORCED. Presenting only the first is the 481.
    """
    n = c.counts
    own = c.split.get("OWN", 0)
    sub = c.split.get("SUBSTITUTED", 0)
    und = c.split.get("UNDECLARED", 0)
    return "\n".join([
        f'<div class="sc k-tot"><div class="n">{c.total}</div>'
        f'<div class="l">cells</div>'
        f'<div class="d">{len(c.steps)} 步 × {len(c.DIMENSIONS)} 維</div></div>',

        f'<div class="sc k-enf"><div class="n">{n["ENFORCED"]}</div>'
        f'<div class="l">enforced</div>'
        f'<div class="d">謂詞現跑且是綠的。<b>不是一種東西</b>：'
        f'{own} 格對該步驟自己的機制量、{sub} 格對替身量、'
        f'{und} 格所屬維度沒回答量的是誰</div></div>',

        f'<div class="sc k-contr"><div class="n">'
        f'{n.get("ENFORCED-CONTRADICTED", 0)}</div>'
        f'<div class="l">contradicted</div>'
        f'<div class="d">設定成 ENFORCED，<b>但現跑的謂詞是紅的</b>。'
        f'算成覆蓋，沒有覆蓋任何東西</div></div>',

        f'<div class="sc k-wai"><div class="n">{n["WAIVED"]}</div>'
        f'<div class="l">waived</div>'
        f'<div class="d">已知缺口 · strict xfail — 修好那天套件會變紅</div></div>',

        f'<div class="sc k-na"><div class="n">{n["NA"]}</div>'
        f'<div class="l">n/a</div>'
        f'<div class="d">斷言 NA 前提仍成立；前提消失就自動失效</div></div>',
    ])


def render_dimensions(c: Census) -> str:
    """The eight rows, with the ENFORCED column split rather than summed.

    ``<td class="dnum">N</td>`` is load-bearing markup, not decoration:
    ``gen_flow_gate_header.py`` counts those cells to derive the page's
    ``cells`` figure. Changing the tag would silently move 504.
    """
    out = ['<thead><tr><th>#</th><th>維度</th><th>問的問題</th>'
           '<th style="width:150px">分佈</th>'
           '<th style="width:96px">E / <b>!</b> / W / n</th>'
           '<th style="width:118px">E 是對誰量的<br>own/subst/undecl</th>'
           '</tr></thead><tbody>']
    for dim in c.DIMENSIONS:
        zh, en, ask = DIM_ZH[dim]
        n = c.per_dim(dim)
        sp = c.per_dim_split(dim)
        e = n.get("ENFORCED", 0)
        x = n.get("ENFORCED-CONTRADICTED", 0)
        w = n.get("WAIVED", 0)
        na = n.get("NA", 0)
        tot = e + x + w + na
        pct = (lambda v: f"{100.0 * v / tot:.1f}" if tot else "0.0")
        out.append("<tr>")
        out.append(f'<td class="dnum">{dim}</td>')
        out.append(f'<td class="dname">{_esc(zh)} <span>{_esc(en)}</span></td>')
        out.append(f'<td class="dask">{_esc(ask)}</td>')
        out.append(
            f'<td><div class="bar">'
            f'<i class="b-e" style="width:{pct(e)}%"></i>'
            f'<i class="b-c" style="width:{pct(x)}%"></i>'
            f'<i class="b-w" style="width:{pct(w)}%"></i>'
            f'<i class="b-n" style="width:{pct(na)}%"></i></div></td>')
        out.append(f'<td class="dc">{e} · <b class="cx">{x}</b> · '
                   f'<b>{w}</b> · {na}</td>')
        out.append(f'<td class="dc">{sp.get("OWN", 0)} / '
                   f'{sp.get("SUBSTITUTED", 0)} / {sp.get("UNDECLARED", 0)}</td>')
        out.append("</tr>")
    out.append("</tbody>")
    return "\n".join(out)


def render_matrix(c: Census) -> str:
    """63 rows x 8 glyphs, stage-banded in the flow's own order."""
    out = ['<thead><tr>',
           '<th class="sid">Step</th><th class="snm">Name</th>']
    for dim in c.DIMENSIONS:
        zh, en, ask = DIM_ZH[dim]
        out.append(f'<th title="{_esc(zh)} — {_esc(ask)}">{dim}·{_esc(en)}</th>')
    out.append('</tr></thead><tbody>')

    stage = None
    for step in c.steps:
        if step["stage"] != stage:
            stage = step["stage"]
            label = STAGE_ZH.get(stage, stage)
            out.append(f'<tr class="stg"><td colspan="10">{_esc(label)}</td></tr>')
        sid, name = step["id"], step["name"]
        out.append("<tr>")
        out.append(f'<td class="sid">{_esc(sid)}</td>')
        out.append(f'<td class="snm" title="{_esc(name)}">{_esc(name)}</td>')
        for dim in c.DIMENSIONS:
            cell = c.cells[(sid, dim)]
            glyph, css, tip = LABEL_UI[cell["label"]]
            zh = DIM_ZH[dim][0]
            detail = tip
            if cell["label"] == "ENFORCED" and cell["sub"]:
                detail = f'{tip} — {SUB_ZH[cell["sub"]]}'
            elif cell["label"] == "ENFORCED-CONTRADICTED":
                seen = ", ".join(cell["outcomes"]) or "<never observed>"
                detail = f"{tip}（現跑結果：{seen}）"
            elif cell["label"] == "WAIVED":
                wv = c.waiver(sid, dim)
                if wv is not None:
                    detail = _clip(wv.reason, 190)
            out.append(f'<td><span class="st {css}" '
                       f'title="{_esc(sid)} · {_esc(zh)} — {_esc(detail)}">'
                       f'{glyph}</span></td>')
        out.append("</tr>")
    out.append("</tbody>")
    return "\n".join(out)


def render_waivers(c: Census) -> str:
    """Grouped by the dimension the REGISTRY records.

    The page had step 12 filed under dimension 2 because that is where it was
    on 2026-08-06. ``waiver_for`` is the only thing that knows where it is now.
    """
    groups: Dict[int, List] = collections.defaultdict(list)
    for wv in c.W.WAIVERS:
        groups[wv.dim].append(wv)
    total = sum(len(v) for v in groups.values())

    out = [f'<h2>已知缺口 <span class="cnt">{total} 個 WAIVED 格</span></h2>',
           '<p class="h2sub">每一個都是承認「這一格今天還測不到」，帶具體理由與'
           '可查證的證據，而且是 <code>xfail(strict=True)</code> —— '
           '<b>修好的那天套件會變紅，逼人把 waiver 拿掉。</b>'
           '一個沒有到期壓力的例外，最後都會變成永久的沉默。'
           '<br>這一節由 <code>matrix_63x8/waivers.py</code> 現算：'
           '哪一格被 waive、掛在哪一個維度，以登記簿為準。</p>']

    for dim in sorted(groups):
        zh, en, _ = DIM_ZH[dim]
        items = sorted(groups[dim], key=lambda w: str(w.step_id))
        out.append(f'<h3 style="font-size:14px;margin:22px 0 9px;'
                   f'font-weight:640"><span class="dnum" '
                   f'style="width:auto">{dim}</span> {_esc(zh)} '
                   f'<span style="color:var(--ink-3);font-weight:400;'
                   f'font-family:var(--mono);font-size:11.5px"> · '
                   f'{len(items)} 個</span></h3>')
        for wv in items:
            sid = c.F.normalize_id(wv.step_id)
            try:
                name = c.F.step_name(sid)
            except Exception:                       # step deleted from the flow
                name = "(step not in the current flow)"
            out.append(
                f'<div class="gap"><div class="gap-h">'
                f'<span class="pill">step {_esc(sid)}</span>'
                f'<span class="pill q">dim {dim} · {_esc(zh)}</span>'
                f'<span class="gap-t">{_esc(_clip(name, 72))}</span></div>')
            out.append(f'<p class="gap-r">{_esc(_clip(wv.reason, 240))} '
                       f'<i>（完整理由見 '
                       f'programs/tests/matrix_63x8/waivers.py）</i></p>')
            out.append(f'<p class="gap-e">{_esc(_clip(wv.evidence, 240))}</p>')
            out.append('</div>')
    return "\n".join(out)


def render_limits(c: Census) -> str:
    """The two sentences in the limits note that quote a live figure.

    Both were wrong on 2026-08-09 and wrong in the flattering direction:
    "dimension 8's 61 cells are measured with a stand-in" overstated the
    substitution (45 of them are; 16 are measured against the step's own
    mechanism), and "11 real repo defects spread over 8 steps" undercounted the
    spread (10 steps). A limits section is the one place on a page where an
    error is worth the most, because it is read as the author being candid.
    """
    n = c.counts
    own = c.split.get("OWN", 0)
    sub = c.split.get("SUBSTITUTED", 0)
    d8 = c.per_dim_split(8)
    # Natural order, not lexicographic: the flow's own step sequence. Sorting
    # "6" after "39" is how a list of ids stops looking like a list of steps.
    order = {sid: i for i, sid in enumerate(s["id"] for s in c.steps)}
    steps = sorted({c.F.normalize_id(w.step_id) for w in c.W.WAIVERS},
                   key=lambda s: order.get(s, len(order)))
    dupes = collections.Counter(
        c.F.normalize_id(w.step_id) for w in c.W.WAIVERS)
    multi = sorted(s for s, k in dupes.items() if k > 1)
    return "\n".join([
        f'<p><b>維度 8 的 {d8.get("SUBSTITUTED", 0)} 格是用替身 gate 量的，'
        f'{d8.get("OWN", 0)} 格才是對該步驟自己的機制量的。</b> '
        f'替身那些證明了產出的帳算得對，但沒證明那個 MISSING 降級在該步驟的'
        f'<b>正式流程</b>裡真的到得了。全表 {n["ENFORCED"]} 個 enforced 裡，'
        f'只有這 {own} 格是對自己的機制量的；{sub} 格是替身；'
        f'其餘 {c.split.get("UNDECLARED", 0)} 格所屬的維度根本沒回答'
        f'「你量的是誰」。<b>這三個數字不可以相加。</b></p>',

        f'<p><b>還有 {n["WAIVED"]} 格真實的 repo 缺陷是被 waive 而不是被修掉的</b>'
        f'（分佈在 {len(steps)} 個步驟上：{_esc("、".join(steps))}；'
        f'{_esc("、".join(multi)) if multi else "沒有一個步驟"} 在兩個維度上各佔一格）。'
        f'測試覆蓋的 commit 不該夾帶修復。每個都是 strict —— 修好的那天套件會變紅。'
        f'而且<b>被 waive 的格子仍然會跑</b>：套件裡那 {n["WAIVED"]} 個 '
        f'<code>xfail</code> 就是這 {n["WAIVED"]} 格，waiver 的理由是它的預期失敗'
        f'訊息，所以「被 waive」不等於「沒被執行」。</p>',

        f'<p><b>而 {n.get("ENFORCED-CONTRADICTED", 0)} 格連 waive 都沒有 —— '
        f'它們被登記成 ENFORCED，現跑的謂詞卻是紅的。</b>'
        f'這不是這張表的限制，是這張表現在能講出來的東西：'
        f'<code>test_no_cell_is_counted_enforced_while_its_predicate_is_red</code> '
        f'會因此變紅，而不是讓那 {n.get("ENFORCED-CONTRADICTED", 0)} 格'
        f'繼續被算進覆蓋率。上面的矩陣用 <span class="st s-CONTRADICTED">!</span> '
        f'逐格標出它們。</p>',
    ])


def render_mutation(c: Census) -> str:
    """The mutation ledger's own position, asked of the ledger.

    The page said "all 504 cells have been reddened by a real mutation" in one
    paragraph, two paragraphs after correcting the identical error at 481 —
    while `matrix_mutation_ledger.py --census`, quoted verbatim in between,
    sums to 481. An error a page has just finished explaining is the one it is
    least likely to re-read.
    """
    import matrix_mutation_ledger as ML  # noqa: E402 — sys.path set by _load()
    rep = ML.census()
    per = rep["per_dimension"]
    covered = sum(p["covered"] for p in per.values())
    grid = rep["grid"]
    pairs = sum(len(m.applies_to) for m in ML.MUTATIONS)
    order = sorted(per.items(), key=lambda kv: -kv[1]["covered"])
    line = " · ".join(f"{d} {p['covered']}/{p['considered']}" for d, p in order)
    return "\n".join([
        f'<p><b>{covered} 格 / {grid} 格</b>帶著一條具名 mutation，'
        f'而那條 mutation 是<b>真的被執行過</b>並且讓那一格變紅的。'
        f'剩下的 {grid - covered} 格沒有 —— 「有一條會動的線」不代表'
        f'「那條線量的是對的東西」，而<b>沒有線</b>就連那個都談不上。</p>',
        f'<p>逐維計數才是覆蓋率（每次跑都印）：<code>{_esc(line)}</code></p>',
        f'<p>LOCK 1 每次跑檢查 <b>{pairs}</b> 組 (entry, step)：每一條編輯配方'
        f'都必須在<b>當前的</b>樹上解析得開。LOCK 2 在隔離副本上真的執行那個編輯，'
        f'把那一格跑兩次（未 mutate 必須過、mutate 後必須紅）；'
        f'replay 模式 <code>{_esc(rep["replay_mode"])}</code>，'
        f'每次跑重放 {rep["replay_pairs"]} 組。</p>',
        f'<p class="h2sub" style="margin:9px 0 0">重現：'
        f'<code>python3 programs/matrix_mutation_ledger.py --census '
        f'--resolve</code></p>',
    ])


def render_footer(c: Census) -> str:
    """The footer restated every figure and got the version wrong by nine
    releases. It now carries the same four numbers as the score tiles and the
    same refusal to add them up."""
    import json
    version = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
        .read_text(encoding="utf-8"))["version"]
    n = c.counts
    return (
        f'plugin v{version} · flow {len(c.steps)} steps · {c.total} cells<br>'
        f'{n["ENFORCED"]} enforced '
        f'({c.split.get("OWN", 0)} own / {c.split.get("SUBSTITUTED", 0)} '
        f'substituted / {c.split.get("UNDECLARED", 0)} undeclared) · '
        f'{n.get("ENFORCED-CONTRADICTED", 0)} contradicted · '
        f'{n["WAIVED"]} waived · {n["NA"]} n/a<br>'
        f'enforced / contradicted / waived / n-a 這四個數字加起來是 {c.total}；'
        f'括號裡的 own / 替身 / 未宣告是 enforced 的<b>內部拆分</b>，'
        f'不另外相加。<b>沒有一個「enforcing 總數」可以引用</b> —— '
        f'把 own、替身、未宣告三種加在一起，就是 vibe-ic#889 落地要停掉的那個抹除；'
        f'把 contradicted 併進 enforced，就是 vibe-ic#888 落地要停掉的那一個。<br>'
        f'由 <code>{_TAG}</code> 對當前原始碼現算（<code>--check</code> 會在漂移時 exit 1）')


def render_meta(c: Census) -> str:
    """The three description tags, which are what a link preview publishes.

    Before this block existed they disagreed with each other: ``og:`` and
    ``twitter:`` both said "504 格，481 enforced / 11 waived / 12 n/a" while
    ``name="description"`` had already been rewritten to say the distributions
    were NOT recomputed. A page can be corrected in the body and still ship the
    old number to every chat client that unfurls it, because nothing regenerates
    the head.
    """
    n = c.counts
    body = (f"{c.total} 格：{n['ENFORCED']} enforced"
            f"（{c.split.get('OWN', 0)} own / "
            f"{c.split.get('SUBSTITUTED', 0)} 替身 / "
            f"{c.split.get('UNDECLARED', 0)} 未宣告）、"
            f"{n.get('ENFORCED-CONTRADICTED', 0)} contradicted、"
            f"{n['WAIVED']} waived、{n['NA']} n/a。"
            f"沒有一個「enforcing 總數」可以引用。")
    long = (f"Vibe-IC 流程 {len(c.steps)} 步驟 × {len(c.DIMENSIONS)} 判斷維度。"
            f"{body}")
    return "\n".join([
        f'<meta name="description" content="{_esc(long)}">',
        f'<meta property="og:description" content="{_esc(body)}">',
        f'<meta name="twitter:description" content="{_esc(body)}">',
    ])


RENDERERS = {
    "META": render_meta,
    "SCORE": render_score,
    "DIMENSIONS": render_dimensions,
    "MATRIX": render_matrix,
    "WAIVERS": render_waivers,
    "LIMITS": render_limits,
    "MUTATION": render_mutation,
    "FOOTER": render_footer,
}


def splice(text: str, name: str, body: str) -> str:
    begin, end = _markers(name)
    start, stop = text.find(begin), text.find(end)
    if start < 0 or stop < 0 or stop < start:
        raise SystemExit(
            f"generated-{name.lower()} markers not found in the page (looked "
            f"for\n  {begin}\n  {end}\n). A hand edit that removed them would "
            f"make this generator silently write nothing, so it refuses "
            f"instead. Seed the markers around the block it owns.")
    return text[:start] + begin + "\n" + body + "\n" + end + text[stop + len(end):]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _env = os.environ.get("VIBEIC_FLOW_GATE_PAGE")
    ap.add_argument("--page", type=Path,
                    default=Path(_env) if _env else None, required=not _env,
                    help="flow-gate.html to rewrite "
                         "(or set VIBEIC_FLOW_GATE_PAGE)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any generated block would change")
    args = ap.parse_args(argv)

    c = Census()

    # A PASS must say how much it examined (vibe-ic#447). A grid rendered over
    # zero cells matches an empty page trivially and every count reads 0
    # without a single predicate having run.
    if not c.total or not c.steps:
        sys.stderr.write(
            f"NOTHING_SCANNED: the live census produced {len(c.steps)} step(s) "
            f"over {c.total} cell(s) — this is NOT a pass. Check that the "
            f"eight dimension modules import and that pytest can collect "
            f"them.\n")
        return 2
    if c.total != len(c.steps) * len(c.DIMENSIONS):
        sys.stderr.write(
            f"INCOMPLETE: {c.total} cells for {len(c.steps)} steps x "
            f"{len(c.DIMENSIONS)} dimensions. Rendering a partial grid as a "
            f"full one is the defect this page is about.\n")
        return 2

    text = args.page.read_text(encoding="utf-8")
    out = text
    for name in BLOCKS:
        out = splice(out, name, RENDERERS[name](c))

    summary = (f"{c.total} cells = {len(c.steps)} steps x "
               f"{len(c.DIMENSIONS)} dims; {dict(c.counts)}; "
               f"ENFORCED split {dict(c.split)}")
    if args.check:
        if out != text:
            sys.stderr.write(
                f"{args.page}: generated blocks are stale; re-run "
                f"`python3 {_TAG}`\n  live: {summary}\n")
            return 1
        print(f"[PASS] flow-gate matrix fresh: {summary}")
        return 0

    if out == text:
        print(f"no change ({summary})")
        return 0
    args.page.write_text(out, encoding="utf-8")
    print(f"wrote {args.page}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
