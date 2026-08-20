#!/usr/bin/env bash
arm="${GATEKEEPER_VERIFY_ARM:-?}"
start=$(date +%s.%N)
sleep "${ARM_DWELL:-0}"
[ -n "${ARM_PROBE_DIR:-}" ] && printf '%s %s\n' "$start" "$(date +%s.%N)" > "$ARM_PROBE_DIR/$arm"
[ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] && python3 tools/stub_hygiene_record.py "$GATEKEEPER_HYGIENE_REPORT"
echo '=== gatekeeper landing gates — base=stub ==='
if [ "$arm" = A2 ]; then
  echo "  ${ARM_A2_RANGE_LINE:-SKIP  range is empty — nothing new to land}"
  echo "  ${ARM_A2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"
else
  echo '  SKIP  range is empty — nothing new to land'
  echo "  ${ARM_B2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"
fi
echo '  PASS  worktree carries no uncommitted change'
if [ -n "${ARM_GATE_FAIL:-}" ]; then
  echo '=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==='
  exit 1
fi
echo '=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==='
exit 0
