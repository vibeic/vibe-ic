#!/usr/bin/env python3
"""benchmark_golden_capture.py — record a HOST-VERIFIED, vibe-ic-AUTHORED solution as
OUR OWN golden, kept SEPARATE from the downloaded `reference_solution`, and tagged with
the plugin version + AI model that produced it — so we can later cross-reference how our
solutions evolve across plugin versions / models (user directive 2026-06-22).

Why a separate corpus: the downloaded reference solutions (NVIDIA/RTLLM) are the upstream
oracle; OUR golden is what the vibe-ic plugin + an AI model produced and the HOST scorer
verified PASS. Mixing them would contaminate the upstream oracle. Keeping a versioned,
model-tagged parallel corpus lets us diff plugin-version A vs B on the same problem.

Storage (both, for robustness against the concurrent-rebuild / git-clean hazard):
  1. table `vibe_golden_solutions` in the given sqlite DB — CREATE IF NOT EXISTS; survives
     `build_db.py` (which only DROPs `problems`/`benchmarks`). UNIQUE(benchmark, problem_id,
     plugin_version, ai_model) so a re-run UPSERTs and each version/model keeps its own row.
  2. an append-only JSONL backup OUTSIDE any git repo (default ~/vibe_golden/golden_backup.jsonl)
     — disaster recovery if a concurrent session wipes/reverts the DB; re-importable via `import`.

CLI:
  init    --db <sqlite>
  capture --db <sqlite> --benchmark B --problem P --rtl f.sv [--spec f.yaml]
          --plugin-version 1.1.59 --ai-model claude-opus-4-8
          [--host-verdict PASS] [--scorer "iverilog-12 / bench.py eval"] [--run-id R] [--backup JSONL]
  import  --db <sqlite> --backup JSONL          # rebuild the table from the JSONL backup
  list    --db <sqlite> [--benchmark B]         # print (problem, version, model, verdict) rows
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_BACKUP = os.path.expanduser("~/vibe_golden/golden_backup.jsonl")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vibe_golden_solutions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  benchmark      TEXT NOT NULL,
  problem_id     TEXT NOT NULL,
  solution_rtl   TEXT NOT NULL,
  spec_yaml      TEXT,
  plugin_version TEXT NOT NULL,
  ai_model       TEXT NOT NULL,
  host_verdict   TEXT NOT NULL DEFAULT 'PASS',
  scorer         TEXT,
  run_id         TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE(benchmark, problem_id, plugin_version, ai_model)
);
CREATE INDEX IF NOT EXISTS idx_vgs_problem ON vibe_golden_solutions(benchmark, problem_id);
CREATE INDEX IF NOT EXISTS idx_vgs_version ON vibe_golden_solutions(plugin_version, ai_model);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db(db: str) -> None:
    cx = sqlite3.connect(db)
    cx.executescript(_SCHEMA)
    cx.commit()
    cx.close()


def _upsert(cx, row: dict) -> None:
    cx.execute(
        """INSERT INTO vibe_golden_solutions
           (benchmark,problem_id,solution_rtl,spec_yaml,plugin_version,ai_model,host_verdict,scorer,run_id,created_at)
           VALUES (:benchmark,:problem_id,:solution_rtl,:spec_yaml,:plugin_version,:ai_model,:host_verdict,:scorer,:run_id,:created_at)
           ON CONFLICT(benchmark,problem_id,plugin_version,ai_model) DO UPDATE SET
             solution_rtl=excluded.solution_rtl, spec_yaml=excluded.spec_yaml,
             host_verdict=excluded.host_verdict, scorer=excluded.scorer,
             run_id=excluded.run_id, created_at=excluded.created_at""", row)


def capture(db: str, benchmark: str, problem: str, rtl: str, spec: str | None,
            plugin_version: str, ai_model: str, host_verdict: str = "PASS",
            scorer: str = "", run_id: str = "", backup: str = _DEFAULT_BACKUP) -> dict:
    if not plugin_version or not ai_model:
        raise SystemExit("ERROR: --plugin-version and --ai-model are REQUIRED (provenance tags).")
    rtl_text = Path(rtl).read_text(errors="replace")
    spec_text = Path(spec).read_text(errors="replace") if spec and os.path.isfile(spec) else None
    row = {"benchmark": benchmark, "problem_id": problem, "solution_rtl": rtl_text,
           "spec_yaml": spec_text, "plugin_version": plugin_version, "ai_model": ai_model,
           "host_verdict": host_verdict, "scorer": scorer or None, "run_id": run_id or None,
           "created_at": _utc_now()}
    init_db(db)
    cx = sqlite3.connect(db)
    _upsert(cx, row)
    cx.commit()
    cx.close()
    # durable append-only backup OUTSIDE any git repo
    os.makedirs(os.path.dirname(backup) or ".", exist_ok=True)
    with open(backup, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def import_backup(db: str, backup: str) -> int:
    init_db(db)
    cx = sqlite3.connect(db)
    n = 0
    with open(backup) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            _upsert(cx, json.loads(line))
            n += 1
    cx.commit()
    cx.close()
    return n


def list_rows(db: str, benchmark: str | None) -> None:
    cx = sqlite3.connect(db)
    init_db(db)
    q = ("SELECT benchmark,problem_id,plugin_version,ai_model,host_verdict,created_at "
         "FROM vibe_golden_solutions")
    args: tuple = ()
    if benchmark:
        q += " WHERE benchmark=?"
        args = (benchmark,)
    q += " ORDER BY benchmark,problem_id,plugin_version,ai_model"
    rows = list(cx.execute(q, args))
    for r in rows:
        print(f"  {r[0]:18s} {r[1]:30s} v{r[2]:8s} {r[3]:20s} {r[4]:5s} {r[5]}")
    print(f"total vibe-golden rows: {len(rows)}")
    cx.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--db", required=True)
    pc = sub.add_parser("capture")
    pc.add_argument("--db", required=True); pc.add_argument("--benchmark", required=True)
    pc.add_argument("--problem", required=True); pc.add_argument("--rtl", required=True)
    pc.add_argument("--spec", default=None)
    pc.add_argument("--plugin-version", required=True); pc.add_argument("--ai-model", required=True)
    pc.add_argument("--host-verdict", default="PASS"); pc.add_argument("--scorer", default="")
    pc.add_argument("--run-id", default=""); pc.add_argument("--backup", default=_DEFAULT_BACKUP)
    pm = sub.add_parser("import"); pm.add_argument("--db", required=True)
    pm.add_argument("--backup", default=_DEFAULT_BACKUP)
    pl = sub.add_parser("list"); pl.add_argument("--db", required=True); pl.add_argument("--benchmark", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "init":
        init_db(a.db); print(f"vibe_golden_solutions ready in {a.db}")
    elif a.cmd == "capture":
        r = capture(a.db, a.benchmark, a.problem, a.rtl, a.spec, a.plugin_version, a.ai_model,
                    a.host_verdict, a.scorer, a.run_id, a.backup)
        print(f"captured {r['benchmark']}/{r['problem_id']} (plugin v{r['plugin_version']}, "
              f"{r['ai_model']}, {r['host_verdict']}) @ {r['created_at']}")
    elif a.cmd == "import":
        print(f"imported {import_backup(a.db, a.backup)} rows from {a.backup}")
    elif a.cmd == "list":
        list_rows(a.db, a.benchmark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
