### 9.1.3 I/O delay
- `set_input_delay` / `set_output_delay`:使用 **clock period 的 20%** 作為預設(例:`sky130_fd_sc_hd` 10 ns → 2 ns I/O delay)
- Plugin 可依需要 override;若 override,須於 declaration.json 註記
