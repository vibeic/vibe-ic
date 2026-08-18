#!/bin/bash
# =============================================================================
# quartus_batch_compile.sh — Quartus Batch Compile for Vibe-IC 135-IC Campaign
# =============================================================================
#
# 用途：
#   針對 ic_projects_v2/ 中每顆 IC 的 RTL，自動建立 Quartus 專案、
#   產生 FPGA top wrapper、執行完整編譯流程，並收集結果。
#
# 使用方式：
#   bash tools/quartus_batch_compile.sh          # 編譯全部 IC
#   bash tools/quartus_batch_compile.sh 1 10     # 編譯 IC #1-10
#   bash tools/quartus_batch_compile.sh 5 5      # 只編譯 IC #5
#
# 輸出：
#   fpga_verification/de10_nano_tests/<ic>_test/  — 各 IC 的 Quartus 專案
#   quartus_batch_results.json                    — JSON 彙總結果
#   quartus_batch_dashboard.md                    — Markdown 看板
#
# 目標板：Terasic DE10-Nano (Cyclone V 5CSEBA6U23I7, 41,910 ALMs)
# Quartus 路徑：~/eda/quartus/quartus/bin/
# =============================================================================

set -o pipefail

# ===== 全域設定 =====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IC_DIR="$PROJECT_ROOT/ic_projects_v2"
FPGA_DIR="$PROJECT_ROOT/fpga_verification/de10_nano_tests"
COMMON_RTL="$PROJECT_ROOT/fpga_verification/common_rtl"
QUARTUS_BIN="~/eda/quartus/quartus/bin"
RESULTS_JSON="$PROJECT_ROOT/quartus_batch_results.json"
RESULTS_MD="$PROJECT_ROOT/quartus_batch_dashboard.md"
MAX_ALMS=41910  # Cyclone V 5CSEBA6U23I7 最大 ALM 數

# Quartus PATH
export PATH="$QUARTUS_BIN:$PATH"

# 起止範圍
START=${1:-1}
END=${2:-135}

# 時間戳
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# ===== 顏色輸出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ===== 暫存結果陣列 =====
declare -a RESULT_ENTRIES

