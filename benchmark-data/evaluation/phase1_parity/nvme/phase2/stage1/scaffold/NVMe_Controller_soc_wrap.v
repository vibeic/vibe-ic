// Auto-generated SoC integration wrapper (APB-lite).
// Wraps NVMe_Controller and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: NVMe_Controller
// Register file present (L4): yes

`timescale 1ns/1ps

module NVMe_Controller_soc_wrap (
    // ---- APB-lite register-access bus ----
    input         PCLK,
    input         PRESETn,
    input  [11:0] PADDR,
    input         PSEL,
    input         PENABLE,
    input         PWRITE,
    input  [31:0] PWDATA,
    output reg [31:0] PRDATA,
    output        PREADY
    ,
    // ---- native protocol ports (passthrough to pads) ----
    inout  PCIe_Link,  // Underlying transport for all SQ/CQ/data/doorbell/MSI-X TLPs. ×1..×16 lanes.
    input  CLKREQ,  // Optional clock request (M.2)
    input  BAR0_BAR1_MMIO,  // NVMe controller register region (≥ 4 KB)
    input  Host_SQ_memory,  // SQ ring buffers in host DRAM
    input  Host_CQ_memory,  // CQ ring buffers in host DRAM
    inout  Host_PRP_SGL_buffers,  // Data + metadata buffers + PRP Lists + SGL segments
    input  MSI_X_Table  // MSI-X vector delivery to host APIC/GIC
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 27 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset          CAP [64b, ro]
    // offset          VS [32b, ro]
    // offset          INTMS [32b, rws]
    // offset          INTMC [32b, rwc]
    // offset          CC [32b, rw]
    // offset          CSTS [32b, ro/rwc]
    // offset          NSSR [32b, rw]
    // offset          AQA [32b, rw]
    // offset          ASQ [64b, rw]
    // offset          ACQ [64b, rw]
    // offset          CMBLOC [32b, ro]
    // offset          CMBSZ [32b, ro]
    // offset          BPINFO [32b, ro]
    // offset          BPRSEL [32b, rw]
    // offset          BPMBL [64b, rw]
    // offset          CMBMSC [64b, rw]
    // offset          CMBSTS [32b, ro]
    // offset          PMRCAP [32b, ro]
    // offset          PMRCTL [32b, rw]
    // offset          PMRSTS [32b, ro]
    // offset          PMREBS [32b, ro]
    // offset          PMRSWTP [32b, ro]
    // offset          PMRMSC [64b, rw]
    // offset          SQ0TDBL [32b, rw]
    // offset          CQ0HDBL [32b, rw]
    // offset          SQyTDBL [32b, rw]
    // offset          CQyHDBL [32b, rw]

    always @(*) begin
        PRDATA = 32'h0;
        if (apb_read) begin
            case (PADDR)
                // TODO: 12'hXXX: PRDATA = <reg>;  per offsets above
                default: PRDATA = 32'h0;
            endcase
        end
    end

    // TODO: on apb_write, decode PADDR and update the block's
    //       register file (writes are stubbed out for now).

    // Wrapped protocol-block instance.
    NVMe_Controller u_NVMe_Controller (
        .PCIe_Link(PCIe_Link),
        .REFCLK(PCLK),
        .PERST(PRESETn),
        .CLKREQ(CLKREQ),
        .BAR0_BAR1_MMIO(BAR0_BAR1_MMIO),
        .Host_SQ_memory(Host_SQ_memory),
        .Host_CQ_memory(Host_CQ_memory),
        .Host_PRP_SGL_buffers(Host_PRP_SGL_buffers),
        .MSI_X_Table(MSI_X_Table)
    );

endmodule
