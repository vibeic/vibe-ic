// ref_sha256.v -- Top-level register-mapped wrapper for the SHA-256 / SHA-224 core.
// Author: Vibe-IC strict-blind pilot. Derived solely from L1..L9 specs +
//         NIST FIPS-180-4 public crypto standard.
//
// External contract (L3 / L5):
//   - clk, reset_n (active-LOW, synchronous), cs, we
//   - address[7:0], write_data[31:0], read_data[31:0], error
//   - Register map:
//       0x00 NAME0    R   (32) magic word 0
//       0x01 NAME1    R   (32) magic word 1
//       0x02 VERSION  R   (32) version string
//       0x08 CTRL     R/W (32) bit0=INIT, bit1=NEXT, bit2=MODE (1=SHA-256, 0=SHA-224)
//       0x09 STATUS   R   (32) bit0=READY, bit1=VALID
//       0x10..0x1F BLOCK0..BLOCK15  W   (32 each) 512-bit message block
//       0x20..0x27 DIGEST0..DIGEST7 R   (32 each) 256-bit digest (SHA-256 full / SHA-224 first 224b)
//
// SHA-224 reads DIGEST7 as 0 (caller takes first 7 words).
//
// L5 says reserved-address reads "0 or error=1" -- Plugin's choice.  We
// implement: read_data=0 + error=1 for unknown addresses (most informative).

`timescale 1ns/1ps
`default_nettype none

module ref_sha256 (
    input  wire        clk,
    input  wire        reset_n,        // sync active-LOW
    input  wire        cs,
    input  wire        we,
    input  wire [ 7:0] address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error
);
    // ------------------------------------------------------------------
    // Register map addresses
    // ------------------------------------------------------------------
    localparam [7:0] ADDR_NAME0   = 8'h00;
    localparam [7:0] ADDR_NAME1   = 8'h01;
    localparam [7:0] ADDR_VERSION = 8'h02;
    localparam [7:0] ADDR_CTRL    = 8'h08;
    localparam [7:0] ADDR_STATUS  = 8'h09;
    localparam [7:0] ADDR_BLOCK0  = 8'h10;   // 0x10..0x1F
    localparam [7:0] ADDR_BLOCK15 = 8'h1F;
    localparam [7:0] ADDR_DIGEST0 = 8'h20;   // 0x20..0x27
    localparam [7:0] ADDR_DIGEST7 = 8'h27;

    // Magic name + version (informational; matches "sha2" / "5612" / "0.81" feel)
    localparam [31:0] CORE_NAME0   = 32'h73686132;  // "sha2"
    localparam [31:0] CORE_NAME1   = 32'h35362020;  // "56  "
    localparam [31:0] CORE_VERSION = 32'h302e3831;  // "0.81"

    // ------------------------------------------------------------------
    // Block register file: 16 x 32-bit
    // ------------------------------------------------------------------
    reg [31:0] block_regs [0:15];

    // CTRL bits
    reg ctrl_init, ctrl_next, ctrl_mode;

    // ------------------------------------------------------------------
    // Core instantiation
    // ------------------------------------------------------------------
    wire [511:0] block_flat;
    wire [255:0] core_digest;
    wire         core_ready;
    wire         core_valid;

    // Pack 16 block words into a flat 512-bit vector
    // block[511:480] = BLOCK0, block[479:448] = BLOCK1, ..., block[31:0] = BLOCK15
    genvar gi;
    generate
        for (gi = 0; gi < 16; gi = gi + 1) begin : g_pack
            assign block_flat[(511 - 32*gi) -: 32] = block_regs[gi];
        end
    endgenerate

    // INIT / NEXT pulses: assert for one cycle when CTRL is written with the bit set
    reg init_pulse, next_pulse;
    ref_sha256_core u_core (
        .clk          (clk),
        .reset_n      (reset_n),
        .init         (init_pulse),
        .next         (next_pulse),
        .mode         (ctrl_mode),
        .block        (block_flat),
        .ready        (core_ready),
        .digest_valid (core_valid),
        .digest       (core_digest)
    );

    // ------------------------------------------------------------------
    // Write path (synchronous, sync active-LOW reset)
    // ------------------------------------------------------------------
    integer wi;
    always @(posedge clk) begin
        if (!reset_n) begin
            for (wi = 0; wi < 16; wi = wi + 1)
                block_regs[wi] <= 32'h0;
            ctrl_init  <= 1'b0;
            ctrl_next  <= 1'b0;
            ctrl_mode  <= 1'b1;   // default SHA-256
            init_pulse <= 1'b0;
            next_pulse <= 1'b0;
        end else begin
            // Default: pulses last only one cycle
            init_pulse <= 1'b0;
            next_pulse <= 1'b0;

            if (cs && we) begin
                if (address >= ADDR_BLOCK0 && address <= ADDR_BLOCK15) begin
                    block_regs[address - ADDR_BLOCK0] <= write_data;
                end else if (address == ADDR_CTRL) begin
                    ctrl_init <= write_data[0];
                    ctrl_next <= write_data[1];
                    ctrl_mode <= write_data[2];
                    // Edge-trigger style: turn writes of INIT/NEXT into a single-cycle pulse
                    // to the core.  L5 says INIT and NEXT should not be set simultaneously;
                    // if both set, INIT wins (matches L5 note "reference采用INIT priority").
                    if (write_data[0])      init_pulse <= 1'b1;
                    else if (write_data[1]) next_pulse <= 1'b1;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Read path (combinational)
    // ------------------------------------------------------------------
    reg [31:0] read_data_n;
    reg        error_n;
    always @* begin
        read_data_n = 32'h0;
        error_n     = 1'b0;
        case (address)
            ADDR_NAME0:   read_data_n = CORE_NAME0;
            ADDR_NAME1:   read_data_n = CORE_NAME1;
            ADDR_VERSION: read_data_n = CORE_VERSION;
            ADDR_CTRL:    read_data_n = { 29'h0, ctrl_mode, ctrl_next, ctrl_init };
            ADDR_STATUS:  read_data_n = { 30'h0, core_valid, core_ready };
            default: begin
                if (address >= ADDR_DIGEST0 && address <= ADDR_DIGEST7) begin
                    // DIGEST0 = MS 32 bits of H, DIGEST7 = LS 32 bits
                    case (address - ADDR_DIGEST0)
                        4'd0: read_data_n = core_digest[255:224];
                        4'd1: read_data_n = core_digest[223:192];
                        4'd2: read_data_n = core_digest[191:160];
                        4'd3: read_data_n = core_digest[159:128];
                        4'd4: read_data_n = core_digest[127: 96];
                        4'd5: read_data_n = core_digest[ 95: 64];
                        4'd6: read_data_n = core_digest[ 63: 32];
                        4'd7: read_data_n = (ctrl_mode ? core_digest[31:0] : 32'h0);
                        default: read_data_n = 32'h0;
                    endcase
                end else if (address >= ADDR_BLOCK0 && address <= ADDR_BLOCK15) begin
                    // Block is write-only per L5 -- reads return 0 (allowed by spec)
                    read_data_n = 32'h0;
                end else begin
                    // Unknown address: error flag
                    read_data_n = 32'h0;
                    error_n     = 1'b1;
                end
            end
        endcase
    end

    // Register the read path so timing is well-defined.
    always @(posedge clk) begin
        if (!reset_n) begin
            read_data <= 32'h0;
            error     <= 1'b0;
        end else begin
            if (cs && !we) begin
                read_data <= read_data_n;
                error     <= error_n;
            end else begin
                error <= 1'b0;   // error only flagged on a read
            end
        end
    end

endmodule

`default_nettype wire
