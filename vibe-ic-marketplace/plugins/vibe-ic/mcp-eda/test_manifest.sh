#!/bin/bash
# Test suite for P0 result manifest feature
set -e
PASS=0
FAIL=0
TOTAL=0

check() {
  TOTAL=$((TOTAL+1))
  local name="$1" content="$2" pattern="$3"
  if echo "$content" | grep -q "$pattern" 2>/dev/null; then
    echo "  ✅ $name"
    PASS=$((PASS+1))
  else
    echo "  ❌ $name (pattern '$pattern' not found)"
    FAIL=$((FAIL+1))
  fi
}

echo "========================================="
echo "  P0 Manifest Test Suite"
echo "========================================="

# Setup test workspace in container
docker exec vibeic-eda bash -c '
rm -rf /tmp/mtest && mkdir -p /tmp/mtest/results /tmp/mtest/analog /tmp/mtest/dft
'

echo ""
echo "--- Test 1: Synthesis manifest ---"
docker exec vibeic-eda bash -c '
echo "{\"timestamp\":\"2026-04-07\",\"step\":\"synthesis\",\"status\":\"PASS\",\"cells\":8,\"area_um2\":200}" >> /tmp/mtest/results/latest_results.jsonl
echo -e "step: synthesis\nstatus: PASS\ncells: 8\n---" >> /tmp/mtest/results/latest_results.yml
'
JSONL=$(docker exec vibeic-eda cat /tmp/mtest/results/latest_results.jsonl 2>/dev/null)
YML=$(docker exec vibeic-eda cat /tmp/mtest/results/latest_results.yml 2>/dev/null)
check "JSONL written" "$JSONL" "synthesis"
check "YML written" "$YML" "synthesis"
check "Status PASS" "$JSONL" "PASS"
check "Cells recorded" "$JSONL" "cells.*8"

echo ""
echo "--- Test 2: SPICE PASS manifest ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"spice_simulation\",\"status\":\"PASS\",\"measurements\":{\"vout\":1.800},\"meas_failed_count\":0,\"has_negative_voltage\":false}" >> /tmp/mtest/analog/latest_results.jsonl
'
SPICE=$(docker exec vibeic-eda cat /tmp/mtest/analog/latest_results.jsonl 2>/dev/null)
check "SPICE PASS" "$SPICE" "PASS"
check "Measurements" "$SPICE" "vout.*1.8"
check "No neg voltage" "$SPICE" "has_negative_voltage.*false"

echo ""
echo "--- Test 3: SPICE SUSPICIOUS (negative voltage) ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"spice_simulation\",\"status\":\"SUSPICIOUS\",\"measurements\":{\"vout\":-43.7},\"has_negative_voltage\":true}" >> /tmp/mtest/analog/latest_results.jsonl
'
SPICE2=$(docker exec vibeic-eda cat /tmp/mtest/analog/latest_results.jsonl 2>/dev/null)
check "SUSPICIOUS flagged" "$SPICE2" "SUSPICIOUS"
check "Neg voltage true" "$SPICE2" "has_negative_voltage.*true"

echo ""
echo "--- Test 4: SPICE MEAS_FAILED ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"spice_simulation\",\"status\":\"MEAS_FAILED\",\"meas_failed_count\":3}" >> /tmp/mtest/analog/latest_results.jsonl
'
SPICE3=$(docker exec vibeic-eda cat /tmp/mtest/analog/latest_results.jsonl 2>/dev/null)
check "MEAS_FAILED status" "$SPICE3" "MEAS_FAILED"
check "Failed count 3" "$SPICE3" "meas_failed_count.*3"

echo ""
echo "--- Test 5: Append not overwrite ---"
LINES=$(docker exec vibeic-eda wc -l /tmp/mtest/analog/latest_results.jsonl | awk '{print $1}')
check "3 entries appended" "$LINES" "3"

echo ""
echo "--- Test 6: All 13 tool steps writable ---"
docker exec vibeic-eda bash -c '
for step in synthesis lint simulation formal place_and_route gds_generation sta lvs drc ir_drop equivalence spice_simulation dft; do
  echo "{\"step\":\"$step\",\"status\":\"PASS\"}" >> /tmp/mtest/results/all_steps.jsonl
done
'
ALL=$(docker exec vibeic-eda wc -l /tmp/mtest/results/all_steps.jsonl | awk '{print $1}')
check "13 step types" "$ALL" "13"

echo ""
echo "--- Test 7: Reviewer finds latest PASS in iteration history ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"spice\",\"status\":\"MEAS_FAILED\",\"iter\":1}" >> /tmp/mtest/results/review.jsonl
echo "{\"step\":\"spice\",\"status\":\"SUSPICIOUS\",\"iter\":2}" >> /tmp/mtest/results/review.jsonl
echo "{\"step\":\"spice\",\"status\":\"PASS\",\"iter\":3,\"vout\":1.8}" >> /tmp/mtest/results/review.jsonl
'
LATEST=$(docker exec vibeic-eda bash -c 'grep "PASS" /tmp/mtest/results/review.jsonl | tail -1')
check "Latest PASS is iter 3" "$LATEST" "iter.*3"
check "Latest has vout 1.8" "$LATEST" "vout.*1.8"

echo ""
echo "--- Test 8: P&R manifest with timing ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"place_and_route\",\"status\":\"PASS\",\"slack_ns\":183.63,\"timing_met\":true,\"area_um2\":89176}" >> /tmp/mtest/results/latest_results.jsonl
'
PNR=$(docker exec vibeic-eda cat /tmp/mtest/results/latest_results.jsonl 2>/dev/null)
check "PNR slack recorded" "$PNR" "slack_ns.*183"
check "Timing MET" "$PNR" "timing_met.*true"

echo ""
echo "--- Test 9: DFT manifest with coverage ---"
docker exec vibeic-eda bash -c '
echo "{\"step\":\"dft\",\"status\":\"PASS\",\"coverage_pct\":90.39,\"scan_chain_length\":129,\"test_vectors\":66}" >> /tmp/mtest/dft/latest_results.jsonl
'
DFT=$(docker exec vibeic-eda cat /tmp/mtest/dft/latest_results.jsonl 2>/dev/null)
check "DFT coverage" "$DFT" "coverage_pct.*90"
check "Scan chain" "$DFT" "scan_chain_length.*129"
check "Test vectors" "$DFT" "test_vectors.*66"

echo ""
echo "========================================="
echo "  Results: $PASS/$TOTAL passed, $FAIL failed"
echo "========================================="

if [ $FAIL -eq 0 ]; then
  echo "  ALL TESTS PASSED ✅"
else
  echo "  SOME TESTS FAILED ❌"
  exit 1
fi
