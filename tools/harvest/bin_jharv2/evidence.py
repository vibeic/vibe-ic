#!/usr/bin/env python3
"""For every KEEP, name one file and prove it by hand-checkable sha256, then say what it is.

The report must be falsifiable by someone who does not trust it: for each KEEP this prints
the sha256 of the bytes ON DISK and the sha256 of `git show origin/main:<path>`, the exact
two commands a reader can re-run. It also states what the file contains -- taken from the
file itself (module docstring / first comment / first real line) and from the size of its
difference against main -- never from a guess about intent.
"""
import os, subprocess, hashlib, sys

D = "/home/reyerchu/_harvb"
R = "/home/reyerchu/vibe-ic"

def sh(*a, **kw):
    return subprocess.run(a, capture_output=True, **kw)

def sha_file(p):
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None

def sha_main(path):
    r = sh("git", "-C", R, "show", f"origin/main:{path}")
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout).hexdigest()

def describe(p, path):
    """What the file contains, read out of the file."""
    try:
        raw = open(p, encoding="utf-8", errors="replace").read()
        txt = raw[:8000]
    except OSError:
        return "(unreadable)"
    lines = txt.splitlines()
    doc = None
    for i, ln in enumerate(lines[:40]):
        s = ln.strip()
        if not s or s.startswith("#!") or s.startswith("# -*-"):
            continue
        if s.startswith('"""') or s.startswith("'''"):
            body = s.strip("\"'").strip()
            if body:
                doc = body
            elif i + 1 < len(lines):
                doc = lines[i + 1].strip()
            break
        if s.startswith("#") or s.startswith("//"):
            doc = s.lstrip("#/ ").strip()
            break
        doc = s
        break
    if not doc:
        doc = "(no header line)"
    n = raw.count("\n") + (0 if raw.endswith("\n") or not raw else 1)
    kind = {".py": "python", ".sh": "shell", ".md": "markdown", ".json": "json",
            ".yaml": "yaml", ".yml": "yaml", ".v": "verilog", ".sv": "systemverilog",
            ".tcl": "tcl"}.get(os.path.splitext(path)[1], "file")
    return f"{kind}, {n} lines — {doc[:150]}"

def delta(p, path):
    """How far it is from main, in lines. Both sides are real files -- an earlier version of
    this used `git diff --no-index /dev/stdin`, which silently reported the whole file as
    added and made every number in the column wrong."""
    r = sh("git", "-C", R, "show", f"origin/main:{path}")
    if r.returncode != 0:
        return "main has no file at this path"
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as t:
        t.write(r.stdout)
        tn = t.name
    try:
        d = sh("git", "diff", "--numstat", "--no-index", "--", tn, p)
        out = d.stdout.decode("utf-8", "replace").split()
        if len(out) >= 2 and out[0].isdigit() and out[1].isdigit():
            return f"+{out[0]}/-{out[1]} lines vs main"
        if not out:
            return "identical to main (0 lines differ)"
        return "differs from main"
    finally:
        os.unlink(tn)

def first_novel(lst):
    """The first real PATH in an evidence list.

    The uncommitted list is rendered as `UNCOMMITTED[MOD:path,NEW:path]`, and the previous version
    split on commas and stripped only the bare prefixes — so it handed back the literal token
    `UNCOMMITTED[MOD:vibe-ic-.../x.py` as a path, the file lookup failed, and 214 published rows
    ended up claiming `sha256(UNCOMMITTED[...]) = (not on disk) here, - on main`. Evidence that
    names nothing and hashes nothing, in the column whose whole job is being checkable.
    """
    for tok in lst.split(","):
        tok = tok.strip()
        if not tok:
            continue
        i = tok.find("UNCOMMITTED[")
        if i != -1:
            tok = tok[i + len("UNCOMMITTED["):]
        tok = tok.lstrip("[").rstrip("]")
        for pre in ("ONLY_HERE:", "DIFFERS:", "NEW:", "MOD:"):
            if tok.startswith(pre):
                tok = tok[len(pre):]
                break
        tok = tok.strip()
        # a top-level file has no slash; requiring one dropped .codex-marketplace-install.json
        if tok and not tok.startswith("(") and not tok.endswith(":"):
            return tok
    return None

rows = []
# pruned rows: path, verdict, base, nown, novel, landed, deln, novel_list, landed_list
fp = os.path.join(D, "rows_pruned.tsv")
if os.path.exists(fp):
    for ln in open(fp, encoding="utf-8", errors="replace").read().splitlines():
        f = (ln.split("\t") + [""] * 9)[:9]
        if f[1].startswith("KEEP") and f[7]:
            rows.append((f[0], f[7], "pruned"))
# registered rows: repo, wt, br, head, st, ..., novel_list(13), super/unc(14)
fr = os.path.join(D, "rows_reg.tsv")
if os.path.exists(fr):
    for ln in open(fr, encoding="utf-8", errors="replace").read().splitlines():
        f = (ln.split("\t") + [""] * 16)[:16]
        if f[4].startswith("KEEP"):
            lst = f[12] or f[13]
            if lst:
                rows.append((f[1], lst, "registered"))

out = open(os.path.join(D, "evidence.tsv"), "w", encoding="utf-8")
for wt, lst, kind in rows:
    path = first_novel(lst)
    if not path:
        continue
    p = os.path.join(wt, path)
    if not os.path.exists(p):
        out.write(f"{wt}\t{path}\t(not on disk)\t-\t-\t-\n")
        continue
    a = sha_file(p)
    b = sha_main(path)
    out.write("\t".join([wt, path, a or "-", b or "(no such path on origin/main)",
                         delta(p, path), describe(p, path)]) + "\n")
out.close()
print(sum(1 for _ in open(os.path.join(D, "evidence.tsv"))), "evidence rows")
