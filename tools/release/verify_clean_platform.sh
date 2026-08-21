#!/usr/bin/env bash
# verify_clean_platform.sh — vibe-ic release reproducibility gate.
#
# Goal: on a fresh platform, prove the install is
# whole and REPRODUCES our verified benchmark scores — deterministically, no
# reference answers touched.
#
# Four phases (each prints [PASS]/[FAIL]/[SKIP]; the script exits non-zero if any
# non-skipped check FAILs):
#   0. host tools preflight     (python3, node, iverilog; docker optional)
#   1. plugin structure present (marketplace/plugin json, .mcp.json, flow, registry)
#   2. plugin self-checks       (flow-compliance, expert-DB consistency, chip-agnostic, MCP import)
#   3. benchmark reproduce      (re-score the committed samples; assert == verified numbers)
#
# Phase 3 needs the external datasets (not shipped). Point to them with env vars;
# absent → that benchmark SKIPs (not a failure), with an explicit hint:
#   RTLLM_DATASET=/path/to/RTLLM
#   VEV2_DATASET=/path/to/verilog-eval/dataset_spec-to-rtl
#   VEHUMAN_DATASET=/path/to/verilog-eval/dataset_code-complete-iccad2023
#
# Usage:  tools/release/verify_clean_platform.sh            # from repo root
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLUGIN="$REPO/vibe-ic-marketplace/plugins/vibe-ic"
EVAL="$REPO/benchmark-data/evaluation"
PASS=0 FAIL=0 SKIP=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }
skip() { echo "  [SKIP] $*"; SKIP=$((SKIP+1)); }
hdr()  { echo; echo "== $* =="; }

# ── Phase 0 — host tools ────────────────────────────────────────────────────
hdr "Phase 0 — host tool preflight"
for t in python3 node; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t present ($($t --version 2>&1 | head -1))"
  else bad "$t MISSING (required)"; fi
done
if command -v iverilog >/dev/null 2>&1; then ok "iverilog present ($(iverilog -V 2>&1 | head -1))"
else bad "iverilog MISSING (required for functional pass@1)"; fi
if command -v docker >/dev/null 2>&1; then
  if docker image ls 2>/dev/null | grep -qiE 'vibeic-eda'; then ok "vibeic-eda docker image present (forked+enhanced EDA toolchain)"
  elif docker image ls 2>/dev/null | grep -qiE 'iic-osic|osic-tools'; then ok "IIC-OSIC-TOOLS docker image present (stock base fallback — pull ghcr.io/vibeic/vibeic-eda:latest for the fork enhancements)"
  else skip "docker present but no EDA image found (pull ghcr.io/vibeic/vibeic-eda:latest — or clone github.com/vibeic/vibeic-eda to build from source — or pull IIC-OSIC-TOOLS, for Phase 3 PnR/analog)"; fi
else skip "docker not found (only functional pass@1 via iverilog is verified here)"; fi

# ── Phase 1 — plugin structure ──────────────────────────────────────────────
hdr "Phase 1 — plugin structure"
for f in \
  "$REPO/vibe-ic-marketplace/.claude-plugin/marketplace.json" \
  "$PLUGIN/.claude-plugin/plugin.json" \
  "$PLUGIN/.mcp.json" \
  "$PLUGIN/flow/phase1_phase2_phase3.yaml" \
  "$PLUGIN/benchmark/BENCHMARK_REGISTRY.json" \
  "$PLUGIN/agents/ic_expert_db/ic_expert_db.json" ; do
  [ -f "$f" ] && ok "present: ${f#$REPO/}" || bad "MISSING: ${f#$REPO/}"
done
VER="$(python3 -c "import json;print(json.load(open('$PLUGIN/.claude-plugin/plugin.json'))['version'])" 2>/dev/null)"
[ -n "$VER" ] && ok "plugin version = $VER" || bad "cannot read plugin version"

