#!/usr/bin/env python3
"""mktable.py -- render the triage table the job asks for, one row per worktree,
every row carrying a disposition."""
import sys, os, re
from collections import Counter, defaultdict

src = sys.argv[1]; out = sys.argv[2]
rows = [l.rstrip("\n").split("\t") for l in open(src, errors="replace")]
hdr, rows = rows[0], rows[1:]
I = {k: i for i, k in enumerate(hdr)}
g = lambda r, k: r[I[k]] if I[k] < len(r) else ""

HOSTNAME = {"105": "8HD-9", "108": "8HD-6", "112": "8HD-d",
            "114": "8HD-8", "120": "8HD-4", "121": "8hd-3"}

def what(r):
    """one line: what this worktree changes."""
    s = g(r, "subject").strip() or "(no subject)"
    s = re.sub(r"\s+", " ", s)
    if len(s) > 118: s = s[:115] + "..."
    nf = [x.split("/")[-1] for x in g(r, "novelfiles").split(",") if x][:3]
    td = ", ".join(nf) if nf else g(r, "topdirs")
    nadd, trk = g(r, "code_add") or g(r, "nadd"), g(r, "trk_dirty")
    bits = [s]
    if td: bits.append(f"`{td[:96]}`")
    if trk and trk != "0": bits.append(f"**+{trk} uncommitted**")
    return "<br>".join(bits)

def esc(x): return x.replace("|", "\\|")

vc = Counter(g(r, "verdict") for r in rows)
rc = Counter(g(r, "rule") for r in rows)
hc = Counter(g(r, "host") for r in rows)
hv = defaultdict(Counter)
for r in rows: hv[g(r, "host")][g(r, "verdict")] += 1

L = []
A = L.append
A("# vibe-ic worktree harvest triage")
A("")
A(f"Every vibe-ic worktree on all six fleet machines, one row each, every row "
  f"carrying a disposition. **{len(rows)} worktrees**, all measured against "
  f"`origin/main` **867de428** (2026-08-21) — the 20 surviving non-`~/vibe-ic` "
  f"clones were fetched first so nothing is judged against a stale ref.")
A("")
A("## How the verdict was reached")
A("")
A("`vibe-ic` lands everything as a **squash**, so a fully-landed branch is never an "
  "ancestor of `main`: `git merge-base --is-ancestor`, `git branch --merged` and "
  "`rev-list --count origin/main..HEAD` all report landed work as unlanded. Nothing "
  "here uses ancestry. The verdict is decided on content, and the load-bearing "
  "number is:")
A("")
A("> **`nadd`** — added lines of `git diff --numstat origin/main <head>` restricted to "
  "the files the worktree itself touched (`merge-base..head`). This is the content the "
  "worktree **has that `main` does not**. Its mirror `ndel` measures only how far "
  "*behind* `main` the tree is.")
A("")
A("Summing the two — which an earlier pass of this job did — makes a merely stale tree "
  "look like thousands of lines of recoverable work. `nadd == 0` means there is nothing "
  "in the tree that `main` lacks, however far its history has diverged.")
A("")
A("| verdict | count | meaning |")
A("|---|---:|---|")
A(f"| **LANDED** | {vc['LANDED']} | content already in `main`. Safe to delete. |")
A(f"| **RECOVER** | {vc['RECOVER']} | real work worth keeping. |")
A(f"| **ABANDON** | {vc['ABANDON']} | superseded, duplicated by something landed, or spent scratch. |")
A("")
A("### Rules, in the order they fire")
A("")
A("| rule | verdict | fires when |")
A("|---|---|---|")
for rid, v, txt in [
  ("L2","RECOVER","committed content is in `main` but the tree carries uncommitted tracked edits — those edits are the work"),
  ("L0","LANDED","`nadd == 0` and clean: nothing in the tree is absent from `main`"),
  ("L1","LANDED","every changed file byte-identical to `main`, or its hunks already present there"),
  ("N1","LANDED","the only lines absent from `main` are version manifests / README version strings from an older release"),
  ("A1","ABANDON","tip is a gatekeeper PR-verification merge and that PR **merged** (landed squashed)"),
  ("A2","ABANDON","tip is a PR-verification merge and that PR was closed **without** merging (rejected)"),
  ("R1","RECOVER","tip is a PR-verification merge and that PR is still **open**"),
  ("A3","ABANDON","`[vX.Y.Z] candidate batch` staging tree for a version older than `main`'s v1.11.2"),
  ("A5","ABANDON","tip is a bare integration merge holding ≤20 lines absent from `main` — merge-queue scratch"),
  ("A4","ABANDON","identical `HEAD` to a tree already kept elsewhere in this table"),
  ("R2","RECOVER","anything else — sized by `nadd`"),
  ("U1","RECOVER","the row could not be measured (worktree state `GONE`/`NOHEAD`) — verdict withheld, defaulting to keep")]:
    A(f"| `{rid}` | {v} | {txt} ({rc.get(rid,0)}) |")
A("")
A("Ties break toward RECOVER: an over-cautious keep costs disk, a wrong ABANDON "
  "destroys work nobody can reconstruct.")
A("")
A("### Per host")
A("")
A("| host | ip | worktrees | LANDED | RECOVER | ABANDON |")
A("|---|---|---:|---:|---:|---:|")
for h in sorted(hc, key=lambda x: -hc[x]):
    A(f"| {HOSTNAME.get(h,h)} | 192.168.1.{h} | {hc[h]} | {hv[h]['LANDED']} | {hv[h]['RECOVER']} | {hv[h]['ABANDON']} |")
A("")
A("---")
A("")
A("## The table")
A("")
A("**code** = authored lines this tree has that `main` lacks. **all** = the same "
  "including regenerable artefacts (`benchmark-data/`, `*.json`, reports). `#` = the "
  "issue it belongs to where one could be identified. RECOVER is ordered by "
  "uncommitted edits first, then authored lines — read it top-down.")
A("")

order = {"RECOVER": 0, "ABANDON": 1, "LANDED": 2}
def rank(r):
    return (-int(g(r, "trk_dirty") or 0), -int(g(r, "code_add") or 0), -int(g(r, "nadd") or 0))
rows.sort(key=lambda r: (order[g(r, "verdict")],) + rank(r) + (g(r, "host"), g(r, "path")))
for v in ("RECOVER", "ABANDON", "LANDED"):
    sub = [r for r in rows if g(r, "verdict") == v]
    A(f"### {v} — {len(sub)}")
    A("")
    A("| worktree | host | what it changes | code | all | # | verdict | why |")
    A("|---|---|---|---:|---:|---|---|---|")
    for r in sub:
        p = g(r, "path").replace("/home/reyerchu/", "~/")
        repo = g(r, "repo")
        if repo and repo != "/home/reyerchu/vibe-ic":
            p += f"  <sub>({repo.replace('/home/reyerchu/','~/')})</sub>"
        A(f"| `{esc(p)}` | {HOSTNAME.get(g(r,'host'),g(r,'host'))} | {esc(what(r))} | "
          f"{g(r,'code_add')} | {g(r,'nadd')} | {g(r,'issue') or '—'} | **{v}** | {esc(g(r,'why'))} "
          f"(`{g(r,'rule')}`) |")
    A("")
open(out, "w").write("\n".join(L) + "\n")
print(f"{out}: {len(rows)} rows  {dict(vc)}")
