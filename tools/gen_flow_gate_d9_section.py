#!/usr/bin/env python3
"""gen_flow_gate_d9_section.py — render the D9 block of the flow-gate page.

WHY THIS IS A GENERATOR AND NOT HAND-WRITTEN HTML
=================================================
The page it writes into carries this rule in its own masthead: every published
digit is recomputed against the current source, and a hand-typed total is the
defect the whole campaign exists to remove.  A D9 section typed by hand would
reproduce that defect on the very page that documents it.

So every number below comes from ``d9_reality.json`` — the output of
``tools/d9_flow_gate_reality.py``, which decides each cell by RUNNING the
shipped gates under a two-arm artefact mutation.  This program adds no opinion;
it renders, and ``--check`` fails on drift exactly as the page's sibling
generators do.

WHAT IT REFUSES
---------------
It refuses to publish D9 as a shipped dimension.  MEASURED-TODAY and PLANNED are
rendered in visibly different registers and never summed.

THAT REFUSAL WAS RIGHT IN 2026-08 AND IS WRONG NOW, WHICH IS WHY THIS PROGRAM
NO LONGER RENDERS
-----------------------------------------------------------------------------
The sentence this file used to carry here -- "it is not one: nothing in
``flow/phase1_phase2_phase3.yaml`` asks the ninth question" -- was prose, never
a measurement, and the file it names now contradicts it: four ``# D9`` labelled
clauses, one of them the BLOCKING ``program_exit_zero:
"step_internal_fail_bubble_up_check ."`` in step 36.

The question also changed identity underneath this program.  #1009 measured "is
the output CORRECT".  The D9 that shipped is ``verdict_consumed`` -- does a
step's own FAIL survive to the process exit code -- and the published page says
so in its own words: "The ninth question is shipped -- and it is not 'is the
output correct?'".  So this block is not a stale version of that section; it is
a denial of it.

Two further facts make this unrepairable by refreshing the data, and both are
measured:

  * the report describes a 63-step flow (the flow has 68), and the block
    additionally hardcodes ``504`` = 63 x 8 in its own prose, which no refresh
    of the report would correct; and
  * the report cannot BE refreshed here.  ``benchmark-data/`` was exported to
    its own repository at v1.10.56 (e23d0be5e, 2026-08-17), so
    ``d9_flow_gate_reality.py`` exits rc 2 "benchmark-data/ not found" and has
    no corpus-path option.  The report landed on 2026-08-18, INTO a tree where
    the corpus was already gone: it was un-regenerable the day it shipped.

``premise_refusal()`` below decides this against the tree rather than against
this paragraph, so a future flow that stops asking the ninth question restores
the program without anyone editing prose.  Until then every path -- ``--emit``,
``--install``, ``--write``, ``--check`` -- exits 2 and writes nothing.

It also refuses to render the plan's target as though it were measured.  The
only ceiling figure it prints is the one this repo can DERIVE — the count of
dark cells whose artefact ``benchmark-data/PUBLISHING.md`` excludes from the
corpus by construction.

Usage:
    python3 tools/gen_flow_gate_d9_section.py --reality <d9_reality.json> \
        --page <flow-gate.html> [--write | --check] [--emit <fragment.html>]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

BEGIN = "<!-- BEGIN GENERATED D9 — tools/gen_flow_gate_d9_section.py — DO NOT EDIT BY HAND -->"
END = "<!-- END GENERATED D9 -->"

#: The sentence the whole section exists to carry.  It is a CONSTANT, not a
#: template: nothing in this program may soften, shorten or reflow it, and a
#: reviewer can diff this literal against the brief in one look.
CERTIFIES = (
    "This gate certifies CONSISTENCY AND ATTRIBUTION, never CORRECTNESS."
)

MAY_BELIEVE = (
    "every declared artefact exists, agrees with itself, agrees with every "
    "other artefact of the same run about the same physical quantity, and sits "
    "inside what THIS PDK&#39;s own tables permit — and no verdict was issued "
    "over a zero denominator, an absent file, or a glob that found another "
    "run&#39;s evidence."
)
MAY_NOT_BELIEVE = (
    "that the design is functionally correct, that it closes timing, that a "
    "foundry deck would sign it off, or that silicon works."
)

#: cause -> (label zh, one-line meaning zh, severity class)
CAUSES = {
    "DENOMINATOR": (
        "分母為零",
        "這個步驟宣告的產出，在 {runs} 個已發佈的 run 裡<b>一個都沒有</b>。"
        "沒有東西可量，任何尺都量不到。",
        "c-den"),
    "RULER-BLIND": (
        "尺是瞎的",
        "gate <b>跑了、綠了</b> —— 而且把它宣稱在judge的那個產出<b>整個刪掉之後，"
        "它還是一樣綠</b>。這一格量的不是這個步驟，是空氣。",
        "c-blind"),
    "NO-BLOCKING-RULER": (
        "沒有會擋的尺",
        "整個 gate 沒有任何一條 blocking 條款會執行程式：只有 "
        "<code>files_exist</code> 之類的路徑解析。檔案在，就過。",
        "c-noruler"),
    "ALREADY-RED": (
        "本來就是紅的",
        "gate 在已發佈的 run 上<b>本來就是 FINDING</b>，刪掉產出前後都一樣紅。"
        "它可能有讀，但無法證明它讀的是這個步驟的產出。",
        "c-red"),
    "RULER-NEVER-RAN": (
        "尺沒跑起來",
        "在分母集合裡的每一個 run 上，gate 都是 NO-INPUT 或 ERROR —— "
        "它從來沒有真的讀到東西。",
        "c-never"),
}


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def render(rep: Dict) -> str:
    rows: List[Dict] = rep["rows"]
    runs = rep["corpus"]["runs"]
    moves = rep["moves_today"]
    dark = rep["dark"]
    steps = rep["steps"]
    bands = rep["denominator_bands"]
    causes = rep["causes"]
    excl = rep.get("publishing_excluded_dark", {})

    out: List[str] = [BEGIN]

    # ── masthead ────────────────────────────────────────────────────────
    out.append('<div class="d9-top">')
    out.append('<div class="eyebrow">Dimension 9 · 今天量到的，不是出貨的</div>')
    out.append("<h2>第 9 個維度：<span class='d9-q'>輸出是不是對的</span>"
               f"<span class='cnt'>{moves} / {steps} 格今天真的會動</span></h2>")
    out.append(
        '<p class="h2sub"><b>D9 不是一個已經出貨的維度。</b>'
        '<code>flow/phase1_phase2_phase3.yaml</code> 裡沒有任何一條 gate 在問'
        '「輸出對不對」；上面那 504 格問的是前八個問題。'
        '這一節是<b>把第九個問題拿去量今天的樹</b>得到的結果，'
        f'不是一個新的維度宣告。每一格都是<b>真的把該步驟的 blocking gate 跑起來</b>'
        f'（two-arm artefact mutation，{rep["two_arm_cells_planned"]} 個 (step,run) '
        'cell），不是靜態掃描。</p>')
    out.append("</div>")

    # ── the sentence ────────────────────────────────────────────────────
    out.append('<div class="d9-oath">')
    out.append('<div class="d9-oath-h">全綠的時候，讀者可以相信什麼 · '
               'What a reader may believe when every cell is green</div>')
    out.append(f'<p class="d9-may"><b>可以相信 MAY believe：</b>{MAY_BELIEVE}</p>')
    out.append(f'<p class="d9-mayn"><b>不可以相信 MAY NOT believe：</b>'
               f'{MAY_NOT_BELIEVE}</p>')
    out.append(f'<p class="d9-cert">{esc(CERTIFIES)}</p>')
    out.append('<p class="d9-cert-zh">這個 gate 證明的是<b>一致性與歸屬</b>'
               '（consistency and attribution），<b>永遠不是正確性</b>（correctness）。</p>')
    out.append("</div>")

    # ── scoreboard ──────────────────────────────────────────────────────
    out.append('<div class="score d9-score">')
    out.append(f'<div class="sc k-tot"><div class="n">{steps}</div>'
               f'<div class="l">d9 cells</div><div class="d">63 步 × 第 9 個問題</div></div>')
    out.append(f'<div class="sc k-enf"><div class="n">{moves}</div>'
               f'<div class="l">moves today</div><div class="d">刪掉該步驟自己宣告的產出後，'
               f'blocking gate 的判定<b>真的改變</b>了</div></div>')
    out.append(f'<div class="sc k-contr"><div class="n">{dark}</div>'
               f'<div class="l">dark</div><div class="d">今天量不到。'
               f'<b>不是因為沒有 oracle</b> —— 五個實測原因在下表</div></div>')
    out.append(f'<div class="sc k-na"><div class="n">{runs}</div>'
               f'<div class="l">published runs</div><div class="d">'
               f'<code>git ls-files benchmark-data</code> 裡帶 '
               f'<code>phase1/generated_docs/</code> 的目錄</div></div>')
    out.append("</div>")

    # ── the denominator ─────────────────────────────────────────────────
    out.append("<section>")
    out.append(f'<h3 class="d9-h3">為什麼 {dark} 格不是「沒有 oracle」 · '
               '原因一：<b>分母</b></h3>')
    out.append(
        f'<p class="h2sub">每個步驟，{runs} 個已發佈 run 裡有幾個'
        '<b>完整帶著它宣告的產出集合</b>？'
        'ANY_OF 與 glob 都照 <code>flowref</code> 的定義解析。</p>')
    out.append('<div class="scroll"><table class="run">')
    out.append("<thead><tr><th>帶滿該步驟產出的 run 數</th><th>步驟數</th>"
               "<th>這代表什麼</th></tr></thead><tbody>")
    out.append(f'<tr><td class="n"><b>0</b></td><td class="n">{bands["zero"]}</td>'
               f'<td>這些格子<b>連跑都跑不起來</b>。沒有任何已發佈的 run 帶著它的產出。</td></tr>')
    out.append(f'<tr><td class="n">1 – 10</td><td class="n">{bands["one_to_ten"]}</td>'
               f'<td>中位數是 <b>{bands["median"]}</b> 個 run。'
               f'一格綠燈的背後常常只有兩三個 run。</td></tr>')
    out.append(f'<tr><td class="n">≥ 11</td><td class="n">{bands["eleven_plus"]}</td>'
               f'<td>其中<b>只有 {bands["all_runs"]} 個步驟</b>拿得到全部 '
               f'{bands["max"]} 個 run。</td></tr>')
    out.append("</tbody></table></div>")
    out.append(
        '<div class="blk"><h3>分母為什麼這麼小 —— 這是<b>發佈政策寫死的</b>，不是疏忽</h3>'
        '<p><code>benchmark-data/PUBLISHING.md</code> 的「Excluded by construction」'
        '一節明講：<code>*.gds</code>、<code>*.def</code>、<code>*.spef</code>、'
        '<code>*.oas</code> <b>從來不會被 commit</b>。'
        f'實測整個 corpus：<b>{excl.get("def", "?")} 個 .def、'
        f'{excl.get("gds", "?")} 個 .gds、{excl.get("spef", "?")} 個 .spef、'
        f'{excl.get("oas", "?")} 個 .oas</b>。'
        '所以凡是產出是版圖幾何的步驟，分母天生就是 0 —— '
        '這是<b>今天這張表的天花板本身</b>，不是可以靠寫程式補起來的洞。</p></div>')
    out.append("</section>")

    # ── the five causes census ──────────────────────────────────────────
    out.append("<section>")
    out.append(f'<h3 class="d9-h3">{dark} 格暗的，各自是<b>哪一種</b>暗</h3>')
    out.append('<p class="h2sub">原因由 two-arm 的<b>實際結果</b>決定，不是推測。'
               '優先序：分母為零 → 沒有 blocking 尺 → 尺是瞎的（觀察到的行為，'
               '壓過所有解釋）→ PDK 沒讀到 → skill 不存在 → 本來就紅 → 尺沒跑起來。</p>')
    out.append('<div class="d9-causes">')
    for cause, n in sorted(causes.items(), key=lambda kv: -kv[1]):
        label, meaning, cls = CAUSES.get(cause, (cause, "", "c-other"))
        meaning = meaning.format(runs=runs)
        out.append(f'<div class="d9-cause {cls}">'
                   f'<div class="d9-cause-n">{n}</div>'
                   f'<div class="d9-cause-b"><div class="d9-cause-t">'
                   f'{esc(label)} <span class="d9-cause-k">{esc(cause)}</span></div>'
                   f'<div class="d9-cause-m">{meaning}</div></div></div>')
    out.append("</div>")
    out.append("</section>")

    # ── per-step table: the dark cells AS DARK ──────────────────────────
    out.append("<section>")
    out.append('<h3 class="d9-h3">63 個步驟，逐格 · '
               '<b>暗的就顯示成暗的</b></h3>')
    out.append('<p class="h2sub">'
               '<span class="d9-k d9-k-mv">MOVES</span> = 把該步驟宣告的產出從一份'
               '隔離的副本裡刪掉之後，某一條 blocking gate 的判定<b>改變了</b>'
               '（這是這個 repo 對「一格是真的」唯一承認的證據：'
               '<code>matrix_mutation_ledger</code>）。'
               '<span class="d9-k d9-k-dk">DARK</span> = 沒有改變。'
               'den = 帶滿該步驟產出的 run 數；moved = 在幾個 run 上判定真的改變。</p>')
    out.append('<div class="scroll"><table class="mx d9-mx">')
    out.append('<thead><tr><th class="sid">step</th><th class="snm">名稱</th>'
               '<th style="width:58px">den</th><th style="width:70px">moved</th>'
               '<th style="width:96px">D9</th>'
               '<th class="snm" style="width:210px">為什麼暗 / 誰讓它會動</th></tr></thead><tbody>')
    stage = None
    for r in rows:
        if r["stage"] != stage:
            stage = r["stage"]
            out.append(f'<tr class="stg"><td colspan="6">{esc(stage)}</td></tr>')
        if r["moves_today"]:
            chip = '<span class="d9-k d9-k-mv">MOVES</span>'
            why = ", ".join(f'<code>{esc(m["program"])}</code>'
                            for m in r["movers"][:2])
        else:
            chip = '<span class="d9-k d9-k-dk">DARK</span>'
            label = CAUSES.get(r["cause"], (r["cause"],))[0]
            why = (f'<span class="d9-why">{esc(label)}</span> '
                   f'<span class="d9-whyk">{esc(r["cause"])}</span>')
        cls = "" if r["moves_today"] else ' class="d9-dark"'
        out.append(
            f'<tr{cls}><td class="sid">{esc(r["step"])}</td>'
            f'<td class="snm" title="{esc(r["name"])}">{esc(r["name"])}</td>'
            f'<td>{r["denominator"]}</td>'
            f'<td>{r["runs_moved"]}</td>'
            f'<td>{chip}</td><td class="snm">{why}</td></tr>')
    out.append("</tbody></table></div>")
    out.append("</section>")

    # ── evidenced findings: the causes no program decides per cell ──────
    ev = rep["evidenced_findings"]
    fb = ev["floorplan_budget"]
    inv = ev["single_emitter_inverted"]
    sk = rep["skills"]
    pg = rep["programs"]

    out.append("<section>")
    out.append('<h3 class="d9-h3">另外三個原因 —— '
               '<b>有證據，但沒有任何程式能逐格判定</b></h3>')
    out.append('<p class="h2sub">把這三個算成「每一格的原因」就是在編造一個'
               '這支程式做不到的歸因。它們是<b>具名的、可查證的發現</b>，'
               '每一條都附上重新量過的普查數字。</p>')

    out.append('<div class="gap"><div class="gap-h">'
               '<span class="pill">原因四 · UNREAD PDK</span>'
               '<span class="gap-t">物理上界那一整類，今天 0% 可執行</span></div>')
    out.append(
        f'<p class="gap-r">tech LEF（<code>*.tlef</code>）在 <b>'
        f'{ev["pdk"]["tech_lef_runs"]} / {runs}</b> 個已發佈 run 裡出現。'
        f'整個 corpus 只有 <b>{excl.get("lef", "?")} 個 .lef、'
        f'{excl.get("tlef", "?")} 個 .tlef</b>。'
        '沒有 PDK 自己的表，就沒有 Jmax、沒有密度窗、沒有製造格點 —— '
        '「這個數字有沒有超出這個 PDK 允許的範圍」這個問句<b>連問都問不出來</b>。</p>')
    out.append(
        f'<p class="gap-e">實跑 <code>{esc(ev["pdk"]["em_checker"])}</code>：'
        'rc=<b>3</b>、<code>verdict=SKIPPED</code>、'
        '<code>skip_reason=jmax_reference_absent</code>，訊息是'
        '「no Jmax reference (no --jmax or --tech-lef supplied); §4.05: cannot '
        'fabricate PASS and will not use the decap-count proxy」。'
        '<b>它誠實地拒絕，不是假裝通過</b> —— 這一點比原始 brief 描述的更好，'
        '也是這個 repo 的房規（零分母必須 refuse，不能 pass）。</p></div>')

    if inv:
        out.append('<div class="gap"><div class="gap-h">'
                   '<span class="pill">原因二 · SINGLE-EMITTER</span>'
                   '<span class="gap-t">「總數 == 各部分相加」，'
                   '兩個運算元由同一支程式在同一輪寫出</span></div>')
        out.append(
            '<p class="gap-r">最尖銳的一個是<b>反向的</b>：被檢查的那個數，'
            '本身就是用檢查它所用的比例<b>算出來的</b>。'
            '拿 coverage 去驗 <code>faults_covered</code>，'
            '等於讓它重算一次自己的輸入 —— 這個等式<b>永遠成立</b>，'
            '它不可能發現任何事情。</p>')
        out.append(
            f'<p class="gap-e"><code>{esc(inv["file"])}:{inv["line"]}</code> — '
            f'<code>{esc(inv["source"])}</code></p>')
        out.append('<p class="gap-e"><b>本頁只發佈這一條經過逐行查證的實例。</b>'
                   '委託本頁的 brief 宣稱「7 條裡 7 條」都是單一產出者，'
                   '本次<b>沒有重新推導那 7 條</b>，因此不引用那個數字。</p></div>')

    out.append('<div class="gap"><div class="gap-h">'
               '<span class="pill">原因三 · CONSUMED-THEN-CHECKED</span>'
               '<span class="gap-t">被拿來當標準的 spec，'
               '本身就是從被檢查的東西推導出來的</span></div>')
    out.append(
        f'<p class="gap-r">floorplan 的預算欄位 <code>{esc(fb["field"])}</code>，'
        f'在 <b>{fb["l19_docs"]}</b> 份已發佈的 L19 文件裡：'
        f'<b>{fb["null"]} 份是 null</b>、<b>{fb["key_absent"]} 份根本沒有這個欄位</b>、'
        f'只有 <b>{fb["populated"]} 份真的有值</b>'
        f'（其中 <b>{fb["populated_but_prose"]} 份還是散文</b>，'
        '像「user macro ~2900 x 3500 um」這種字串，機器無法拿來比較）。'
        '一個幾乎不存在的預算，沒辦法當成任何東西的上界。</p>')
    out.append(
        '<p class="gap-e">repo 自己的註解 '
        '<code>programs/floorplan_contract.py:56</code> 記的是'
        '「194 of 194 tracked L19 documents carry <code>die_area_budget_um: null</code>」。'
        f'<b>今天重量已經不是 194/194</b>：{fb["l19_docs"]} 份裡有 {fb["populated"]} 份有值。'
        '那條註解已經過期 —— 本頁發佈的是<b>今天量到的</b>。</p></div>')

    out.append('<div class="gap"><div class="gap-h">'
               '<span class="pill">原因五 · MISSING EXPERT ASSETS</span>'
               '<span class="gap-t">流程點名的 skill，一半不存在</span></div>')
    out.append(
        f'<p class="gap-r">flow YAML 點名 <b>{sk["declared"]}</b> 個 skill，'
        f'其中 <b>{sk["missing"]} 個在磁碟上不存在</b>'
        f'（<code>{esc(", ".join(sk["missing_names"][:6]))}</code> …）。'
        f'同時 <code>programs/</code> 底下有 <b>{pg["on_disk"]}</b> 支程式'
        f'（含底線開頭的共 {pg["all_py_in_programs"]} 支 .py），'
        f'而 flow YAML 只點到 <b>{pg["referenced_by_flow"]}</b> 支。</p>')
    out.append('<p class="gap-e">「這一步該由誰用專家判斷收尾」在流程裡有名字，'
               '在磁碟上沒有身體。</p></div>')
    out.append("</section>")

    # ── the ceiling, DERIVED ────────────────────────────────────────────
    out.append("<section>")
    out.append('<h3 class="d9-h3">天花板 —— 這個數字是<b>推導出來的</b>，不是估的</h3>')
    out.append(
        f'<p class="h2sub">{dark} 格暗的裡面，有 <b>{excl["dark_cells_blocked"]} 格'
        '的產出是 <code>PUBLISHING.md</code> 明文「Excluded by construction」的'
        '版圖幾何</b>。除非發佈政策改變，這幾格<b>在已發佈的 corpus 上永遠量不到</b>，'
        '不是靠寫程式能補的。</p>')
    out.append('<div class="scroll"><table class="run"><thead><tr>'
               '<th>step</th><th>今天為什麼暗</th><th>它需要的產出</th>'
               '</tr></thead><tbody>')
    for b in excl.get("blocked", []):
        need = b["needs"][0]
        out.append(f'<tr><td><code>{esc(b["step"])}</code></td>'
                   f'<td>{esc(CAUSES.get(b["cause"], (b["cause"],))[0])}</td>'
                   f'<td><code>{esc(need[:72])}</code></td></tr>')
    out.append("</tbody></table></div>")
    out.append(
        f'<div class="blk"><h3>推導：{steps} − {excl["dark_cells_blocked"]} = '
        f'<b>{excl["ceiling_on_published_corpus"]}</b></h3>'
        f'<p>在<b>今天這份已發佈的 corpus 上</b>，D9 最多能到 '
        f'<b>{excl["ceiling_on_published_corpus"]} / {steps}</b> 格。'
        '再往上需要的不是程式，是<b>改發佈政策</b>（讓 .def/.gds 進 repo）'
        '或<b>真的流片</b>（步驟 40–44 是 fab intake、wafer sort、packaging、'
        'final test、HTOL —— 沒有任何程式能生出那些產出）。</p></div>')
    out.append("</section>")

    # ── the plan, PLANNED not MEASURED ──────────────────────────────────
    out.append('<section class="d9-plan">')
    out.append('<h3 class="d9-h3"><span class="d9-planned">PLANNED</span> '
               '改善計畫 —— <b>以下沒有一個數字是量到的</b></h3>')
    out.append(
        '<p class="h2sub">上面每一格都是實跑出來的。<b>這一節不是。</b>'
        '這是提案，工期是估的，目標格數是估的。'
        '把它跟上面的量測混在一起加總，就是這整個頁面存在要防止的那件事。</p>')
    plan = [
        ("Phase 0", "把 PDK 自己的 Jmax、密度窗、製造格點寫進 run，"
                    "成為帶 sha256 的 <code>pdk_constants.json</code>",
         f'解開「物理上界」那一整類：今天 tech LEF 在 {ev["pdk"]["tech_lef_runs"]}/'
         f'{runs} 個 run 裡，所以這一類是 <b>0% 可執行</b>。'
         '<b>⚠ 實測修正：</b>brief 說它的 728 行 consumer「已經寫好了」—— '
         '<b>本次在樹裡找不到</b>。<code>pdk_constants</code> 只在 '
         '<code>analog_a2_topology_emit.py</code>（932 行）出現一次，'
         '而且只是一個 JSON key <code>pdk_constants_source</code>。'
         'Phase 0 要寫的是<b>產出端和消費端兩邊</b>。'),
        ("Phase 1", f'修掉 {causes.get("RULER-BLIND", 0)} 格「尺是瞎的」',
         '這是<b>最急的一類</b>，因為它今天是<b>綠的</b> —— '
         '一個把產出刪光還是照樣綠的 gate，比沒有 gate 更危險，'
         '它會讓讀者以為那一格有人在看。'),
        ("Phase 2", f'給 {causes.get("NO-BLOCKING-RULER", 0)} 格補上會擋的條款',
         '整條 gate 只有 <code>files_exist</code>：檔案在就過，內容不看。'),
        ("Phase 3", f'處理 {causes.get("ALREADY-RED", 0)} 格「本來就紅」+ '
                    f'{causes.get("RULER-NEVER-RAN", 0)} 格「尺沒跑起來」',
         '先讓它們在已發佈的 run 上跑得起來、紅得有理由，'
         '才談得上證明它們讀的是這個步驟的產出。'),
        ("Phase 4", f'把 {causes.get("DENOMINATOR", 0) - excl["dark_cells_blocked"]}'
                    f' 格分母為零、但<b>不是</b>被發佈政策擋住的格子填出分母',
         '這需要發佈帶著那些產出的 run，不是改程式。'),
        ("Phase 5", f'{excl["dark_cells_blocked"]} 格政策擋住的 + 需要真矽的',
         '要嘛改 <code>PUBLISHING.md</code>，要嘛流片。<b>不是工程排期問題。</b>'),
    ]
    out.append('<div class="scroll"><table class="run"><thead><tr>'
               '<th style="width:82px">phase</th><th>做什麼</th>'
               '<th>為什麼 / 實測註記</th></tr></thead><tbody>')
    for ph, what, why in plan:
        out.append(f'<tr><td><b>{esc(ph)}</b></td><td>{what}</td>'
                   f'<td>{why}</td></tr>')
    out.append("</tbody></table></div>")
    out.append(
        '<div class="blk d9-est"><h3>工期與目標：<b>估計值，不是量測值</b></h3>'
        '<p>委託本頁的 brief 給的是 <b>~14 engineer-weeks</b>、目標 '
        '<b>47 / 63</b>、天花板 <b>53</b>。'
        '本次<b>沒有</b>重新推導工期，所以照引並標明它是估的。'
        f'天花板<b>有</b>重新推導，得到的是 <b>{excl["ceiling_on_published_corpus"]}</b>'
        f'（{steps} 減去 {excl["dark_cells_blocked"]} 格被發佈政策寫死的），'
        '<b>不是 53</b>。兩個數字的差別在於「哪些格子算永久擋住」，'
        '本頁採用的是可查證的那一個：<code>PUBLISHING.md</code> 的明文排除清單。</p></div>')
    out.append("</section>")

    # ── where this page disagrees with its own commission ───────────────
    out.append("<section>")
    out.append('<h3 class="d9-h3">本頁與委託 brief <b>不一致</b>的地方 —— '
               '一律以量到的為準</h3>')
    out.append('<p class="h2sub">brief 是照昨天的樹寫的。'
               '凡是量出來不一樣的，本頁發佈<b>量到的那個</b>，並在這裡說明。</p>')
    dis = [
        ("今天會動的格數", "25 / 63 會動、38 格暗",
         f'<b>{moves} / {steps} 會動、{dark} 格暗</b>',
         'brief 的 25 用的是什麼判準未載明。本頁的判準是 two-arm artefact '
         'mutation，並且把判準本身寫在程式的 docstring 裡。'),
        ("分母為零的步驟數", "20",
         f'<b>{bands["zero"]}</b>',
         'run 目錄會互相巢狀（例如 <code>caravel_user_project/</code> 與其底下的 '
         '<code>v1.9.43_sky130A/</code>），檔案要用<b>最長前綴</b>歸屬，'
         '否則子 run 的檔案會被算到母 run 頭上。'),
        ("programs 支數", "1128 支，flow 點到 208 支",
         f'<b>{pg["on_disk"]}</b> 支（非底線開頭）／'
         f'<b>{pg["all_py_in_programs"]}</b> 支全部 .py，'
         f'flow 點到 <b>{pg["referenced_by_flow"]}</b> 支',
         f'「1128」比較接近全部 .py 的 '
         f'{pg["all_py_in_programs"]}；本頁把兩種定義都印出來。'),
        ("PDK 天花板", "53",
         f'<b>{excl["ceiling_on_published_corpus"]}</b>',
         f'由 <code>PUBLISHING.md</code> 排除清單推導：'
         f'{excl["dark_cells_blocked"]} 格的產出是 .def/.gds。'),
        ("Phase 0 的 consumer", "728 行，已經寫好了",
         "<b>找不到</b>",
         '<code>pdk_constants</code> 全樹只出現在 '
         '<code>analog_a2_topology_emit.py</code>（932 行）的一個 JSON key。'),
        ("EM 檢查的行為", "回報「0 of 1667 segment(s) screened」",
         "<b>rc=3 / SKIPPED / jmax_reference_absent</b>",
         '「N of M segment(s) screened」這句話在 '
         '<code>em_peak_current_authority_check.py</code>，'
         '不是 <code>em_current_density_check.py</code>；'
         '後者是誠實拒絕，不是回報 0。'),
        ("378 個謂詞的分類", "378 個具體謂詞，330 個 program-decidable",
         "<b>本頁不發佈這組數字</b>",
         'SELF-CONSISTENT / CROSS-ARTEFACT / SPEC-BOUND / PHYSICALLY-BOUNDED / '
         'EXPERT-JUDGMENT 這套分類<b>在樹裡不存在</b>，'
         '本次無法重新推導。照抄一個沒量過的數字，就是這個頁面存在要移除的那個缺陷。'),
    ]
    out.append('<div class="scroll"><table class="run"><thead><tr>'
               '<th style="width:130px">項目</th><th style="width:150px">brief 說</th>'
               '<th style="width:150px">本頁量到</th><th>為什麼不一樣</th>'
               '</tr></thead><tbody>')
    for item, brief_says, measured, why in dis:
        out.append(f'<tr><td>{item}</td><td class="d9-was">{brief_says}</td>'
                   f'<td class="d9-is">{measured}</td><td>{why}</td></tr>')
    out.append("</tbody></table></div>")
    out.append("</section>")

    # ── how to reproduce ────────────────────────────────────────────────
    out.append(
        '<div class="note d9-repro"><p><b>怎麼重跑這一節。</b>'
        '這一整塊是生成的，不是手打的：</p>'
        '<p><code>python3 tools/d9_flow_gate_reality.py '
        '--out tools/d9_reality</code><br>'
        '<code>python3 tools/gen_flow_gate_d9_section.py '
        '--reality tools/d9_reality/d9_reality.json '
        '--page flow-gate.html --check</code></p>'
        f'<p>掃描本身跑了 <b>{rep["two_arm_cells_planned"]}</b> 個 (step,run) '
        'two-arm cell，每一個都在<b>隔離副本</b>上做，'
        f'收尾驗證 <code>git status</code> 對 <code>benchmark-data/</code> '
        f'是<b>乾淨的</b>：<code>corpus_clean_after_sweep='
        f'{str(rep.get("corpus_clean_after_sweep")).lower()}</code>。'
        '<code>--check</code> 在數字漂移時 exit 1。</p></div>')

    out.append(END)
    return "\n".join(out)


CSS_MARK = "/* ── D9 ── */"

#: Uses ONLY the page's existing custom properties, so both themes follow the
#: page rather than this block inventing a second palette.
CSS = CSS_MARK + """
.d9-top{border-top:1px solid var(--line);padding-top:26px;margin-top:8px}
.d9-top h2{margin:9px 0 8px}
.d9-q{color:var(--key)}
.d9-oath{border:1px solid var(--contr-br);border-left:3px solid var(--contr);
  border-radius:9px;background:var(--contr-bg);padding:16px 18px;margin:18px 0 26px}
