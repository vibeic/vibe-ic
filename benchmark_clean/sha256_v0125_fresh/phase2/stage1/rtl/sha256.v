// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl (AI-authored from input/docs/L*.md + NIST FIPS-180-4)
//
// Top module: sha256 — NIST FIPS-180-4 SHA-256 / SHA-224 dual-mode hash accelerator.
// Memory-mapped register file interface per L3 / L4 / L5.
//
// Ports per L3:
//   clk, reset_n (sync active-LOW), cs, we, address[7:0],
//   write_data[31:0], read_data[31:0], error
//
// Register map per L5:
//   0x00 NAME0    R   "sha2"
//   0x01 NAME1    R   "56  " / "224 "
//   0x02 VERSION  R   "0.10"
//   0x08 CTRL     R/W [0]=INIT [1]=NEXT [2]=MODE
//   0x09 STATUS   R   [0]=READY [1]=VALID
//   0x10..0x1F  BLOCK0..15  W   512-bit message block
//   0x20..0x27  DIGEST0..7  R   256-bit digest (SHA-256) / first 224 bits (SHA-224)

`default_nettype none
module sha256 (
    input  wire         clk,
    input  wire         reset_n,    // sync active-LOW

    input  wire         cs,
    input  wire         we,
    input  wire [7:0]   address,
    input  wire [31:0]  write_data,
    output reg  [31:0]  read_data,
    output reg          error
);
    // -------------------------------------------------------------------
    // Register-map address constants (per L5)
    // -------------------------------------------------------------------
    localparam ADDR_NAME0    = 8'h00;
    localparam ADDR_NAME1    = 8'h01;
    localparam ADDR_VERSION  = 8'h02;
    localparam ADDR_CTRL     = 8'h08;
    localparam ADDR_STATUS   = 8'h09;
    localparam ADDR_BLOCK_LO = 8'h10;
    localparam ADDR_BLOCK_HI = 8'h1F;
    localparam ADDR_DIGEST_LO= 8'h20;
    localparam ADDR_DIGEST_HI= 8'h27;

    localparam CTRL_INIT_BIT = 0;
    localparam CTRL_NEXT_BIT = 1;
    localparam CTRL_MODE_BIT = 2;

    localparam STATUS_READY_BIT = 0;
    localparam STATUS_VALID_BIT = 1;

    // Identifier constants
    localparam [31:0] NAME0_STR   = 32'h73686132; // "sha2"
    localparam [31:0] NAME1_STR   = 32'h35362020; // "56  "
    localparam [31:0] VERSION_STR = 32'h302E3130; // "0.10"

    // -------------------------------------------------------------------
    // Register file storage
    // -------------------------------------------------------------------
    reg [31:0] block_mem [0:15];   // 0x10..0x1F
    reg [2:0]  ctrl_reg;           // [0]=INIT [1]=NEXT [2]=MODE (only MODE persists)
    reg        mode_q;             // captured MODE bit
    reg        init_pulse;
    reg        next_pulse;

    integer i;

    // -------------------------------------------------------------------
    // Pack 16 block words into 512-bit block
    //   block_words[0]  -> bits [511:480]  (big-endian per FIPS-180-4)
    // -------------------------------------------------------------------
    wire [511:0] block_packed = {
        block_mem[ 0], block_mem[ 1], block_mem[ 2], block_mem[ 3],
        block_mem[ 4], block_mem[ 5], block_mem[ 6], block_mem[ 7],
        block_mem[ 8], block_mem[ 9], block_mem[10], block_mem[11],
        block_mem[12], block_mem[13], block_mem[14], block_mem[15]
    };

    // -------------------------------------------------------------------
    // Core instantiation
    // -------------------------------------------------------------------
    wire core_ready;
    wire core_valid;
    wire [255:0] core_digest;

    sha256_core u_core (
        .clk     (clk),
        .reset_n (reset_n),
        .init    (init_pulse),
        .next    (next_pulse),
        .mode    (mode_q),
        .block   (block_packed),
        .ready   (core_ready),
        .valid   (core_valid),
        .digest  (core_digest)
    );

    // -------------------------------------------------------------------
    // CTRL write — produce 1-cycle INIT / NEXT pulses + sticky MODE
    // -------------------------------------------------------------------
    always @(posedge clk) begin
        if (!reset_n) begin
            init_pulse <= 1'b0;
            next_pulse <= 1'b0;
            mode_q     <= 1'b1;        // default SHA-256
            ctrl_reg   <= 3'b000;
            for (i = 0; i < 16; i = i + 1) block_mem[i] <= 32'h0;
        end else begin
            // Default: deassert pulses each cycle
            init_pulse <= 1'b0;
            next_pulse <= 1'b0;

            if (cs && we) begin
                if (address >= ADDR_BLOCK_LO && address <= ADDR_BLOCK_HI) begin
                    block_mem[address[3:0]] <= write_data;
                end
                else if (address == ADDR_CTRL) begin
                    ctrl_reg   <= write_data[2:0];
                    mode_q     <= write_data[CTRL_MODE_BIT];
                    if (core_ready) begin
                        // INIT priority over NEXT (per L5 note)
                        if (write_data[CTRL_INIT_BIT])      init_pulse <= 1'b1;
                        else if (write_data[CTRL_NEXT_BIT]) next_pulse <= 1'b1;
                    end
                end
            end
        end
    end

    // -------------------------------------------------------------------
    // Read multiplexer (combinational)
    // -------------------------------------------------------------------
    wire [31:0] digest_word [0:7];
    assign digest_word[0] = core_digest[255:224];
    assign digest_word[1] = core_digest[223:192];
    assign digest_word[2] = core_digest[191:160];
    assign digest_word[3] = core_digest[159:128];
    assign digest_word[4] = core_digest[127: 96];
    assign digest_word[5] = core_digest[ 95: 64];
    assign digest_word[6] = core_digest[ 63: 32];
    assign digest_word[7] = core_digest[ 31:  0];

    // NAME1 depends on MODE (informational): "56  " for SHA-256, "224 " for SHA-224
    wire [31:0] name1_str = mode_q ? NAME1_STR : 32'h32323420; // "224 "

    always @(*) begin
        read_data = 32'h0;
        error     = 1'b0;
        if (cs && !we) begin
            case (address)
                ADDR_NAME0:   read_data = NAME0_STR;
                ADDR_NAME1:   read_data = name1_str;
                ADDR_VERSION: read_data = VERSION_STR;
                ADDR_CTRL:    read_data = {29'b0, ctrl_reg};
                ADDR_STATUS:  read_data = {30'b0, core_valid, core_ready};
                default: begin
                    if (address >= ADDR_DIGEST_LO && address <= ADDR_DIGEST_HI) begin
                        read_data = digest_word[address[2:0]];
                    end
                    else if (address >= ADDR_BLOCK_LO && address <= ADDR_BLOCK_HI) begin
                        // BLOCK is write-only per L5; read returns last-written value
                        read_data = block_mem[address[3:0]];
                    end
                    else begin
                        read_data = 32'h0;
                        error     = 1'b1;  // undefined address
                    end
                end
            endcase
        end
    end

endmodule
`default_nettype wire
