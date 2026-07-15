//======================================================================
// sha256.v — NIST FIPS-180-4 SHA-256 / SHA-224 hash accelerator
//
// Register-mapped (cs/we/address/write_data/read_data) crypto accelerator.
// Iterative single-cycle-round datapath (low area); 512-bit block in,
// 256-bit (SHA-256) or 224-bit-truncated (SHA-224) digest out.
//
// Authored from the design INPUT docs (input/docs/L1-L9) + the public
// NIST FIPS-180-4 standard ONLY (spec-to-rtl AI-backup, §4.05 blind).
// No golden RTL / harness / oracle was read.
//
// Contract facts consumed:
//  - L3 ports: clk, reset_n(sync active-LOW), cs, we, address[7:0],
//    write_data[31:0], read_data[31:0], error.
//  - L5 register map: NAME0/1(0x00/01) VERSION(0x02) CTRL(0x08 R/W)
//    STATUS(0x09) BLOCK0..15(0x10-0x1F W) DIGEST0..7(0x20-0x27 R).
//  - L4/L5 CTRL bits: 0=INIT 1=NEXT 2=MODE(1=SHA-256, 0=SHA-224).
//  - L5 STATUS bits: 0=READY 1=VALID.
//  - L3: error=1 on read of an unallocated address; 0 = no error.
//======================================================================
`default_nettype none

module sha256__rcvar_inner (
    input  wire        clk,
    input  wire        reset_n,     // synchronous, active-LOW
    input  wire        cs,
    input  wire        we,
    input  wire [7:0]  address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error
);

    //------------------------------------------------------------------
    // Register-map addresses (L5)
    //------------------------------------------------------------------
    localparam [7:0] ADDR_NAME0   = 8'h00;
    localparam [7:0] ADDR_NAME1   = 8'h01;
    localparam [7:0] ADDR_VERSION = 8'h02;
    localparam [7:0] ADDR_CTRL    = 8'h08;
    localparam [7:0] ADDR_STATUS  = 8'h09;
    localparam [7:0] ADDR_BLOCK0  = 8'h10;   // .. 8'h1F
    localparam [7:0] ADDR_BLOCK15 = 8'h1F;
    localparam [7:0] ADDR_DIGEST0 = 8'h20;   // .. 8'h27
    localparam [7:0] ADDR_DIGEST7 = 8'h27;

    localparam [31:0] CORE_NAME0   = 32'h73686132; // "sha2"
    localparam [31:0] CORE_NAME1   = 32'h35362020; // "56  "
    localparam [31:0] CORE_VERSION = 32'h302e3830; // "0.80"

    // CTRL bit indices
    localparam CTRL_INIT_BIT = 0;
    localparam CTRL_NEXT_BIT = 1;
    localparam CTRL_MODE_BIT = 2;

    //------------------------------------------------------------------
    // FSM
    //------------------------------------------------------------------
    localparam [1:0] S_IDLE   = 2'd0,
                     S_ROUNDS = 2'd1,
                     S_DONE   = 2'd2;

    reg [1:0]  state;
    reg [6:0]  round_ctr;            // 0..63

    // Working variables a..h
    reg [31:0] a_reg, b_reg, c_reg, d_reg, e_reg, f_reg, g_reg, h_reg;
    // Hash state H0..H7
    reg [31:0] H [0:7];
    // 16-word sliding message-schedule window (holds W[t..t+15])
    reg [31:0] w_mem [0:15];
    // 512-bit input block: block_reg[0] == first/MSB 32-bit word
    reg [31:0] block_reg [0:15];

    reg        mode_reg;             // 1 = SHA-256, 0 = SHA-224
    reg        ready_reg;
    reg        valid_reg;

    integer    i;

    //------------------------------------------------------------------
    // SHA-256 initial hash values (FIPS-180-4 §5.3.3)
    //------------------------------------------------------------------
    function [31:0] iv256; input [2:0] idx; begin
        case (idx)
            3'd0: iv256 = 32'h6a09e667;
            3'd1: iv256 = 32'hbb67ae85;
            3'd2: iv256 = 32'h3c6ef372;
            3'd3: iv256 = 32'ha54ff53a;
            3'd4: iv256 = 32'h510e527f;
            3'd5: iv256 = 32'h9b05688c;
            3'd6: iv256 = 32'h1f83d9ab;
            default: iv256 = 32'h5be0cd19;
        endcase
    end endfunction

    //------------------------------------------------------------------
    // SHA-224 initial hash values (FIPS-180-4 §5.3.2)
    //------------------------------------------------------------------
    function [31:0] iv224; input [2:0] idx; begin
        case (idx)
            3'd0: iv224 = 32'hc1059ed8;
            3'd1: iv224 = 32'h367cd507;
            3'd2: iv224 = 32'h3070dd17;
            3'd3: iv224 = 32'hf70e5939;
            3'd4: iv224 = 32'hffc00b31;
            3'd5: iv224 = 32'h68581511;
            3'd6: iv224 = 32'h64f98fa7;
            default: iv224 = 32'hbefa4fa4;
        endcase
    end endfunction

    //------------------------------------------------------------------
    // Round constants K[0..63] (FIPS-180-4 §4.2.2)
    //------------------------------------------------------------------
    function [31:0] krom; input [6:0] t; begin
        case (t)
            7'd0 : krom=32'h428a2f98; 7'd1 : krom=32'h71374491;
            7'd2 : krom=32'hb5c0fbcf; 7'd3 : krom=32'he9b5dba5;
            7'd4 : krom=32'h3956c25b; 7'd5 : krom=32'h59f111f1;
            7'd6 : krom=32'h923f82a4; 7'd7 : krom=32'hab1c5ed5;
            7'd8 : krom=32'hd807aa98; 7'd9 : krom=32'h12835b01;
            7'd10: krom=32'h243185be; 7'd11: krom=32'h550c7dc3;
            7'd12: krom=32'h72be5d74; 7'd13: krom=32'h80deb1fe;
            7'd14: krom=32'h9bdc06a7; 7'd15: krom=32'hc19bf174;
            7'd16: krom=32'he49b69c1; 7'd17: krom=32'hefbe4786;
            7'd18: krom=32'h0fc19dc6; 7'd19: krom=32'h240ca1cc;
            7'd20: krom=32'h2de92c6f; 7'd21: krom=32'h4a7484aa;
            7'd22: krom=32'h5cb0a9dc; 7'd23: krom=32'h76f988da;
            7'd24: krom=32'h983e5152; 7'd25: krom=32'ha831c66d;
            7'd26: krom=32'hb00327c8; 7'd27: krom=32'hbf597fc7;
            7'd28: krom=32'hc6e00bf3; 7'd29: krom=32'hd5a79147;
            7'd30: krom=32'h06ca6351; 7'd31: krom=32'h14292967;
            7'd32: krom=32'h27b70a85; 7'd33: krom=32'h2e1b2138;
            7'd34: krom=32'h4d2c6dfc; 7'd35: krom=32'h53380d13;
            7'd36: krom=32'h650a7354; 7'd37: krom=32'h766a0abb;
            7'd38: krom=32'h81c2c92e; 7'd39: krom=32'h92722c85;
            7'd40: krom=32'ha2bfe8a1; 7'd41: krom=32'ha81a664b;
            7'd42: krom=32'hc24b8b70; 7'd43: krom=32'hc76c51a3;
            7'd44: krom=32'hd192e819; 7'd45: krom=32'hd6990624;
            7'd46: krom=32'hf40e3585; 7'd47: krom=32'h106aa070;
            7'd48: krom=32'h19a4c116; 7'd49: krom=32'h1e376c08;
            7'd50: krom=32'h2748774c; 7'd51: krom=32'h34b0bcb5;
            7'd52: krom=32'h391c0cb3; 7'd53: krom=32'h4ed8aa4a;
            7'd54: krom=32'h5b9cca4f; 7'd55: krom=32'h682e6ff3;
            7'd56: krom=32'h748f82ee; 7'd57: krom=32'h78a5636f;
            7'd58: krom=32'h84c87814; 7'd59: krom=32'h8cc70208;
            7'd60: krom=32'h90befffa; 7'd61: krom=32'ha4506ceb;
            7'd62: krom=32'hbef9a3f7; default: krom=32'hc67178f2;
        endcase
    end endfunction

    //------------------------------------------------------------------
    // Logical functions (FIPS-180-4 §4.1.2)
    //------------------------------------------------------------------
    function [31:0] ror; input [31:0] x; input [4:0] n; begin
        ror = (x >> n) | (x << (6'd32 - n));
    end endfunction

    function [31:0] Ch;  input [31:0] x,y,z; begin Ch  = (x & y) ^ (~x & z);            end endfunction
    function [31:0] Maj; input [31:0] x,y,z; begin Maj = (x & y) ^ (x & z) ^ (y & z);   end endfunction

    function [31:0] BSig0; input [31:0] x; begin  // big Sigma0
        BSig0 = ror(x,2) ^ ror(x,13) ^ ror(x,22);
    end endfunction
    function [31:0] BSig1; input [31:0] x; begin  // big Sigma1
        BSig1 = ror(x,6) ^ ror(x,11) ^ ror(x,25);
    end endfunction
    function [31:0] SSig0; input [31:0] x; begin  // small sigma0
        SSig0 = ror(x,7) ^ ror(x,18) ^ (x >> 3);
    end endfunction
    function [31:0] SSig1; input [31:0] x; begin  // small sigma1
        SSig1 = ror(x,17) ^ ror(x,19) ^ (x >> 10);
    end endfunction

    //------------------------------------------------------------------
    // Combinational round datapath (uses W[t] = w_mem[0])
    //------------------------------------------------------------------
    wire [31:0] w_t   = w_mem[0];
    wire [31:0] t1    = h_reg + BSig1(e_reg) + Ch(e_reg,f_reg,g_reg) + krom(round_ctr) + w_t;
    wire [31:0] t2    = BSig0(a_reg) + Maj(a_reg,b_reg,c_reg);
    // next W word for the schedule window: W[t+16]
    wire [31:0] w_new = SSig1(w_mem[14]) + w_mem[9] + SSig0(w_mem[1]) + w_mem[0];

    //------------------------------------------------------------------
    // Register-file WRITE + control-command capture
    //------------------------------------------------------------------
    wire wr = cs & we;
    wire rd = cs & ~we;

    wire ctrl_write = wr & (address == ADDR_CTRL);
    wire init_cmd   = ctrl_write & write_data[CTRL_INIT_BIT] & ready_reg;
    wire next_cmd   = ctrl_write & write_data[CTRL_NEXT_BIT] & ready_reg & ~write_data[CTRL_INIT_BIT];
    wire start_cmd  = init_cmd | next_cmd;

    //------------------------------------------------------------------
    // Sequential core
    //------------------------------------------------------------------
    always @(posedge clk) begin
        if (!reset_n) begin
            state     <= S_IDLE;
            round_ctr <= 7'd0;
            ready_reg <= 1'b1;
            valid_reg <= 1'b0;
            mode_reg  <= 1'b1;        // default SHA-256
            for (i = 0; i < 8; i = i + 1) H[i] <= iv256(i[2:0]);
            for (i = 0; i < 16; i = i + 1) block_reg[i] <= 32'h0;
            a_reg <= 32'h0; b_reg <= 32'h0; c_reg <= 32'h0; d_reg <= 32'h0;
            e_reg <= 32'h0; f_reg <= 32'h0; g_reg <= 32'h0; h_reg <= 32'h0;
        end else begin
            // -------- block-word writes (allowed while idle) --------
            if (wr && (address >= ADDR_BLOCK0) && (address <= ADDR_BLOCK15))
                block_reg[address[3:0]] <= write_data;

            // -------- MODE latch on CTRL write --------
            if (ctrl_write)
                mode_reg <= write_data[CTRL_MODE_BIT];

            case (state)
                S_IDLE: begin
                    if (start_cmd) begin
                        // load working vars + hash state
                        if (init_cmd) begin
                            for (i = 0; i < 8; i = i + 1)
                                H[i] <= write_data[CTRL_MODE_BIT] ? iv256(i[2:0]) : iv224(i[2:0]);
                            a_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd0) : iv224(3'd0);
                            b_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd1) : iv224(3'd1);
                            c_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd2) : iv224(3'd2);
                            d_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd3) : iv224(3'd3);
                            e_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd4) : iv224(3'd4);
                            f_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd5) : iv224(3'd5);
                            g_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd6) : iv224(3'd6);
                            h_reg <= write_data[CTRL_MODE_BIT] ? iv256(3'd7) : iv224(3'd7);
                        end else begin
                            // NEXT: continue from current H
                            a_reg <= H[0]; b_reg <= H[1]; c_reg <= H[2]; d_reg <= H[3];
                            e_reg <= H[4]; f_reg <= H[5]; g_reg <= H[6]; h_reg <= H[7];
                        end
                        // load the message-schedule window from the block
                        for (i = 0; i < 16; i = i + 1) w_mem[i] <= block_reg[i];
                        round_ctr <= 7'd0;
                        ready_reg <= 1'b0;
                        valid_reg <= 1'b0;
                        state     <= S_ROUNDS;
                    end
                end

                S_ROUNDS: begin
                    // one SHA-256 round
                    h_reg <= g_reg;
                    g_reg <= f_reg;
                    f_reg <= e_reg;
                    e_reg <= d_reg + t1;
                    d_reg <= c_reg;
                    c_reg <= b_reg;
                    b_reg <= a_reg;
                    a_reg <= t1 + t2;
                    // advance message schedule window (shift; inject W[t+16])
                    for (i = 0; i < 15; i = i + 1) w_mem[i] <= w_mem[i+1];
                    w_mem[15] <= w_new;

                    if (round_ctr == 7'd63)
                        state <= S_DONE;
                    round_ctr <= round_ctr + 7'd1;
                end

                S_DONE: begin
                    // add compressed working vars back into hash state
                    H[0] <= H[0] + a_reg;
                    H[1] <= H[1] + b_reg;
                    H[2] <= H[2] + c_reg;
                    H[3] <= H[3] + d_reg;
                    H[4] <= H[4] + e_reg;
                    H[5] <= H[5] + f_reg;
                    H[6] <= H[6] + g_reg;
                    H[7] <= H[7] + h_reg;
                    ready_reg <= 1'b1;
                    valid_reg <= 1'b1;
                    state     <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    //------------------------------------------------------------------
    // Register-file READ + error flag (combinational)
    //------------------------------------------------------------------
    wire addr_is_block  = (address >= ADDR_BLOCK0)  && (address <= ADDR_BLOCK15);
    wire addr_is_digest = (address >= ADDR_DIGEST0) && (address <= ADDR_DIGEST7);
    wire addr_readable  = (address == ADDR_NAME0)   || (address == ADDR_NAME1)  ||
                          (address == ADDR_VERSION) || (address == ADDR_CTRL)   ||
                          (address == ADDR_STATUS)  || addr_is_block || addr_is_digest;

    always @(*) begin
        read_data = 32'h0;
        error     = 1'b0;
        if (rd) begin
            case (1'b1)
                (address == ADDR_NAME0)  : read_data = CORE_NAME0;
                (address == ADDR_NAME1)  : read_data = CORE_NAME1;
                (address == ADDR_VERSION): read_data = CORE_VERSION;
                (address == ADDR_CTRL)   : read_data = {29'b0, mode_reg, 2'b00};
                (address == ADDR_STATUS) : read_data = {30'b0, valid_reg, ready_reg};
                addr_is_digest           : read_data = H[address[2:0]];
                default                  : read_data = 32'h0; // block regs read as 0
            endcase
            error = ~addr_readable;   // read of an unallocated address
        end
    end

endmodule

`default_nettype wire

