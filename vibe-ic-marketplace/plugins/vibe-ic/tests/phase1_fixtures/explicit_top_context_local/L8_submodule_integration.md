## 8.1 Top 層級

`sha256` 為**單一 top module**,內部包含 register file + hash datapath(具體拆分由 Plugin 自選)。

對外契約:
- 5 個 port(L3 定義):`clk`、`reset_n`、`cs`、`we`、`address[7:0]`、`write_data[31:0]`、`read_data[31:0]`、`error`
- Register map(L4 / L5 定義):8-bit address space,主要 0x00-0x27

