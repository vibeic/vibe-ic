//============================================================================
// sha256.v  --  Top: memory-mapped SHA-256/SHA-224 hash accelerator
//
// SOURCE: GENERATED from the L1-L9 design docs (L3 port contract, L4 command
//   protocol, L5 register map) + NIST FIPS-180-4. No upstream RTL was read.
//
// External interface (L3):
//   clk, reset_n (sync active-LOW), cs, we, address[7:0],
//   write_data[31:0], read_data[31:0], error
//
// Register map (L5):
//   0x00 NAME0   R    chip id word 0
//   0x01 NAME1   R    chip id word 1
//   0x02 VERSION R    version string
//   0x08 CTRL    R/W  bit0=INIT bit1=NEXT bit2=MODE(1=SHA256,0=SHA224)
//   0x09 STATUS  R    bit0=READY bit1=VALID
//   0x10-0x1F BLOCK0..15  W   512-bit message block
//   0x20-0x27 DIGEST0..7  R   digest (SHA-224 = first 7 words)
//============================================================================
`default_nettype none

module sha256 (
    input  wire        clk,
    input  wire        reset_n,        // synchronous, active-LOW
    input  wire        cs,             // chip select
    input  wire        we,             // 1=write 0=read
    input  wire [7:0]  address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error
);

    //------------------------------------------------------------------
    // Register addresses (L5)
    //------------------------------------------------------------------
    localparam [7:0] ADDR_NAME0   = 8'h00,
                     ADDR_NAME1   = 8'h01,
                     ADDR_VERSION = 8'h02,
                     ADDR_CTRL    = 8'h08,
                     ADDR_STATUS  = 8'h09,
                     ADDR_BLOCK0  = 8'h10,   // .. 0x1F
                     ADDR_BLOCK15 = 8'h1F,
                     ADDR_DIGEST0 = 8'h20,   // .. 0x27
                     ADDR_DIGEST7 = 8'h27;

    // Chip identity (ASCII "sha2" / "56  " split across two words, version).
    localparam [31:0] CORE_NAME0   = 32'h73686132;  // "sha2"
    localparam [31:0] CORE_NAME1   = 32'h35362020;  // "56  "
    localparam [31:0] CORE_VERSION = 32'h302e3830;  // "0.80"

    localparam CTRL_INIT = 0, CTRL_NEXT = 1, CTRL_MODE = 2;
    localparam STATUS_READY = 0, STATUS_VALID = 1;

    //------------------------------------------------------------------
    // Register-file storage
    //------------------------------------------------------------------
    reg [31:0] block_reg [0:15];          // BLOCK0..15
    reg        init_reg, next_reg, mode_reg;

    // pulses to core (1-cycle)
    reg core_init, core_next;

    //------------------------------------------------------------------
    // Hash core
    //------------------------------------------------------------------
    wire         core_ready;
    wire [255:0] core_digest;
    wire         core_valid;
    wire [511:0] block_bus;

    // pack BLOCK0..15 into 512-bit bus, BLOCK0 = most-significant word
    assign block_bus = { block_reg[0],  block_reg[1],  block_reg[2],  block_reg[3],
                         block_reg[4],  block_reg[5],  block_reg[6],  block_reg[7],
                         block_reg[8],  block_reg[9],  block_reg[10], block_reg[11],
                         block_reg[12], block_reg[13], block_reg[14], block_reg[15] };

    sha256_core core (
        .clk          (clk),
        .reset_n      (reset_n),
        .init         (core_init),
        .next         (core_next),
        .mode         (mode_reg),
        .block        (block_bus),
        .ready        (core_ready),
        .digest       (core_digest),
        .digest_valid (core_valid)
    );

    //------------------------------------------------------------------
    // Write path + control pulse generation
    //------------------------------------------------------------------
    integer j;
    always @(posedge clk) begin
        if (!reset_n) begin
            core_init <= 1'b0;
            core_next <= 1'b0;
            init_reg  <= 1'b0;
            next_reg  <= 1'b0;
            mode_reg  <= 1'b1;            // default SHA-256
            for (j=0;j<16;j=j+1) block_reg[j] <= 32'b0;
        end else begin
            // control pulses are single-cycle
            core_init <= 1'b0;
            core_next <= 1'b0;
            init_reg  <= 1'b0;
            next_reg  <= 1'b0;

            if (cs && we) begin
                if (address == ADDR_CTRL) begin
                    init_reg <= write_data[CTRL_INIT];
                    next_reg <= write_data[CTRL_NEXT];
                    mode_reg <= write_data[CTRL_MODE];
                    // INIT has priority over NEXT (L5 note). Only launch
                    // the core when idle to avoid corrupting an in-flight hash.
                    if (core_ready) begin
                        if (write_data[CTRL_INIT])      core_init <= 1'b1;
                        else if (write_data[CTRL_NEXT]) core_next <= 1'b1;
                    end
                end else if (address >= ADDR_BLOCK0 && address <= ADDR_BLOCK15) begin
                    block_reg[address[3:0]] <= write_data;
                end
                // writes to other addresses are ignored
            end
        end
    end

    //------------------------------------------------------------------
    // Read path + error flag (combinational)
    //------------------------------------------------------------------
    always @(*) begin
        read_data = 32'h0;
        error     = 1'b0;
        if (cs && !we) begin
            case (address)
                ADDR_NAME0:   read_data = CORE_NAME0;
                ADDR_NAME1:   read_data = CORE_NAME1;
                ADDR_VERSION: read_data = CORE_VERSION;
                ADDR_CTRL:    read_data = {29'b0, mode_reg, next_reg, init_reg};
                ADDR_STATUS:  read_data = {30'b0, core_valid, core_ready};
                default: begin
                    if (address >= ADDR_DIGEST0 && address <= ADDR_DIGEST7) begin
                        // DIGEST0 = top 32 bits of digest (H0). In SHA-224 mode
                        // (mode_reg=0) the digest is only the first 7 words
                        // (224 bits), so DIGEST7 is not part of the result and
                        // reads back 0 (per L4/L5 "SHA-224 取前 7").
                        if (address[2:0] == 3'd7 && !mode_reg)
                            read_data = 32'h0;
                        else
                            read_data = core_digest[(7-(address[2:0]))*32 +: 32];
                    end else begin
                        // undefined address read => error
                        read_data = 32'h0;
                        error     = 1'b1;
                    end
                end
            endcase
        end
    end

endmodule

`default_nettype wire