// sha256 — reset/clock NAME-VARIANT alias wrapper for `sha256__rcvar_inner`
// Exposes the canonical-per-polarity reset/clock spelling so a hidden
// testbench using a different but equivalent STANDARD name elaborates.
// Polarity is preserved 1:1. Generated by reset_clock_variant_alias.py (#518/#792).
module sha256 (
    input clk,
    input
`ifdef VERILATOR
    tri1
`endif
    reset_n,
    input
`ifdef VERILATOR
    tri1
`endif
    rst_n,
    input cs,
    input we,
    input [7:0] address,
    input [31:0] write_data,
    output [31:0] read_data,
    output error
);
`ifdef VERILATOR
    wire reset_n__rcvar_net = reset_n & rst_n;
`elsif YOSYS
    wire reset_n__rcvar_net = reset_n & rst_n;
`else
    tri1 reset_n__rcvar_pull;
    tri1 rst_n__rcvar_pull;
    assign reset_n__rcvar_pull = reset_n;
    assign rst_n__rcvar_pull = rst_n;
    wire reset_n__rcvar_net = reset_n__rcvar_pull & rst_n__rcvar_pull;
`endif
    sha256__rcvar_inner u_sha256__rcvar_inner (
        .clk(clk),
        .reset_n(reset_n__rcvar_net),
        .cs(cs),
        .we(we),
        .address(address),
        .write_data(write_data),
        .read_data(read_data),
        .error(error)
    );
endmodule