.d9-oath-h{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);font-weight:600;margin-bottom:11px}
.d9-may,.d9-mayn{margin:0 0 9px;font-size:13.5px;line-height:1.66;color:var(--ink-2)}
.d9-may b{color:var(--enf)} .d9-mayn b{color:var(--contr)}
.d9-cert{margin:13px 0 4px;font-size:15.5px;line-height:1.5;font-weight:700;
  color:var(--contr);letter-spacing:-.01em}
.d9-cert-zh{margin:0;font-size:13.5px;color:var(--ink);line-height:1.6}
.d9-score{margin-bottom:30px}
.d9-h3{font-size:16px;margin:0 0 4px;font-weight:660;letter-spacing:-.01em}
.d9-causes{display:grid;grid-template-columns:repeat(auto-fit,minmax(258px,1fr));
  gap:10px}
.d9-cause{display:flex;gap:12px;border:1px solid var(--line);border-left:3px solid var(--na);
  border-radius:8px;background:var(--surface);padding:12px 14px}
.d9-cause.c-blind{border-left-color:var(--contr)}
.d9-cause.c-den{border-left-color:var(--wai)}
.d9-cause.c-noruler{border-left-color:var(--wai)}
.d9-cause.c-red{border-left-color:var(--contr)}
.d9-cause.c-never{border-left-color:var(--na)}
.d9-cause-n{font-family:var(--mono);font-size:26px;font-weight:640;line-height:1;
  font-variant-numeric:tabular-nums;color:var(--ink);min-width:34px}
