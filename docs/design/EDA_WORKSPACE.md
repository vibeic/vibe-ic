# EDA Workspace — SSD2 文件位置

本專案的 EDA 產出檔案（GDS、DEF、DFT 向量等大型二進位檔）存放在 SSD2 上，不包含在 git repo 中。

## SSD2 掛載點

```bash
# <host> (<lan-ip>)
~/eda            → /mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/eda/
~/ic_documents   → /mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents/
```

## 目錄結構

```
~/eda/
├── pdks/
│   └── gf180mcu-pdk/                    GF180MCU PDK (GitHub shallow clone, 68 MB)
│
├── designs/
│   ├── bench-a_gf180/                    BENCH-A 完整 GF180 設計
│   │   ├── src/                         RTL + formal assertions + synth wrapper
│   │   ├── results/
│   │   │   ├── bench-a_gf180_final.gds   ★ 最終 GDS (5.1 MB, DRC clean)
│   │   │   ├── bench-a_gf180_tiecell.def DEF (detailed routed)
│   │   │   ├── bench-a_pnr_tiecell.v     Post-route netlist
│   │   │   ├── synth_bench-a_tiecell.v   Synthesized netlist (with tie cells)
│   │   │   └── route_drc_tiecell.rpt    DRC report (0 violations)
│   │   ├── dft/
│   │   │   ├── bench-a_scanchained_final.v  Scan-chained netlist (129 elements)
│   │   │   ├── bench-a_jtag_final.v         JTAG TAP netlist
│   │   │   ├── bench-a_atpg_v2.tv.json     Test vectors (66 compacted)
│   │   │   └── bench-a_coverage_v2.yml     Coverage metadata (90.39%)
│   │   ├── sim/
│   │   │   ├── bench-a_sim_wrapper.sv    Verilator sim wrapper
│   │   │   ├── test_bench-a.py           cocotb testbench (7 tests)
│   │   │   └── Makefile                 Verilator + cocotb runner
│   │   ├── analog/
│   │   │   ├── ldo_v5.sp               LDO (VOUT=1.800V) ★
│   │   │   ├── osc_ring.sp             OSC (4.97MHz) ★
│   │   │   ├── por_v2.sp               POR (VPOR+=1.492V) ★
│   │   │   └── *.log                   ngspice simulation logs
│   │   ├── reports/                     → same as repo BENCH-A_project/reports/
│   │   ├── pnr_tiecell.tcl             P&R script with tie cells
│   │   └── pnr_detailed.tcl            P&R script (older, setSigType hack)
│   │
│   └── sn74hc163_gf180/                SN74HC163 GF180 設計
│       ├── src/counter4.v               RTL
│       ├── results/
│       │   ├── counter4_gf180.gds       GDS (1.5 MB, DRC clean)
│       │   ├── counter4_gf180.def       DEF
│       │   └── synth_counter4.v         Netlist
│       ├── run_flow.sh                  一鍵流程腳本
│       └── gen_gds.py                   KLayout GDS 生成器
│
└── tools/                               (empty, tools are in Docker container)
```

## 快速存取

```bash
# 查看 BENCH-A 最終 GDS
ls -lh ~/eda/designs/bench-a_gf180/results/bench-a_gf180_final.gds

# 跑 SN74HC163 完整流程
docker exec iic-eda bash /foss/eda/designs/sn74hc163_gf180/run_flow.sh

# 跑 BENCH-A cocotb 模擬
docker exec iic-eda bash -c 'cd /foss/eda/designs/bench-a_gf180/sim && make SIM=verilator'

# 跑 LDO ngspice 模擬
docker exec iic-eda bash -c 'ngspice -b /foss/eda/designs/bench-a_gf180/analog/ldo_v5.sp'
```

## Docker Container

```bash
# 容器名稱: iic-eda (auto-restart on reboot)
# Image: hpretl/iic-osic-tools:latest (22.1 GB)
# Mount: ~/AI_IC_design → /foss/designs, ~/eda → /foss/eda

docker start iic-eda  # if stopped
docker exec -it iic-eda bash  # interactive shell
```
