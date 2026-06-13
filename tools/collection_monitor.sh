#!/bin/bash
# Hourly monitor for mass IC collection — prints status until collector finishes
STATUS="~/ic_documents/logs/status.txt"
LOG="~/ic_documents/logs/mass_collect.log"
PDF_DIR="~/ic_documents/datasheets"

while true; do
  PDFS=$(ls "$PDF_DIR"/*.pdf 2>/dev/null | wc -l)
  SIZE=$(du -sh "$PDF_DIR" 2>/dev/null | cut -f1)
  DB=$(psql -U reyerchu -d vibe_ic -t -c "SELECT COUNT(*) FROM ics" 2>/dev/null | tr -d ' ')
  LAST_LOG=$(tail -1 "$LOG" 2>/dev/null)

  echo "[$(date '+%Y-%m-%d %H:%M')] PDFs: $PDFS ($SIZE) | DB: $DB ICs | Last: $LAST_LOG"

  # Check if collector finished
  if grep -q "^DONE" "$STATUS" 2>/dev/null; then
    echo ""
    echo "=== COLLECTION COMPLETE ==="
    cat "$STATUS"
    break
  fi

  sleep 3600  # Check every hour
done