# ===== 輔助函數 =====

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_pass()  { echo -e "${GREEN}[PASS]${NC}  $1"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $1"; }
log_skip()  { echo -e "${YELLOW}[SKIP]${NC}  $1"; }

# 從 RTL 中解析 module 名稱
get_module_name() {
    local sv_file="$1"
    grep -m1 '^module ' "$sv_file" | sed 's/module \+\([a-zA-Z_][a-zA-Z0-9_]*\).*/\1/'
}

# 判斷模組是否有 clk + rst_n（sequential）
has_clk_rst() {
    local sv_file="$1"
    grep -q 'input.*clk' "$sv_file" && grep -q 'input.*rst_n' "$sv_file"
}

# 判斷模組是否有 clk（任何時脈）但無 rst_n
has_clk_only() {
    local sv_file="$1"
    grep -q 'input.*clk' "$sv_file" && ! grep -q 'input.*rst_n' "$sv_file"
}

# 解析模組的所有 input/output 埠（回傳格式：direction name width）
parse_ports() {
    local sv_file="$1"
    local module_name="$2"
    python3 - "$sv_file" "$module_name" <<'PYEOF'
import re, sys

sv_file = sys.argv[1]
target_module = sys.argv[2]

with open(sv_file) as f:
    text = f.read()

# Find the target module declaration
pattern = rf'module\s+{re.escape(target_module)}\s*\((.*?)\);'
m = re.search(pattern, text, re.DOTALL)
if not m:
    sys.exit(1)

port_text = m.group(1)
# Remove comments
port_text = re.sub(r'//.*', '', port_text)

# Parse each port
for line in port_text.split('\n'):
    line = line.strip().rstrip(',')
    if not line:
        continue
    # Match: input/output [logic/wire] [signed] [width] name
    m2 = re.match(r'(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:signed\s+)?\[(\d+):(\d+)\]\s+(\w+)', line)
    if m2:
        direction = m2.group(1)
        hi = int(m2.group(2))
        lo = int(m2.group(3))
        name = m2.group(4)
        width = hi - lo + 1
        print(f"{direction} {name} {width}")
        continue
    m3 = re.match(r'(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:signed\s+)?(\w+)', line)
    if m3:
        direction = m3.group(1)
        name = m3.group(2)
        print(f"{direction} {name} 1")
PYEOF
}

# ===== 產生 FPGA Top Wrapper =====
generate_fpga_top() {
    local ic_num="$1"
    local ic_name="$2"
    local module_name="$3"
    local sv_file="$4"
    local test_dir="$5"
    local proj_name="${module_name}_fpga"
    local top_file="$test_dir/${proj_name}_top.sv"

    # 解析埠
    local ports
    ports=$(parse_ports "$sv_file" "$module_name")
    if [ -z "$ports" ]; then
        log_fail "IC #${ic_num} (${ic_name}): 無法解析模組埠"
        return 1
    fi

    # 判斷設計類型
    local is_sequential=0
    local has_clk_port=0
    local has_rst_port=0
    echo "$ports" | grep -q 'input clk ' && has_clk_port=1
    echo "$ports" | grep -q 'input CLK ' && has_clk_port=1
    echo "$ports" | grep -q 'input rst_n ' && has_rst_port=1
    echo "$ports" | grep -q 'input CLR_N ' && has_rst_port=1

    if [ "$has_clk_port" -eq 1 ]; then
        is_sequential=1
    fi

    # 產生 wrapper
    python3 - "$sv_file" "$module_name" "$top_file" "$proj_name" "$is_sequential" "$has_rst_port" <<'PYEOF'
import re, sys

sv_file = sys.argv[1]
module_name = sys.argv[2]
top_file = sys.argv[3]
proj_name = sys.argv[4]
is_sequential = int(sys.argv[5])
has_rst_port = int(sys.argv[6])

with open(sv_file) as f:
    text = f.read()

# Parse module ports
pattern = rf'module\s+{re.escape(module_name)}\s*\((.*?)\);'
m = re.search(pattern, text, re.DOTALL)
if not m:
    print(f"ERROR: Cannot find module {module_name}")
    sys.exit(1)

port_text = m.group(1)
port_text_clean = re.sub(r'//.*', '', port_text)

ports = []
for line in port_text_clean.split('\n'):
    line = line.strip().rstrip(',')
    if not line:
        continue
    m2 = re.match(r'(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:signed\s+)?\[(\d+):(\d+)\]\s+(\w+)', line)
    if m2:
        ports.append((m2.group(1), m2.group(4), int(m2.group(2)) - int(m2.group(3)) + 1))
        continue
    m3 = re.match(r'(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:signed\s+)?(\w+)', line)
    if m3:
        ports.append((m3.group(1), m3.group(2), 1))

# Classify ports
inputs = [(n, w) for d, n, w in ports if d == 'input']
outputs = [(n, w) for d, n, w in ports if d == 'output']
inouts = [(n, w) for d, n, w in ports if d == 'inout']

# Identify clock and reset ports
clk_names = [n for n, w in inputs if n.lower() in ('clk', 'clock', 'clk1', 'clk2', 'clk_32k', 'xtal_clk', 'spi_sclk')]
rst_names = [n for n, w in inputs if n.lower() in ('rst_n', 'reset_n', 'clr_n', 'reset_ext_n')]

# Separate "functional" inputs (not clk/rst)
func_inputs = [(n, w) for n, w in inputs if n not in clk_names and n not in rst_names]
total_output_bits = sum(w for n, w in outputs)
total_func_input_bits = sum(w for n, w in func_inputs)

# Build the top wrapper
lines = []
lines.append(f'// ============================================================================')
lines.append(f'// {module_name.upper()} FPGA Test Top — DE10-Nano (Cyclone V 5CSEBA6U23I7)')
lines.append(f'// ============================================================================')
lines.append(f'// Auto-generated by quartus_batch_compile.sh')
lines.append(f'// Simple loopback wrapper: inputs from SW/GPIO, outputs to LEDR/GPIO')
lines.append(f'//')
lines.append(f'// Connections:')
lines.append(f'//   CLOCK_50  -> system clock')
lines.append(f'//   KEY[0]    -> reset (active low)')
lines.append(f'//   SW[3:0]   -> manual inputs')
lines.append(f'//   LEDR[7:0] -> status/outputs')
lines.append(f'// ============================================================================')
lines.append(f'')
lines.append(f'module {proj_name}_top (')
lines.append(f'    input  logic        CLOCK_50,')
lines.append(f'    input  logic [1:0]  KEY,')
lines.append(f'    input  logic [3:0]  SW,')
lines.append(f'    output logic [7:0]  LEDR,')
lines.append(f'    inout  logic [35:0] GPIO_0')
lines.append(f');')
lines.append(f'')
lines.append(f'    // ---- Reset ----')
lines.append(f'    logic rst_n;')
lines.append(f'    assign rst_n = KEY[0];')
lines.append(f'')

# Declare DUT signals
lines.append(f'    // ---- DUT Signals ----')
for d, n, w in ports:
    wstr = f'[{w-1}:0] ' if w > 1 else '       '
    lines.append(f'    logic {wstr}dut_{n};')
lines.append(f'')

# Connect inputs
lines.append(f'    // ---- Input Connections ----')
gpio_in_idx = 2  # GPIO_0[0]=TX, GPIO_0[1]=RX reserved
sw_idx = 0

for n, w in inputs:
    if n.lower() in ('clk', 'clock'):
        lines.append(f'    assign dut_{n} = CLOCK_50;')
    elif n.lower() in ('clk1', 'clk2'):
        lines.append(f'    assign dut_{n} = CLOCK_50;')
    elif n.lower() == 'clk_32k':
        # Generate 32kHz from 50MHz (divide by ~1526)
        lines.append(f'    // 32kHz from 50MHz divider')
        lines.append(f'    logic [10:0] div_32k;')
        lines.append(f'    logic clk_32k_div;')
        lines.append(f'    always_ff @(posedge CLOCK_50) begin')
        lines.append(f'        if (!rst_n) begin div_32k <= 0; clk_32k_div <= 0; end')
        lines.append(f'        else if (div_32k >= 762) begin div_32k <= 0; clk_32k_div <= ~clk_32k_div; end')
        lines.append(f'        else div_32k <= div_32k + 1;')
        lines.append(f'    end')
        lines.append(f'    assign dut_{n} = clk_32k_div;')
    elif n.lower() == 'xtal_clk':
        lines.append(f'    assign dut_{n} = CLOCK_50;  // Use 50MHz as xtal')
    elif n.lower() == 'spi_sclk':
        lines.append(f'    assign dut_{n} = 1\'b0;  // SPI clock idle')
    elif n.lower() in ('rst_n', 'reset_n', 'reset_ext_n'):
        lines.append(f'    assign dut_{n} = rst_n;')
    elif n.lower() == 'clr_n':
        lines.append(f'    assign dut_{n} = rst_n;')
    elif n.lower() in ('scl_i',):
        lines.append(f'    assign dut_{n} = 1\'b1;  // I2C SCL idle high')
    elif n.lower() in ('sda_i',):
        lines.append(f'    assign dut_{n} = 1\'b1;  // I2C SDA idle high')
    elif n.lower() in ('uart_rx',):
        lines.append(f'    assign dut_{n} = 1\'b1;  // UART RX idle high')
    elif n.lower() in ('cts_n',):
        lines.append(f'    assign dut_{n} = 1\'b0;  // CTS asserted')
    elif n.lower() in ('wp',):
        lines.append(f'    assign dut_{n} = 1\'b0;  // Write protect off')
    elif n.lower() in ('vbat_mode',):
        lines.append(f'    assign dut_{n} = 1\'b0;  // Normal mode')
    elif n.lower() in ('oe_n',):
        lines.append(f'    assign dut_{n} = 1\'b0;  // Output enabled')
    elif n.lower() in ('i2c_spi_n',):
        lines.append(f'    assign dut_{n} = 1\'b1;  // I2C mode')
    elif n.lower() in ('spi_cs_n',):
        lines.append(f'    assign dut_{n} = 1\'b1;  // SPI deselected')
    elif n.lower() in ('spi_mosi',):
        lines.append(f'    assign dut_{n} = 1\'b0;  // SPI MOSI idle')
    elif w == 1 and sw_idx < 4:
        lines.append(f'    assign dut_{n} = SW[{sw_idx}];')
        sw_idx += 1
    elif gpio_in_idx + w - 1 <= 35:
        if w == 1:
            lines.append(f'    assign dut_{n} = GPIO_0[{gpio_in_idx}];')
        else:
            lines.append(f'    assign dut_{n} = GPIO_0[{gpio_in_idx + w - 1}:{gpio_in_idx}];')
        gpio_in_idx += w
    else:
        # Tie off remaining inputs
        lines.append(f'    assign dut_{n} = {w}\'d0;  // Tied off (not enough pins)')

lines.append(f'')

# DUT instantiation
lines.append(f'    // ---- DUT Instance ----')
lines.append(f'    {module_name} u_dut (')
port_conns = []
for d, n, w in ports:
    port_conns.append(f'        .{n:<20s}(dut_{n})')
lines.append(',\n'.join(port_conns))
lines.append(f'    );')
lines.append(f'')

# Connect outputs to LEDs (first 8 bits)
lines.append(f'    // ---- Output to LEDs ----')
out_bit = 0
led_assigns = []
for n, w in outputs:
    for b in range(w):
        if out_bit < 8:
            if w == 1:
                led_assigns.append(f'    assign LEDR[{out_bit}] = dut_{n};')
            else:
                led_assigns.append(f'    assign LEDR[{out_bit}] = dut_{n}[{b}];')
            out_bit += 1

if led_assigns:
    lines.extend(led_assigns)
else:
    lines.append(f'    assign LEDR = 8\'d0;')

# Fill remaining LEDs
for i in range(out_bit, 8):
    lines.append(f'    assign LEDR[{i}] = 1\'b0;')

lines.append(f'')

# Connect remaining outputs to GPIO
gpio_out_idx = gpio_in_idx + 2  # skip some
lines.append(f'    // ---- Remaining outputs to GPIO (active monitoring) ----')
for n, w in outputs:
    if gpio_out_idx + w - 1 <= 35:
        if w == 1:
            lines.append(f'    assign GPIO_0[{gpio_out_idx}] = dut_{n};')
        else:
            lines.append(f'    // {n}[{w-1}:0] -> GPIO_0[{gpio_out_idx+w-1}:{gpio_out_idx}]')
        gpio_out_idx += w

lines.append(f'')
lines.append(f'endmodule')

with open(top_file, 'w') as f:
    f.write('\n'.join(lines) + '\n')

print(f"Generated: {top_file}")
PYEOF
}

# ===== 產生 QPF =====
generate_qpf() {
    local test_dir="$1"
    local proj_name="$2"

    cat > "$test_dir/${proj_name}.qpf" <<EOF
QUARTUS_VERSION = "25.1"
DATE = "$(date '+%Y-%m-%d')"
PROJECT_REVISION = "${proj_name}"
EOF
}

# ===== 產生 QSF =====
generate_qsf() {
    local test_dir="$1"
    local proj_name="$2"
    local module_name="$3"
    local sv_file="$4"
    local ic_dir="$5"

    # 計算相對路徑：從 test_dir 到 sv_file
    local rtl_rel
    rtl_rel=$(python3 -c "import os.path; print(os.path.relpath('$sv_file', '$test_dir'))")
    local common_uart_tx
    common_uart_tx=$(python3 -c "import os.path; print(os.path.relpath('$COMMON_RTL/uart_tx.sv', '$test_dir'))")
    local common_uart_rx
    common_uart_rx=$(python3 -c "import os.path; print(os.path.relpath('$COMMON_RTL/uart_rx.sv', '$test_dir'))")

    cat > "$test_dir/${proj_name}.qsf" <<EOF
# ${module_name} FPGA Test — DE10-Nano Quartus Settings
# Auto-generated by quartus_batch_compile.sh
# Device: Cyclone V 5CSEBA6U23I7

set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEBA6U23I7
set_global_assignment -name TOP_LEVEL_ENTITY ${proj_name}_top
set_global_assignment -name ORIGINAL_QUARTUS_VERSION 25.1
set_global_assignment -name PROJECT_CREATION_TIME_DATE "$(date '+%Y-%m-%d')"
set_global_assignment -name MIN_CORE_JUNCTION_TEMP "-40"
set_global_assignment -name MAX_CORE_JUNCTION_TEMP 100
set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 256

# RTL Sources
set_global_assignment -name SYSTEMVERILOG_FILE ${proj_name}_top.sv
set_global_assignment -name SYSTEMVERILOG_FILE ${rtl_rel}

# SDC
set_global_assignment -name SDC_FILE ${proj_name}.sdc

# ============================================================
# Pin Assignments — DE10-Nano (Tables 3-5 to 3-10)
# ============================================================

# Clock (Table 3-5) — FPGA_CLK1_50 = 50 MHz
set_location_assignment PIN_V11  -to CLOCK_50
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to CLOCK_50

# KEY (Table 3-7) — active low push-buttons
set_location_assignment PIN_AH17 -to KEY[0]
set_location_assignment PIN_AH16 -to KEY[1]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to KEY[0]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to KEY[1]

# SW (Table 3-6) — slide switches
set_location_assignment PIN_Y24  -to SW[0]
set_location_assignment PIN_W24  -to SW[1]
set_location_assignment PIN_W21  -to SW[2]
set_location_assignment PIN_W20  -to SW[3]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to SW[*]

# LED (Table 3-8) — active high
set_location_assignment PIN_W15  -to LEDR[0]
set_location_assignment PIN_AA24 -to LEDR[1]
set_location_assignment PIN_V16  -to LEDR[2]
set_location_assignment PIN_V15  -to LEDR[3]
set_location_assignment PIN_AF26 -to LEDR[4]
set_location_assignment PIN_AE26 -to LEDR[5]
set_location_assignment PIN_Y16  -to LEDR[6]
set_location_assignment PIN_AA23 -to LEDR[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to LEDR[*]

# GPIO 0 (JP1) — Table 3-10, directly matched to DE10-Nano manual
set_location_assignment PIN_V12  -to GPIO_0[0]
set_location_assignment PIN_E8   -to GPIO_0[1]
set_location_assignment PIN_W12  -to GPIO_0[2]
set_location_assignment PIN_D11  -to GPIO_0[3]
set_location_assignment PIN_D8   -to GPIO_0[4]
set_location_assignment PIN_AH13 -to GPIO_0[5]
set_location_assignment PIN_AF7  -to GPIO_0[6]
set_location_assignment PIN_AH14 -to GPIO_0[7]
set_location_assignment PIN_AF4  -to GPIO_0[8]
set_location_assignment PIN_AH3  -to GPIO_0[9]
set_location_assignment PIN_AD5  -to GPIO_0[10]
set_location_assignment PIN_AG14 -to GPIO_0[11]
set_location_assignment PIN_AE23 -to GPIO_0[12]
set_location_assignment PIN_AE6  -to GPIO_0[13]
set_location_assignment PIN_AD23 -to GPIO_0[14]
set_location_assignment PIN_AE24 -to GPIO_0[15]
set_location_assignment PIN_D12  -to GPIO_0[16]
set_location_assignment PIN_AD20 -to GPIO_0[17]
set_location_assignment PIN_C12  -to GPIO_0[18]
set_location_assignment PIN_AD17 -to GPIO_0[19]
set_location_assignment PIN_AC23 -to GPIO_0[20]
set_location_assignment PIN_AC22 -to GPIO_0[21]
set_location_assignment PIN_Y19  -to GPIO_0[22]
set_location_assignment PIN_AB23 -to GPIO_0[23]
set_location_assignment PIN_AA19 -to GPIO_0[24]
set_location_assignment PIN_W11  -to GPIO_0[25]
set_location_assignment PIN_AA18 -to GPIO_0[26]
set_location_assignment PIN_W14  -to GPIO_0[27]
set_location_assignment PIN_Y18  -to GPIO_0[28]
set_location_assignment PIN_Y17  -to GPIO_0[29]
set_location_assignment PIN_AB25 -to GPIO_0[30]
set_location_assignment PIN_AB26 -to GPIO_0[31]
set_location_assignment PIN_Y11  -to GPIO_0[32]
set_location_assignment PIN_AA26 -to GPIO_0[33]
set_location_assignment PIN_AA13 -to GPIO_0[34]
set_location_assignment PIN_AA11 -to GPIO_0[35]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to GPIO_0[*]

# Partition settings
set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -section_id Top
set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -section_id Top
set_global_assignment -name PARTITION_COLOR 16764057 -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -section_id Top
EOF
}

# ===== 產生 SDC =====
generate_sdc() {
    local test_dir="$1"
    local proj_name="$2"
    local is_sequential="$3"

    if [ "$is_sequential" -eq 1 ]; then
        cat > "$test_dir/${proj_name}.sdc" <<EOF
# ${proj_name} — Timing Constraints
# DE10-Nano Cyclone V 5CSEBA6U23I7

# 50MHz main clock
create_clock -name CLOCK_50 -period 20.000 [get_ports {CLOCK_50}]

# Buttons, switches, LEDs are async
set_false_path -from [get_ports {KEY[*]}]
set_false_path -from [get_ports {SW[*]}]
set_false_path -to   [get_ports {LEDR[*]}]

# GPIO is async
set_false_path -from [get_ports {GPIO_0[*]}]
set_false_path -to   [get_ports {GPIO_0[*]}]
EOF
    else
        # Combinational design: virtual clock
        cat > "$test_dir/${proj_name}.sdc" <<EOF
# ${proj_name} — Timing Constraints (Combinational Design)
# DE10-Nano Cyclone V 5CSEBA6U23I7

# Virtual clock for combinational timing analysis
create_clock -name CLOCK_50 -period 20.000 [get_ports {CLOCK_50}]

# All I/O is async for combinational design
set_false_path -from [get_ports {KEY[*]}]
set_false_path -from [get_ports {SW[*]}]
set_false_path -to   [get_ports {LEDR[*]}]
set_false_path -from [get_ports {GPIO_0[*]}]
set_false_path -to   [get_ports {GPIO_0[*]}]
EOF
    fi
}

# ===== 從 fit summary 解析 ALM/Register 用量 =====
parse_fit_summary() {
    local rpt_file="$1"
    if [ ! -f "$rpt_file" ]; then
        echo "0 0"
        return
    fi
    local alms regs
    alms=$(grep -m1 'Logic utilization' "$rpt_file" | grep -oP ':\s*\K[\d,]+' | head -1 | tr -d ',') || alms=0
    regs=$(grep -m1 'Total registers' "$rpt_file" | grep -oP ':\s*\K[\d,]+' | head -1 | tr -d ',') || regs=0
    [ -z "$alms" ] && alms=0
    [ -z "$regs" ] && regs=0
    echo "$alms $regs"
}

# ===== 從 STA summary 解析 Fmax =====
parse_sta_fmax() {
    local rpt_file="$1"
    if [ ! -f "$rpt_file" ]; then
        echo "N/A"
        return
    fi
    local fmax
    fmax=$(grep -oP '[\d.]+\s*MHz' "$rpt_file" | head -1 | grep -oP '[\d.]+') || fmax="N/A"
    [ -z "$fmax" ] && fmax="N/A"
    echo "$fmax"
}

# ===== 主編譯函數 =====
compile_ic() {
    local ic_num_raw="$1"
    local ic_num_padded
    ic_num_padded=$(printf '%03d' "$ic_num_raw")

    # 找到 IC 目錄
    local ic_dir_match
    ic_dir_match=$(ls -d "$IC_DIR/ic_${ic_num_padded}_"* 2>/dev/null | head -1)
    if [ -z "$ic_dir_match" ]; then
        log_skip "IC #${ic_num_raw}: 目錄不存在" >&2
        echo "{\"ic_num\":${ic_num_raw},\"status\":\"SKIP\",\"reason\":\"directory not found\"}"
        return
    fi

    local ic_name
    ic_name=$(basename "$ic_dir_match" | sed 's/ic_[0-9]*_//')

    # 找到 RTL 檔案（排除 formal）
    local sv_file
    sv_file=$(ls "$ic_dir_match/phase2_design/rtl/"*.sv 2>/dev/null | grep -v formal | head -1)
    if [ -z "$sv_file" ]; then
        log_skip "IC #${ic_num_raw} (${ic_name}): 無 RTL 檔案" >&2
        echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"status\":\"SKIP\",\"reason\":\"no RTL file\"}"
        return
    fi

    # 取得 module 名稱
    local module_name
    module_name=$(get_module_name "$sv_file")
    if [ -z "$module_name" ]; then
        log_skip "IC #${ic_num_raw} (${ic_name}): 無法解析 module 名稱" >&2
        echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"status\":\"SKIP\",\"reason\":\"cannot parse module\"}"
        return
    fi

    local proj_name="${module_name}_fpga"
    local test_dir="$FPGA_DIR/${module_name}_test"

    log_info "IC #${ic_num_raw} (${ic_name}): module=${module_name}" >&2

    # 判斷 sequential vs combinational
    local is_sequential=0
    has_clk_rst "$sv_file" && is_sequential=1
    has_clk_only "$sv_file" && is_sequential=1

    # 建立測試目錄
    mkdir -p "$test_dir"

    # 產生所有專案檔案
    generate_fpga_top "$ic_num_raw" "$ic_name" "$module_name" "$sv_file" "$test_dir" >&2
    if [ $? -ne 0 ]; then
        echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"module\":\"${module_name}\",\"status\":\"FAIL\",\"reason\":\"wrapper generation failed\"}"
        return
    fi

    generate_qpf "$test_dir" "$proj_name"
    generate_qsf "$test_dir" "$proj_name" "$module_name" "$sv_file" "$ic_dir_match"
    generate_sdc "$test_dir" "$proj_name" "$is_sequential"

    # ===== 執行 Quartus 編譯 =====
    local compile_log="$test_dir/compile.log"
    local start_time
    start_time=$(date +%s)

    log_info "  Step 1/4: quartus_map (Analysis & Synthesis)..." >&2
    (cd "$test_dir" && "$QUARTUS_BIN/quartus_map" "$proj_name" 2>&1 | tee -a "$compile_log" | tail -3) >&2

    # 檢查 map 是否成功
    if [ ! -f "$test_dir/${proj_name}.map.rpt" ]; then
        log_fail "IC #${ic_num_raw} (${ic_name}): quartus_map 失敗" >&2
        local end_time=$(date +%s)
        local elapsed=$((end_time - start_time))
        echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"module\":\"${module_name}\",\"status\":\"FAIL\",\"stage\":\"map\",\"elapsed_sec\":${elapsed}}"
        return
    fi

    log_info "  Step 2/4: quartus_fit (Fitter)..." >&2
    (cd "$test_dir" && "$QUARTUS_BIN/quartus_fit" "$proj_name" 2>&1 | tee -a "$compile_log" | tail -3) >&2

    if [ ! -f "$test_dir/${proj_name}.fit.rpt" ]; then
        log_fail "IC #${ic_num_raw} (${ic_name}): quartus_fit 失敗" >&2
        local end_time=$(date +%s)
        local elapsed=$((end_time - start_time))
        echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"module\":\"${module_name}\",\"status\":\"FAIL\",\"stage\":\"fit\",\"elapsed_sec\":${elapsed}}"
        return
    fi

    log_info "  Step 3/4: quartus_asm (Assembler)..." >&2
    (cd "$test_dir" && "$QUARTUS_BIN/quartus_asm" "$proj_name" 2>&1 | tee -a "$compile_log" | tail -3) >&2

    log_info "  Step 4/4: quartus_sta (Timing Analysis)..." >&2
    (cd "$test_dir" && "$QUARTUS_BIN/quartus_sta" "$proj_name" 2>&1 | tee -a "$compile_log" | tail -3) >&2

    local end_time
    end_time=$(date +%s)
    local elapsed=$((end_time - start_time))

    # ===== 收集結果 =====
    local sof_file="$test_dir/${proj_name}.sof"
    local sof_size="0"
    local status="FAIL"

    if [ -f "$sof_file" ]; then
        sof_size=$(stat -c%s "$sof_file" 2>/dev/null || echo "0")
        status="PASS"
        log_pass "IC #${ic_num_raw} (${ic_name}): SOF 產生成功 ($(du -h "$sof_file" | cut -f1))" >&2
    else
        log_fail "IC #${ic_num_raw} (${ic_name}): 無 SOF 輸出" >&2
    fi

    # 解析 fit summary
    local fit_data
    fit_data=$(parse_fit_summary "$test_dir/${proj_name}.fit.summary")
    local alms=$(echo "$fit_data" | cut -d' ' -f1)
    local regs=$(echo "$fit_data" | cut -d' ' -f2)

    # 解析 Fmax
    local fmax
    fmax=$(parse_sta_fmax "$test_dir/${proj_name}.sta.summary")

    # 檢查是否太大
    if [ "$alms" -gt "$MAX_ALMS" ] 2>/dev/null; then
        status="OVERSIZE"
        log_skip "IC #${ic_num_raw} (${ic_name}): 超過 Cyclone V 容量 (${alms} ALMs > ${MAX_ALMS})" >&2
    fi

    # 輸出 JSON 結果
    echo "{\"ic_num\":${ic_num_raw},\"ic_name\":\"${ic_name}\",\"module\":\"${module_name}\",\"status\":\"${status}\",\"alms\":${alms:-0},\"registers\":${regs:-0},\"fmax_mhz\":\"${fmax}\",\"sof_size\":${sof_size},\"elapsed_sec\":${elapsed},\"test_dir\":\"${test_dir}\"}"
}

# =============================================================================
# 主流程
# =============================================================================

echo "============================================================"
echo "  Vibe-IC Quartus Batch Compile"
echo "  DE10-Nano (Cyclone V 5CSEBA6U23I7)"
echo "  範圍：IC #${START} ~ #${END}"
echo "  時間：${TIMESTAMP}"
echo "============================================================"
echo ""

# 檢查 Quartus
if ! command -v quartus_map &>/dev/null; then
    echo "ERROR: quartus_map 不在 PATH 中"
    echo "請確認 Quartus 路徑：$QUARTUS_BIN"
    exit 1
fi

log_info "Quartus 版本: $(quartus_map --version 2>/dev/null | head -1)"
echo ""

# 建立輸出目錄
mkdir -p "$FPGA_DIR"

# 逐一編譯
TOTAL=0
PASS=0
FAIL=0
SKIP=0
OVERSIZE=0

# JSON results array
JSON_RESULTS="["
FIRST=1

for ic_num in $(seq "$START" "$END"); do
    TOTAL=$((TOTAL + 1))

    # 執行編譯並捕獲結果
    result=$(compile_ic "$ic_num")

    # 解析狀態
    ic_status=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('status','SKIP'))" 2>/dev/null || echo "SKIP")

    case "$ic_status" in
        PASS)     PASS=$((PASS + 1)) ;;
        FAIL)     FAIL=$((FAIL + 1)) ;;
        OVERSIZE) OVERSIZE=$((OVERSIZE + 1)) ;;
        *)        SKIP=$((SKIP + 1)) ;;
    esac

    # 加入 JSON 結果
    if [ "$FIRST" -eq 1 ]; then
        JSON_RESULTS="${JSON_RESULTS}${result}"
        FIRST=0
    else
        JSON_RESULTS="${JSON_RESULTS},${result}"
    fi

    echo "  ────────────────────────────────────"
