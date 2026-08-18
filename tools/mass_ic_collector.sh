#!/bin/bash
# Mass IC Document Collector — downloads ALL available datasheets
# Runs in background, status monitor checks hourly

PDF_DIR="~/ic_documents/datasheets"
LOG="~/ic_documents/logs/mass_collect.log"
STATUS="~/ic_documents/logs/status.txt"
mkdir -p "$PDF_DIR" "$(dirname $LOG)"

echo "=== Mass IC Collection Started: $(date) ===" > "$LOG"
echo "0" > "$STATUS"

download() {
  local NAME="$1" URL="$2"
  if [ -f "$PDF_DIR/${NAME}.pdf" ] && [ -s "$PDF_DIR/${NAME}.pdf" ]; then
    return 0
  fi
  wget -q --no-check-certificate --timeout=15 --tries=2 -O "$PDF_DIR/${NAME}.pdf" "$URL" 2>/dev/null
  if [ -s "$PDF_DIR/${NAME}.pdf" ]; then
    file "$PDF_DIR/${NAME}.pdf" | grep -q PDF
    if [ $? -eq 0 ]; then
      echo "$(date +%H:%M:%S) ✅ $NAME" >> "$LOG"
      return 0
    fi
  fi
  rm -f "$PDF_DIR/${NAME}.pdf"
  echo "$(date +%H:%M:%S) ❌ $NAME" >> "$LOG"
  return 1
}

