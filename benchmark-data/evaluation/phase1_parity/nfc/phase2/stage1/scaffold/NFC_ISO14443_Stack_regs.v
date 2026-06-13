// Auto-generated register-file skeleton.
// Address decode + read/write hooks are stubbed; behavior is TODO.
// Top module: NFC_ISO14443_Stack

`timescale 1ns/1ps

module NFC_ISO14443_Stack_regs (
    input         clk,
    input         rst_n,
    input  [31:0] reg_addr,
    input         reg_we,
    input  [31:0] reg_wdata,
    output reg [31:0] reg_rdata
);

    // Register declarations
    reg [15:0] ATQA; // offset  (read (picc reply to reqa / wupa))
    reg [31:0] UID; // offset  (read (across cascade levels 1..3))
    reg [7:0] BCC_per_CL; // offset  (computed by both pcd and picc)
    reg [7:0] SAK; // offset  (read (picc reply to final select))
    reg [7:0] ATS; // offset  (read (picc reply to rats 0xe0))
    reg [6:0] GetVersion_Response; // offset  (read (host apdu 0x60))
    reg [11:0] ATQB; // offset  (read (picc reply to reqb / wupb))
    reg [7:0] PCB; // offset  (read/write (per t=cl block))
    reg [7:0] CID; // offset  (read/write (assigned by pcd at rats param))

    // Reset
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ATQA <= 16'b0;
            UID <= 32'b0;
            BCC_per_CL <= 8'b0;
            SAK <= 8'b0;
            ATS <= 8'b0;
            GetVersion_Response <= 7'b0;
            ATQB <= 12'b0;
            PCB <= 8'b0;
            CID <= 8'b0;
        end else if (reg_we) begin
            // TODO — address decode (per L4 offsets)
        end
    end

    // Read mux (TODO — match the offsets above)
    always @(*) begin
        reg_rdata = 32'b0;
    end

endmodule
