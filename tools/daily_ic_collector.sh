#!/bin/bash
# Daily IC Document Collector — runs at 5am CST (UTC+8)
# Searches for new IC datasheets, extracts metadata, imports to PostgreSQL

LOG_DIR="~/ic_documents/logs"
PDF_DIR="~/ic_documents/datasheets"
JSON_DIR="~/ic_documents/datasheets_metadata"
TOOL_DIR="~/AI_IC_design/tools"

mkdir -p "$LOG_DIR" "$PDF_DIR" "$JSON_DIR"

DATE=$(date +%Y-%m-%d)
LOG="$LOG_DIR/collect_${DATE}.log"

echo "=== IC Document Collection — $DATE ===" > "$LOG"
echo "Start: $(date)" >> "$LOG"

# --- 1. Download new TI datasheets (popular ICs not yet collected) ---
echo "" >> "$LOG"
echo "--- Downloading new datasheets ---" >> "$LOG"

NEW_TI_ICS=(
  "SN74AHC1G08:sn74ahc1g08" "SN74LVC1G04:sn74lvc1g04" "SN74LVC2G14:sn74lvc2g14"
  "TPS7A05:tps7a05" "TPS7A20:tps7a20" "TPS62840:tps62840"
  "OPT3001:opt3001" "HDC1080:hdc1080" "BQ25895:bq25895"
  "TXS0108E:txs0108e" "SN74CB3Q3384:sn74cb3q3384"
  "LM5164:lm5164" "TPS5430:tps5430" "UCC28C44:ucc28c44"
  "DRV2605:drv2605" "INA226:ina226" "TPS61099:tps61099"
  "LMR14006:lmr14006" "ADS1256:ads1256" "ADS131M08:ads131m08"
)

DOWNLOADED=0
for IC_PAIR in "${NEW_TI_ICS[@]}"; do
  NAME="${IC_PAIR%%:*}"
  SLUG="${IC_PAIR##*:}"
  if [ ! -f "$PDF_DIR/${NAME}.pdf" ]; then
    wget -q --no-check-certificate -O "$PDF_DIR/${NAME}.pdf" \
      "https://www.ti.com/lit/ds/symlink/${SLUG}.pdf" 2>/dev/null
    if [ -s "$PDF_DIR/${NAME}.pdf" ]; then
      echo "  Downloaded: ${NAME}.pdf" >> "$LOG"
      DOWNLOADED=$((DOWNLOADED+1))
    else
      rm -f "$PDF_DIR/${NAME}.pdf"
    fi
  fi
done

# Microchip ICs
NEW_MCHP_ICS=(
  "PIC16F1459:https://ww1.microchip.com/downloads/en/DeviceDoc/40001639B.pdf"
  "ATECC608A:https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608A-CryptoAuthentication-Device-Summary-Data-Sheet-DS40001977B.pdf"
  "MCP2515:https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2515-Stand-Alone-CAN-Controller-with-SPI-20001801J.pdf"
  "MCP2221A:https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2221A-Data-Sheet-20005565E.pdf"
)

for IC_PAIR in "${NEW_MCHP_ICS[@]}"; do
  NAME="${IC_PAIR%%:*}"
  URL="${IC_PAIR##*:}"
  if [ ! -f "$PDF_DIR/${NAME}.pdf" ]; then
    wget -q --no-check-certificate -O "$PDF_DIR/${NAME}.pdf" "$URL" 2>/dev/null
    if [ -s "$PDF_DIR/${NAME}.pdf" ]; then
      echo "  Downloaded: ${NAME}.pdf" >> "$LOG"
      DOWNLOADED=$((DOWNLOADED+1))
    else
      rm -f "$PDF_DIR/${NAME}.pdf"
    fi
  fi
done

echo "New downloads: $DOWNLOADED" >> "$LOG"

# --- 2. Extract metadata from new PDFs and import to PostgreSQL ---
echo "" >> "$LOG"
echo "--- Extracting metadata & importing to PostgreSQL ---" >> "$LOG"

cd ~/AI_IC_design
IMPORT_RESULT=$(python3 "$TOOL_DIR/extract_and_import.py" 2>&1)
echo "$IMPORT_RESULT" >> "$LOG"

# --- 3. Report ---
echo "" >> "$LOG"
TOTAL_PDFS=$(ls "$PDF_DIR"/*.pdf 2>/dev/null | wc -l)
TOTAL_JSONS=$(ls "$JSON_DIR"/*.json 2>/dev/null | wc -l)
TOTAL_DB=$(psql -U reyerchu -d vibe_ic -t -c "SELECT COUNT(*) FROM ics" 2>/dev/null | tr -d ' ')

echo "=== Summary ===" >> "$LOG"
echo "PDFs on disk: $TOTAL_PDFS" >> "$LOG"
echo "JSON metadata: $TOTAL_JSONS" >> "$LOG"
echo "ICs in PostgreSQL: $TOTAL_DB" >> "$LOG"
echo "End: $(date)" >> "$LOG"

echo "Daily IC collection complete. Log: $LOG"