update_status() {
  local COUNT=$(ls "$PDF_DIR"/*.pdf 2>/dev/null | wc -l)
  local SIZE=$(du -sh "$PDF_DIR" 2>/dev/null | cut -f1)
  echo "$COUNT files, $SIZE, $(date)" > "$STATUS"
}

# ============================================================
# TEXAS INSTRUMENTS — Largest collection (~500 ICs)
# ============================================================
echo "--- TI: Logic ---" >> "$LOG"
for IC in sn74hc00 sn74hc02 sn74hc04 sn74hc08 sn74hc10 sn74hc14 sn74hc20 sn74hc27 sn74hc30 sn74hc32 sn74hc74 sn74hc86 sn74hc125 sn74hc126 sn74hc132 sn74hc138 sn74hc139 sn74hc148 sn74hc151 sn74hc153 sn74hc154 sn74hc157 sn74hc158 sn74hc160 sn74hc161 sn74hc162 sn74hc163 sn74hc164 sn74hc165 sn74hc166 sn74hc173 sn74hc174 sn74hc175 sn74hc191 sn74hc192 sn74hc193 sn74hc194 sn74hc195 sn74hc240 sn74hc244 sn74hc245 sn74hc251 sn74hc257 sn74hc259 sn74hc273 sn74hc283 sn74hc299 sn74hc373 sn74hc374 sn74hc390 sn74hc393 sn74hc541 sn74hc573 sn74hc574 sn74hc590 sn74hc595 sn74hc688; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  # Limit parallel downloads
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: LVC/AHC Logic ---" >> "$LOG"
for IC in sn74lvc1g00 sn74lvc1g02 sn74lvc1g04 sn74lvc1g08 sn74lvc1g14 sn74lvc1g32 sn74lvc1g125 sn74lvc1g126 sn74lvc2g00 sn74lvc2g02 sn74lvc2g04 sn74lvc2g07 sn74lvc2g08 sn74lvc2g14 sn74lvc2g17 sn74lvc2g32 sn74lvc2g34 sn74lvc2g66 sn74lvc2g125 sn74lvc2g126 sn74lvc2g241 sn74lvc2g66 sn74ahc1g00 sn74ahc1g02 sn74ahc1g04 sn74ahc1g08 sn74ahc1g14 sn74ahc1g32 sn74ahc1g125 sn74ahc1g126; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: CMOS 4000 series ---" >> "$LOG"
for IC in cd4001b cd4002b cd4007ub cd4011b cd4012b cd4013b cd4015b cd4016b cd4017b cd4018b cd4019b cd4020b cd4021b cd4022b cd4023b cd4024b cd4025b cd4026b cd4027b cd4028b cd4029b cd4030b cd4033b cd4034b cd4040b cd4041ub cd4042b cd4043b cd4044b cd4046b cd4047b cd4049ub cd4050b cd4051b cd4052b cd4053b cd4060b cd4063b cd4066b cd4067b cd4068b cd4069ub cd4070b cd4071b cd4072b cd4073b cd4075b cd4076b cd4078b cd4081b cd4082b cd4085b cd4086b cd4093b cd4094b cd4098b cd4099b; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: Op-Amps ---" >> "$LOG"
for IC in lm358 lm324 lm386 lmv321 lmv324 lmv358 opa134 opa2134 opa340 opa350 opa365 opa1612 opa1632 opa1678 opa2277 opa2340 opa2350 opa333 opa335 opa336 opa337 opa338 opa376 opa378 opa380 opa2376 ina128 ina129 ina219 ina226 ina228 ina230 ina240 ina250 ina260 ina270 ina281 ina290 ina300; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: Voltage Regulators ---" >> "$LOG"
for IC in lm1117 lm317 lm340 lm7805 lm7812 lm7815 lm7905 lm337 lm2596 lm2576 lm2575 lm2596adj tps7a05 tps7a20 tps7a30 tps7a47 tps7a49 tps62160 tps62162 tps62170 tps62172 tps62200 tps62203 tps62230 tps62240 tps62840 tps61099 tps5430 tps54060 tps54160 tps54260 tps54360 tps54531 tps54540 tps56200 tps56637 tps65132 lmr14006 lmr14010 lmr14020 lmr14030 lmr33610 lmr33620 lmr33630 lmr36006 lmr36010 lmr36015 lm5164; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: ADC/DAC ---" >> "$LOG"
for IC in ads1015 ads1115 ads1118 ads1220 ads1232 ads1234 ads1235 ads1241 ads1242 ads1243 ads1256 ads1261 ads1262 ads1263 ads7042 ads7050 ads7056 ads7066 ads8320 ads8325 ads8330 ads8341 ads8344 ads8345 ads8688 ads131m08 dac7311 dac7551 dac7571 dac7574 dac8311 dac8411 dac8552 dac8554 dac8571 dac8574 dac80501 dac80502; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: Interface ---" >> "$LOG"
for IC in sn65hvd230 sn65hvd231 sn65hvd232 sn65hvd233 sn65hvd234 sn65hvd235 sn65hvd251 sn65hvd255 sn65hvd256 sn65hvd257 tca9548a tca6408a tca6416a tca6424a tca9534 tca9535 tca9539 tca9555 pca9306 pca9517 txs0102 txs0104e txs0108e txb0104 txb0106 txb0108 max232 max3232 max485 max488 max490 max3485 max3488 max3490; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: Motor/LED/Sensor ---" >> "$LOG"
for IC in drv8825 drv8833 drv8835 drv8837 drv8838 drv8840 drv8841 drv8842 drv8870 drv8871 drv8872 drv8873 drv2605 drv2605l tlc5940 tlc5947 tlc5948 tlc5955 tlc59711 lp5012 lp5036 hdc1080 hdc2010 opt3001 opt3002 tmp102 tmp103 tmp112 tmp116 tmp117 tmp1075 lm35 lm75b lm75; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

echo "--- TI: Timers/Comparators/References ---" >> "$LOG"
for IC in ne555 lm555 tlc555 lmc555 tl431 tl432 lm4040 ref2033 ref3012 ref3025 ref3033 ref5020 ref5025 ref5030 ref5040 ref5045 ref5050 lm393 lm339 lm311 tlv3501 tlv3502 tlv7031 tlv7041 tlv7211; do
  NAME=$(echo $IC | tr '[:lower:]' '[:upper:]')
  download "$NAME" "https://www.ti.com/lit/ds/symlink/${IC}.pdf" &
  [ $(jobs -r | wc -l) -ge 10 ] && wait -n
done
wait; update_status

# ============================================================
# NXP
# ============================================================
echo "--- NXP ---" >> "$LOG"
for PAIR in "PCA9685:PCA9685" "PCA9548A:PCA9548A" "PCF8574:PCF8574" "PCF8575:PCF8575" "PCF8591:PCF8591" "PCA9306:PCA9306" "SC16IS750:SC16IS740_750_760" "LM75B:LM75B"; do
  NAME="${PAIR%%:*}"
  SLUG="${PAIR##*:}"
  download "$NAME" "https://www.nxp.com/docs/en/data-sheet/${SLUG}.pdf" &
done
wait; update_status

# ============================================================
# MICROCHIP
# ============================================================
echo "--- Microchip ---" >> "$LOG"
declare -A MCHP_URLS=(
  ["PIC16F1459"]="https://ww1.microchip.com/downloads/en/DeviceDoc/40001639B.pdf"
  ["MCP2515"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2515-Stand-Alone-CAN-Controller-with-SPI-20001801J.pdf"
  ["MCP2221A"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2221A-Data-Sheet-20005565E.pdf"
  ["MCP23017"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP23017-Data-Sheet-DS20001952C.pdf"
  ["MCP23S17"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP23S17-Data-Sheet-DS20001952C.pdf"
  ["MCP4728"]="https://ww1.microchip.com/downloads/en/DeviceDoc/22187E.pdf"
  ["MCP9808"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP9808-0.5C-Maximum-Accuracy-Digital-Temperature-Sensor-Data-Sheet-DS20005095B.pdf"
  ["MCP73831"]="https://ww1.microchip.com/downloads/en/DeviceDoc/MCP73831-Family-Data-Sheet-DS20001984H.pdf"
  ["MCP1826"]="https://ww1.microchip.com/downloads/en/DeviceDoc/22057b.pdf"
  ["ATECC608A"]="https://ww1.microchip.com/downloads/en/DeviceDoc/ATECC608A-CryptoAuthentication-Device-Summary-Data-Sheet-DS40001977B.pdf"
  ["PIC18F46K22"]="https://ww1.microchip.com/downloads/en/DeviceDoc/PIC18(L)F2X-4XK22-Data-Sheet-40001412H.pdf"
  ["PIC32MX250"]="https://ww1.microchip.com/downloads/en/DeviceDoc/PIC32MX1XX-2XX-28-36-44-PIN-DS60001168L.pdf"
  ["SAMD21"]="https://ww1.microchip.com/downloads/en/DeviceDoc/SAM-D21DA1-Family-Data-Sheet-DS40001882G.pdf"
)
for NAME in "${!MCHP_URLS[@]}"; do
  download "$NAME" "${MCHP_URLS[$NAME]}" &
  [ $(jobs -r | wc -l) -ge 5 ] && wait -n
done
wait; update_status

# ============================================================
# ANALOG DEVICES / MAXIM
# ============================================================
echo "--- Analog Devices ---" >> "$LOG"
for PAIR in "DS18B20:DS18B20" "DS18S20:DS18S20" "DS1307:DS1307" "DS3231:DS3231" "MAX31855:MAX31855" "MAX31856:MAX31856" "MAX6675:MAX6675" "MAX7219:MAX7219" "MAX7221:MAX7221" "AD9833:AD9833" "AD9850:AD9850" "AD8232:AD8232" "ADXL345:ADXL345" "AD7124:AD7124-8"; do
  NAME="${PAIR%%:*}"
  SLUG="${PAIR##*:}"
  download "$NAME" "https://www.analog.com/media/en/technical-documentation/data-sheets/${SLUG}.pdf" &
  [ $(jobs -r | wc -l) -ge 5 ] && wait -n
done
wait; update_status

# ============================================================
# ST MICROELECTRONICS
# ============================================================
echo "--- STMicro ---" >> "$LOG"
for PAIR in "STM32F103:stm32f103c8" "STM32F411:stm32f411ce" "STM32F401:stm32f401cc" "STM32L073:stm32l073rz" "STM32G031:stm32g031c8" "STM32H743:stm32h743vi" "L293D:l293d" "L298N:l298" "VL53L0X:vl53l0x" "VL53L1X:vl53l1x" "LSM6DSO:lsm6dso" "LIS3DH:lis3dh" "HTS221:hts221"; do
  NAME="${PAIR%%:*}"
  SLUG="${PAIR##*:}"
  download "$NAME" "https://www.st.com/resource/en/datasheet/${SLUG}.pdf" &
  [ $(jobs -r | wc -l) -ge 5 ] && wait -n
done
wait; update_status

# ============================================================
# OTHER MANUFACTURERS
# ============================================================
echo "--- Others ---" >> "$LOG"
# Espressif
download "ESP32" "https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf" &
download "ESP32-S3" "https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf" &
download "ESP32-C3" "https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf" &
download "ESP8266" "https://www.espressif.com/sites/default/files/documentation/0a-esp8266ex_datasheet_en.pdf" &

# Raspberry Pi
download "RP2040" "https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf" &
download "RP2350" "https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf" &

# Nordic
download "nRF52840" "https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.7.pdf" &
download "nRF52832" "https://infocenter.nordicsemi.com/pdf/nRF52832_PS_v1.8.pdf" &

# Winbond
download "W25Q128" "https://www.winbond.com/resource-files/w25q128jv%20spi%20revc%2011162016.pdf" &
download "W25Q256" "https://www.winbond.com/resource-files/w25q256jv%20spi%20revg%2008032017.pdf" &
download "W25Q32" "https://www.winbond.com/resource-files/w25q32jv%20spi%20revg%2006032016.pdf" &
download "W25Q64" "https://www.winbond.com/resource-files/w25q64jv%20spi%20revj%2001042023.pdf" &

# FTDI
download "FT232R" "https://ftdichip.com/wp-content/uploads/2020/08/DS_FT232R.pdf" &
download "FT2232H" "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT2232H.pdf" &
download "FT232H" "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT232H.pdf" &
download "FT4232H" "https://ftdichip.com/wp-content/uploads/2020/07/DS_FT4232H.pdf" &

# Bosch
download "BME280" "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf" &
download "BMP280" "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf" &
download "BMI160" "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi160-ds000.pdf" &

# Silicon Labs
download "CP2102" "https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf" &
download "CP2104" "https://www.silabs.com/documents/public/data-sheets/cp2104.pdf" &
download "SI7021" "https://www.silabs.com/documents/public/data-sheets/Si7021-A20.pdf" &

wait; update_status

# ============================================================
# FINAL: Extract all metadata and import to PostgreSQL
# ============================================================
echo "" >> "$LOG"
echo "--- Extracting metadata & importing to PostgreSQL ---" >> "$LOG"
cd ~/AI_IC_design
python3 tools/extract_and_import.py >> "$LOG" 2>&1

# Final status
TOTAL=$(ls "$PDF_DIR"/*.pdf 2>/dev/null | wc -l)
SIZE=$(du -sh "$PDF_DIR" 2>/dev/null | cut -f1)
DB_COUNT=$(psql -U reyerchu -d vibe_ic -t -c "SELECT COUNT(*) FROM ics" 2>/dev/null | tr -d ' ')

echo "" >> "$LOG"
echo "============================================" >> "$LOG"
echo "COLLECTION COMPLETE: $(date)" >> "$LOG"
echo "PDFs: $TOTAL ($SIZE)" >> "$LOG"
echo "ICs in DB: $DB_COUNT" >> "$LOG"
echo "============================================" >> "$LOG"

echo "DONE $TOTAL $SIZE $DB_COUNT $(date)" > "$STATUS"