.d9-cause.c-blind .d9-cause-n,.d9-cause.c-red .d9-cause-n{color:var(--contr)}
.d9-cause.c-den .d9-cause-n,.d9-cause.c-noruler .d9-cause-n{color:var(--wai)}
.d9-cause-b{flex:1;min-width:0}
.d9-cause-t{font-size:13.5px;font-weight:640;margin-bottom:4px}
.d9-cause-k{font-family:var(--mono);font-size:10px;color:var(--ink-3);
  letter-spacing:.04em;font-weight:600}
.d9-cause-m{font-size:12.5px;color:var(--ink-2);line-height:1.55}
.d9-k{display:inline-block;font-family:var(--mono);font-size:9.5px;font-weight:700;
  letter-spacing:.06em;padding:2.5px 6px;border-radius:4px;border:1px solid}
.d9-k-mv{background:var(--enf-bg);color:var(--enf);border-color:var(--enf-br)}
.d9-k-dk{background:var(--contr-bg);color:var(--contr);border-color:var(--contr-br)}
table.d9-mx td{font-size:12px}
table.d9-mx tr.d9-dark td{background:var(--contr-bg)}
table.d9-mx tr.d9-dark td.sid{font-weight:700;color:var(--contr)}
.d9-why{font-size:11.5px;color:var(--ink-2)}
.d9-whyk{font-family:var(--mono);font-size:9.5px;color:var(--ink-3);letter-spacing:.04em}
.d9-plan{border-top:1px dashed var(--line);padding-top:22px}
.d9-planned{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;
  padding:3px 8px;border-radius:4px;background:var(--sunk);color:var(--ink-3);
  border:1px solid var(--line);margin-right:8px;vertical-align:2px}