done

JSON_RESULTS="${JSON_RESULTS}]"

# =============================================================================
# 輸出 JSON 結果
# =============================================================================

cat > "$RESULTS_JSON" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "device": "5CSEBA6U23I7",
  "board": "DE10-Nano",
  "range": {"start": ${START}, "end": ${END}},
  "summary": {
    "total": ${TOTAL},
    "pass": ${PASS},
    "fail": ${FAIL},
    "skip": ${SKIP},
    "oversize": ${OVERSIZE}
  },
  "results": ${JSON_RESULTS}
}
EOF

log_info "JSON 結果已寫入: $RESULTS_JSON"

# =============================================================================
# 輸出 Markdown Dashboard
# =============================================================================

cat > "$RESULTS_MD" <<EOF
# Quartus Batch Compile Dashboard

> **裝置**：Cyclone V 5CSEBA6U23I7 (DE10-Nano)
> **時間**：${TIMESTAMP}
> **範圍**：IC #${START} ~ #${END}

## 摘要

| 指標 | 數值 |
|------|:----:|
| **總計** | ${TOTAL} |
| **PASS** | ${PASS} |
| **FAIL** | ${FAIL} |
| **SKIP** | ${SKIP} |
| **OVERSIZE** | ${OVERSIZE} |
| **通過率** | $(python3 -c "print(f'{${PASS}/(${PASS}+${FAIL})*100:.1f}%' if ${PASS}+${FAIL}>0 else 'N/A')") |

