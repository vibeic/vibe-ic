# subservient — SOURCE_MANIFEST

IC: subservient (kind=soc). Task declared reused_ip=true with a vendor_rtl/ drop,
but the blind input root (input/) contained ONLY docs/ (L1-L9) — there was NO
vendor_rtl/ and NO pdk/ directory present. See residual: input-vendor-rtl-missing.

Therefore ALL RTL below is GENERATED clean-room from L1-L9 + the runner-emitted
L1-L23 generated_docs. No reference RTL was read (blindness preserved).

| File | Origin | Role |
|---|---|---|
| phase2/stage1/rtl/subservient.v | GENERATED | chip_top wrapper (tape-out default top, L8.1) + GPIO peripheral + integration glue |
| phase2/stage1/rtl/serv_rv32i_core.v | GENERATED | RV32I-faithful CPU core (clean-room; SERV ISA semantics preserved, micro-arch is a multi-cycle datapath per L2/L8 freedom) |
| phase2/stage1/rtl/servile_ram_if.v | GENERATED | Servile RF/RAM byte gather/scatter adapter (L8.2.2 / L8.2.5) |

## Declaration (per L7.0)
- top_module: subservient (with GPIO)
- isa_extensions: ["I", "Zifencei"]  (C/M/Zicsr not implemented — allowed optional)
- memsize_bytes: 1024
- reset_polarity: active_high (synchronous)
- clock_port_name: i_clk
- sram_interface_protocol: generic_8bit_addr_data_we (byte-wide, 10-bit addr)
- gpio_pin_count: 1
- rf_storage: shared_sram