.d9-est{border-left-color:var(--ink-3)}
.d9-was{color:var(--ink-3);text-decoration:line-through;font-size:12.5px}
.d9-is{color:var(--enf);font-size:12.5px}
.d9-repro{margin-top:14px}
"""


def install(page: str) -> str:
    """Idempotently place the CSS and the two markers.

    Placement is DELIBERATE: the block goes immediately after the scoreboard and
    BEFORE the eight-dimension table, because the sentence it carries has to be
    read before the reader sees eight columns of green.
    """
    if CSS_MARK not in page:
        page = page.replace("\n</style>", "\n" + CSS + "</style>", 1)
    if BEGIN not in page:
        anchor = "<!-- END GENERATED SCORE -->\n</div>\n"
        if anchor not in page:
            raise SystemExit("scoreboard anchor not found; page shape changed")
        page = page.replace(anchor, anchor + BEGIN + "\n" + END + "\n", 1)
    return page


def splice(page: str, block: str) -> str:
    if BEGIN in page and END in page:
        pre = page.split(BEGIN)[0]
        post = page.split(END, 1)[1]
        return pre + block + post
    raise SystemExit("markers not found; use --install to place them first")


#: The flow labels its own D9 clauses. When #1009 wrote this program the label
#: did not exist; today the yaml carries them, so the question of whether the
#: flow asks the ninth question is decided BY THE FLOW, not by a sentence in
#: this file's docstring.
_D9_LABEL_RE = re.compile(r"^\s*#\s*D9\b", re.M)

_FLOW_REL = ("vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml")


def _repo_root() -> Optional[Path]:
    for anc in Path(__file__).resolve().parents:
        if (anc / _FLOW_REL).is_file():
            return anc
    return None


def flow_asks_the_ninth_question(root: Path) -> int:
    """How many D9-labelled clauses the flow carries. 0 means the premise holds."""
    return len(_D9_LABEL_RE.findall(
        (root / _FLOW_REL).read_text(encoding="utf-8", errors="ignore")))


def flow_step_count(root: Path) -> int:
    """Steps the flow declares — the population any D9 figure is a fraction of."""
    import yaml                                   # local: keep import cost off
    data = yaml.safe_load((root / _FLOW_REL).read_text(encoding="utf-8"))
    return len([s for s in (data or {}).get("steps") or [] if s.get("id") is not None])


def premise_refusal(rep: Dict, root: Optional[Path]) -> Optional[str]:
    """Why this program must not render today, or None if it may.

    TWO CHECKS, and both are about whether this program's SUBJECT still exists.

    (1) THE PREMISE. This file's docstring says it refuses to publish D9 as a
        shipped dimension because "nothing in `flow/phase1_phase2_phase3.yaml`
        asks the ninth question". MEASURED 2026-08-28: the flow carries four
        `# D9` labelled clauses, one of them the BLOCKING
        `program_exit_zero: "step_internal_fail_bubble_up_check ."` in step 36.
        The premise is false, and it is false IN THE FILE IT NAMES.

        It is also not the same question any more. #1009 measured "is the output
        CORRECT". The shipped D9 is `verdict_consumed` -- does a step's FAIL
        survive to the process exit code -- and the page says so in its own
        words: "The ninth question is shipped -- and it is not 'is the output
        correct?'". Rendering this block onto that page would publish a denial
        of what the page next to it asserts.

    (2) THE DATA'S FLOW. The report describes a 63-step flow; the flow has 68.
        Every figure in the block is a fraction of a population that no longer
        exists, and the block additionally hardcodes 504 = 63 x 8 in its prose,
        which no refresh of the report would correct.

    Neither is repairable by re-running the producer. MEASURED: `benchmark-data/`
    was exported to its own repository at v1.10.56 (e23d0be5e, 2026-08-17), so
    `d9_flow_gate_reality.py` exits rc 2 "benchmark-data/ not found" here and has
    no corpus-path option. The report shipped on 2026-08-18, INTO a tree where
    the corpus was already gone -- it was un-regenerable the day it landed.
    """
    if root is None:
        return ("this program could not locate the flow it is about to publish "
                "figures against, so it cannot tell whether its own premise "
                "still holds")

    d9_clauses = flow_asks_the_ninth_question(root)
    if d9_clauses:
        return (f"this program's stated premise is that nothing in the flow asks "
                f"the ninth question. The flow carries {d9_clauses} `# D9` "
                f"labelled clause(s) today, including a blocking one in step 36. "
                f"The premise is false, and the shipped D9 is `verdict_consumed`, "
                f"not the output-correctness question this report measured")

    steps = flow_step_count(root)
    if rep.get("steps") not in (None, steps):
        return (f"the report describes a {rep['steps']}-step flow and the flow "
                f"has {steps} steps. Every figure in the block is a fraction of "
                f"a population that no longer exists")
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reality", required=True)
    ap.add_argument("--page")
    ap.add_argument("--emit")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--install", action="store_true",
                    help="place the CSS and the markers (idempotent)")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    rep = json.loads(Path(args.reality).read_text())

    # BEFORE ANY RENDERING. A refusal that still emitted the fragment would let
    # the next caller install what this one declined to publish.
    refusal = premise_refusal(rep, _repo_root())
    if refusal:
        print(f"CANNOT CHECK: {refusal}. Nothing was rendered, emitted or "
              f"written. NOT a pass -- and NOT an invitation to re-install the "
              f"markers: reconnecting this block would publish a denial of what "
              f"the page beside it asserts. See the module docstring.",
              file=sys.stderr)
        return 2

    block = render(rep)

    if args.emit:
        Path(args.emit).write_text(block + "\n")
        print(f"wrote fragment: {args.emit} ({len(block)} bytes)")

    if not args.page:
        return 0
    page_path = Path(args.page)
    page = page_path.read_text()

    if args.install:
        page = install(page)
        page_path.write_text(page)
        print(f"installed CSS + markers into {page_path}")

    if args.check:
        if BEGIN not in page:
            # NOT "reconnect me". The markers are absent because the page
            # replaced this block, CSS and all, with a section asserting the
            # opposite; the guard above is what decides whether that was right.
            print("D9 block absent from page — the page carries its own D9 "
                  "section instead", file=sys.stderr)
            return 1
        current = BEGIN + page.split(BEGIN, 1)[1].split(END)[0] + END
        if current.strip() != block.strip():
            print("D9 block DRIFTED from the measurement", file=sys.stderr)
            return 1
        print("D9 block matches the measurement")
        return 0

    if args.write:
        page_path.write_text(splice(page, block))
        print(f"spliced D9 block into {page_path} "
              f"({page_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