## 詳細結果

| IC# | 名稱 | Module | 狀態 | ALMs | Registers | Fmax (MHz) | SOF 大小 | 時間 (s) |
|----:|------|--------|:----:|-----:|----------:|:----------:|---------:|---------:|
EOF

# 解析 JSON 並輸出 Markdown 表格
python3 - "$RESULTS_JSON" "$RESULTS_MD" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

lines = []
for r in data['results']:
    ic_num = r.get('ic_num', '?')
    ic_name = r.get('ic_name', '?')
    module = r.get('module', 'N/A')
    status = r.get('status', 'SKIP')
    alms = r.get('alms', 0)
    regs = r.get('registers', 0)
    fmax = r.get('fmax_mhz', 'N/A')
    sof_bytes = r.get('sof_size', 0)
    elapsed = r.get('elapsed_sec', 0)

    # Format SOF size
    if sof_bytes > 1048576:
        sof_str = f"{sof_bytes/1048576:.1f} MB"
    elif sof_bytes > 1024:
        sof_str = f"{sof_bytes/1024:.0f} KB"
    elif sof_bytes > 0:
        sof_str = f"{sof_bytes} B"
    else:
        sof_str = "—"

    # Status emoji
    status_str = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "OVERSIZE": "OVER"}.get(status, status)

    lines.append(f"| {ic_num} | {ic_name} | {module} | {status_str} | {alms} | {regs} | {fmax} | {sof_str} | {elapsed} |")

with open(sys.argv[2], 'a') as f:
    f.write('\n'.join(lines) + '\n')

PYEOF

cat >> "$RESULTS_MD" <<EOF

## 使用說明

\`\`\`bash
# 編譯全部
bash tools/quartus_batch_compile.sh

# 編譯 IC #1-10
bash tools/quartus_batch_compile.sh 1 10

# 編譯單一 IC
bash tools/quartus_batch_compile.sh 5 5
\`\`\`

## SOF 位置

每顆 IC 的 SOF 檔案位於：
\`\`\`
fpga_verification/de10_nano_tests/<module>_test/<module>_fpga.sof
\`\`\`
EOF

log_info "Dashboard 已寫入: $RESULTS_MD"

echo ""
echo "============================================================"
echo "  Batch Compile 完成"
echo "  PASS: ${PASS} / FAIL: ${FAIL} / SKIP: ${SKIP} / OVERSIZE: ${OVERSIZE}"
echo "============================================================"