# ── Phase 2 — plugin self-checks ────────────────────────────────────────────
hdr "Phase 2 — plugin self-checks"
run_check() { # <label> <cmd...>
  local label="$1"; shift
  if "$@" >/tmp/vcp_$$.log 2>&1; then ok "$label"; else bad "$label — see output:"; sed 's/^/      /' /tmp/vcp_$$.log | tail -4; fi
}
run_check "flow guide map loads (structural gates registered)" python3 "$PLUGIN/programs/flow_compliance_check.py" --list-structural-gates
run_check "ic_expert_db_consistency_check"                 python3 "$PLUGIN/programs/ic_expert_db_consistency_check.py"
run_check "source_chip_agnostic_check"                     python3 "$PLUGIN/programs/source_chip_agnostic_check.py" "$PLUGIN"
if [ -d "$PLUGIN/mcp-eda/node_modules" ]; then
  run_check "MCP server import (Docker↔plugin wire)"       node -e "import('$PLUGIN/mcp-eda/src/index.js').then(()=>process.exit(0)).catch(e=>{console.error(e.message);process.exit(1)})"
else
  skip "MCP import — run 'npm install' in mcp-eda/ first (node_modules absent)"
fi

# ── Phase 3 — benchmark reproduce ───────────────────────────────────────────
hdr "Phase 3 — benchmark reproduce (deterministic re-score of committed samples)"
# reproduce <name> <scorer> <run-dir> <dataset-env-var> <expected pass/total>
reproduce() {
  local name="$1" scorer="$2" run="$3" dsvar="$4" expect="$5"
  local ds="${!dsvar:-}"
  if [ -z "$ds" ] || [ ! -d "$ds" ]; then skip "$name — set $dsvar=<dataset path> to reproduce (expected $expect)"; return; fi
  if [ ! -f "$scorer" ] || [ ! -d "$run/samples" ]; then bad "$name — scorer or committed samples missing"; return; fi
  local out got
  out="$(python3 "$scorer" --run "$run" --dataset "$ds" 2>&1)"
  got="$(echo "$out" | grep -oE 'pass@1 = [0-9]+/[0-9]+' | head -1 | grep -oE '[0-9]+/[0-9]+')"
  if [ "$got" = "$expect" ]; then ok "$name reproduced $got (== verified)"
  else bad "$name got '$got' but verified is '$expect'"; echo "$out" | tail -2 | sed 's/^/      /'; fi
}
reproduce "RTLLM v2.0 (committed converged samples)" \
  "$EVAL/rtllm/score_rtllm.py" "$EVAL/rtllm/run_v1.3.26" RTLLM_DATASET "44/50"
reproduce "VerilogEval-v2 (blind samples)" \
  "$EVAL/verilogeval_v2/score_verilogeval.py" "$EVAL/verilogeval_v2/run_blind_v1.3.27" VEV2_DATASET "153/156"
reproduce "VerilogEval-Human (blind samples)" \
  "$EVAL/verilogeval_human/score_verilogeval.py" "$EVAL/verilogeval_human/run_fresh_v1.3.26_blind" VEHUMAN_DATASET "153/156"

# NOTE: the numbers above are a DETERMINISTIC re-score of committed samples — it
# proves the tools+samples+scorer reproduce the published number bit-for-bit. The
# stronger claim (a fresh §4.05 Benchmark-Agent blind run on Opus 4.8 reaches the
# same score in one round) requires live agents (the agent-driven path) — it
# cannot run inside this shell gate.

# ── Summary ─────────────────────────────────────────────────────────────────
hdr "Summary"
echo "  PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
rm -f /tmp/vcp_$$.log
if [ "$FAIL" -gt 0 ]; then echo "  VERDICT: NOT READY ($FAIL check(s) failed)"; exit 1; fi
echo "  VERDICT: READY (no failures; $SKIP skipped — provide dataset env vars / docker to cover them)"; exit 0
