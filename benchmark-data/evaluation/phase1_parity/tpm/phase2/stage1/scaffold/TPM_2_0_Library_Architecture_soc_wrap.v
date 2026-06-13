// Auto-generated SoC integration wrapper (APB-lite).
// Wraps TPM_2_0_Library_Architecture and exposes a standard register-access bus so the
// protocol block can drop into an SoC. Decode body is TODO.
// Top module: TPM_2_0_Library_Architecture
// Register file present (L4): yes

`timescale 1ns/1ps

module TPM_2_0_Library_Architecture_soc_wrap (
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
    input  host_command_stream,  // Octet stream of marshalled command — TPM_ST + commandSize + commandCode + handles + sessions + parameters.
    input  tpm_response_stream,  // Octet stream of marshalled response — TPM_ST + responseSize + responseCode + handles + parameters + sessions.
    input  tpm_interrupt,  // Edge-triggered SERIRQ (LPC) or GPIO (SPI / I2C) indicating dataAvail / commandReady transition.
    input  TPM_ACCESS,  // MMIO register; locality / bus-ownership protocol.
    input  TPM_INT_ENABLE,  // MMIO register; per-locality interrupt mask.
    input  TPM_INT_VECTOR,  // MMIO register; SERIRQ vector.
    input  TPM_INT_STATUS,  // MMIO register; sticky interrupt cause; write-1-to-clear.
    input  TPM_INTF_CAPABILITY,  // MMIO register; reports interface version + supported transfer sizes.
    input  TPM_STS,  // MMIO register; main status (commandReady, tpmGo, dataAvail, Expect, selfTestDone, responseRetry, commandCancel, burstCount).
    input  TPM_DATA_FIFO,  // MMIO byte-FIFO; carries command/response octet stream.
    input  TPM_INTERFACE_ID,  // MMIO register; PTP selects FIFO / CRB interface and reports version.
    input  TPM_XDATA_FIFO,  // MMIO 32-bit alias of DATA_FIFO for bulk transfer.
    input  TPM_DID_VID,  // MMIO register; Vendor ID (low 16) + Device ID (high 16).
    input  TPM_RID,  // MMIO register; revision ID.
    input  PP_Physical_Presence  // Strap or button tied to platform; sensed via tpmEstablishment bit of TPM_ACCESS.
);

    // APB-lite is always single-cycle ready in this wrapper.
    assign PREADY = 1'b1;

    wire apb_write = PSEL & PENABLE &  PWRITE;
    wire apb_read  = PSEL & PENABLE & ~PWRITE;

    // -----------------------------------------------------------
    // APB -> register-file decode stub.
    // The protocol exposes 11 register(s) (from L4).
    // TODO: connect PWDATA/PRDATA to the block's register file
    //       using the offsets below, then instantiate the block.
    // -----------------------------------------------------------
    // offset 0x00     TPM_ACCESS [8b, r/w]
    // offset 0x08     TPM_INT_ENABLE [32b, r/w]
    // offset 0x0C     TPM_INT_VECTOR [4b, r/w]
    // offset 0x10     TPM_INT_STATUS [32b, r/w1c]
    // offset 0x14     TPM_INTF_CAPABILITY [32b, ro]
    // offset 0x18     TPM_STS [32b, r/w]
    // offset 0x24     TPM_DATA_FIFO [8b, r/w]
    // offset 0x30     TPM_INTERFACE_ID [64b, r/w]
    // offset 0x80     TPM_XDATA_FIFO [32b, r/w]
    // offset 0xF00    TPM_DID_VID [32b, ro]
    // offset 0xF04    TPM_RID [8b, ro]

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
    TPM_2_0_Library_Architecture u_TPM_2_0_Library_Architecture (
        .host_command_stream(host_command_stream),
        .tpm_response_stream(tpm_response_stream),
        .tpm_interrupt(tpm_interrupt),
        .TPM_ACCESS(TPM_ACCESS),
        .TPM_INT_ENABLE(TPM_INT_ENABLE),
        .TPM_INT_VECTOR(TPM_INT_VECTOR),
        .TPM_INT_STATUS(TPM_INT_STATUS),
        .TPM_INTF_CAPABILITY(TPM_INTF_CAPABILITY),
        .TPM_STS(TPM_STS),
        .TPM_DATA_FIFO(TPM_DATA_FIFO),
        .TPM_INTERFACE_ID(TPM_INTERFACE_ID),
        .TPM_XDATA_FIFO(TPM_XDATA_FIFO),
        .TPM_DID_VID(TPM_DID_VID),
        .TPM_RID(TPM_RID),
        .PLTRST_TPM_RST(PRESETn),
        .PP_Physical_Presence(PP_Physical_Presence),
        .clk(PCLK)
    );

endmodule
