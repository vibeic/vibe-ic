#!/usr/bin/env python3
"""Run ONE selection of test files against ONE tree, per file, and record.

Mirrors the per-file shape the landing tier uses (`pytest_per_file_junit.run_one`):
cwd = plugin root, `-o junit_family=xunit1 --junitxml=<per-file>`, one file per
session. The candidate's progress-supervision plugin is deliberately NOT used —
the harness is the thing under dispute, so both trees are driven by the same
plain pytest and only the SUBJECT differs.

Every file lands in exactly one bucket and the buckets are disjoint:
  RECORDED  a junit XML exists and pytest printed a summary line
  NORECORD  the session produced no usable junit (timeout / crash / no summary)
  NOTRUN    the file does not exist in this tree
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

tree, listfile, outdir, timeout_s = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
plugin = Path(tree) / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
out = Path(outdir); (out / "junit").mkdir(parents=True, exist_ok=True); (out / "log").mkdir(exist_ok=True)
files = [l.strip() for l in Path(listfile).read_text().splitlines() if l.strip()]

# pytest's own summary line. "no tests ran" is DID NOT RUN and is NOT a summary
# that licenses a green: it is recorded as such and never folded into RECORDED.
SUMMARY = re.compile(r"^=+ .*?\b(passed|failed|error|errors|skipped|xfailed|xpassed|no tests ran)\b.*?=+\s*$", re.M)
NOTESTS = re.compile(r"\bno tests ran\b")

rows = []
for i, f in enumerate(files, 1):
    p = plugin / f
    stem = f.replace("/", "__")
    if not p.is_file():
        rows.append({"file": f, "bucket": "NOTRUN", "reason": "file absent in this tree"})
        print(f"[{i}/{len(files)}] NOTRUN  {f}", flush=True); continue
    jx = out / "junit" / f"{stem}.xml"
    cmd = [sys.executable, "-m", "pytest", "-p", "no:randomly",
           "-o", "junit_family=xunit1", f"--junitxml={jx}", f]
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, cwd=str(plugin), capture_output=True, text=True,
                            errors="replace", timeout=timeout_s)
        rc, tail, timed_out = cp.returncode, (cp.stdout or "") + (cp.stderr or ""), False
    except subprocess.TimeoutExpired as exc:
        rc, timed_out = None, True
        tail = ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) + \
               ((exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
    dt = time.time() - t0
    (out / "log" / f"{stem}.log").write_text(tail)
    m = SUMMARY.search(tail)
    summary = m.group(0).strip() if m else ""
    if timed_out:
        bucket, reason = "NORECORD", f"STALLED after {timeout_s:.0f} s"
    elif not jx.is_file():
        bucket, reason = "NORECORD", f"no junit written (rc={rc})"
    elif not summary:
        bucket, reason = "NORECORD", f"no pytest summary line printed (rc={rc})"
    elif NOTESTS.search(summary):
        bucket, reason = "NORECORD", f"no tests ran — DID NOT RUN (rc={rc})"
    else:
        bucket, reason = "RECORDED", ""
    rows.append({"file": f, "bucket": bucket, "reason": reason, "rc": rc,
                 "seconds": round(dt, 1), "summary": summary, "junit": str(jx) if jx.is_file() else ""})
    print(f"[{i}/{len(files)}] {bucket:8s} {dt:6.1f}s {f}  {summary or reason}", flush=True)

(out / "run.json").write_text(json.dumps(
    {"tree": str(tree), "head": subprocess.run(["git","-C",tree,"rev-parse","HEAD"],
     capture_output=True,text=True).stdout.strip(), "files": len(files), "rows": rows}, indent=1) + "\n")
from collections import Counter
c = Counter(r["bucket"] for r in rows)
print(f"\n== {tree}: RECORDED {c['RECORDED']} / NORECORD {c['NORECORD']} / NOTRUN {c['NOTRUN']} of {len(files)}")
