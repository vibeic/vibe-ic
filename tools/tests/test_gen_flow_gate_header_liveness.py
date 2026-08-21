"""The page must not claim in words what the generator inherits.

The header was made honest before the PROSE was, and the prose is what a reader
believes. Nobody reads a two-part timestamp to decide what a sentence means.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

GEN = None
for _c in (Path(__file__).resolve().parents[2] / "tools" / "gen_flow_gate_header.py",
           Path(__file__).resolve().parents[4] / "tools" / "gen_flow_gate_header.py"):
    if _c.is_file():
        GEN = _c
        break

PAGE = """<html><head>
<meta name="description" content="Vibe-IC 流程 63 步驟 x 8 判斷維度的即時狀態：504 格，每一格都是對當前原始碼重新計算的謂詞。">
</head><body><div class="wrap"><div class="top">
<div class="eyebrow">Flow Gate · live state</div>
<h1>x</h1>
<p class="sub">每一格都是對當前原始碼<b>重新計算</b>的謂詞，不是把判定存起來再讀回來。這張表隨 repo 變動。</p>
<div class="meta"><span>plugin <b>v0.0.1</b></span><span>flow steps <b>1</b></span>
<span>cells <b>8</b></span><span>updated <b>2000-01-01 00:00</b></span></div>
</div><table><tr><td class="dnum">1</td></tr></table></body></html>
"""


def _write(tmp: Path) -> Path:
    p = tmp / "page.html"
    p.write_text(PAGE, encoding="utf-8")
    return p


def _run(page: Path, *extra):
    root = GEN.resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(GEN), "--page", str(page), "--plugin-root",
         str(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"), *extra],
        capture_output=True, text=True, timeout=30)


def test_main_still_reaches_its_write_call():
    """A column-0 `def` inserted into a function body silently ENDS that body.

    That happened here: `main` returned None before writing, `sys.exit(None)`
    exited 0, and nothing printed. `ast.parse` was perfectly happy. This asserts
    the structure rather than the syntax.
    """
    tree = ast.parse(GEN.read_text(encoding="utf-8"))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "rewrite_liveness_claims" in fns, "helper must be module-level"
    main = fns["main"]
    src = GEN.read_text(encoding="utf-8").splitlines()
    body = "\n".join(src[main.lineno - 1:main.end_lineno])
    assert "write_text" in body, "main() no longer reaches its write call"


def test_check_reports_every_worded_liveness_claim(tmp_path):
    r = _run(_write(tmp_path), "--check")
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout
    assert out.count("claims liveness in words") >= 3, out
    assert "live state" in out


def test_writing_replaces_the_claims_with_which_half_is_live(tmp_path):
    p = _write(tmp_path)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    after = p.read_text(encoding="utf-8")
    assert "不是把判定存起來再讀回來" not in after
    assert "Flow Gate · live state" not in after
    assert "原封搬運" in after
    assert "distributions inherited" in after


def test_it_is_idempotent(tmp_path):
    """A corrected page must not be rewritten, and --check must go quiet.

    The timestamp is frozen with `--now`, which exists for exactly this: it moves
    every run by design, so comparing whole files without pinning it would test
    the clock rather than the substitution.
    """
    p = _write(tmp_path)
    _run(p, "--now", "2030-01-01 00:00")
    first = p.read_text(encoding="utf-8")
    _run(p, "--now", "2030-01-01 00:00")
    assert p.read_text(encoding="utf-8") == first
    r = _run(p, "--check")
    assert "claims liveness in words" not in r.stdout, r.stdout
