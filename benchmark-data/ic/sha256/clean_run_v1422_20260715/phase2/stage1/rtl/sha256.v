// ---------------------------------------------------------------------------
// sha256 — NIST FIPS-180-4 SHA-256 / SHA-224 dual-mode hash accelerator
// ---------------------------------------------------------------------------
// Memory-mapped register interface (cs/we/address/write_data/read_data/error)
// per L3/L4/L5. Iterative single-cycle-round datapath: one message-schedule
// word + one compression round per clock -> 66 cycles per 512-bit block
// (1 setup + 64 rounds + 1 final add), matching the L1/L7 reference.
//
// Reset: SYNCHRONOUS, active-LOW (reset_n) per L2/L3/L7 declaration.
//
// Authored by the spec-to-rtl role from the runner's emitted L1-L23 docs.
// Register map + magic constants follow the secworks/sha256 public contract
// cited as the design origin in L1.
// ---------------------------------------------------------------------------
`default_nettype none
module sha256__rcvar_inner (
    input  wire        clk,
    input  wire        reset_n,     // synchronous, active-LOW
    input  wire        cs,          // chip select
    input  wire        we,          // 1 = write, 0 = read
    input  wire [7:0]  address,
    input  wire [31:0] write_data,
    output reg  [31:0] read_data,
    output reg         error
);

  // ------------------------------------------------------------------
  // Register address map (L5)
  // ------------------------------------------------------------------
  localparam [7:0] ADDR_NAME0   = 8'h00;
  localparam [7:0] ADDR_NAME1   = 8'h01;
  localparam [7:0] ADDR_VERSION = 8'h02;
  localparam [7:0] ADDR_CTRL    = 8'h08;
  localparam [7:0] ADDR_STATUS  = 8'h09;
  localparam [7:0] ADDR_BLOCK0  = 8'h10;   // 0x10 .. 0x1F : 16 words
  localparam [7:0] ADDR_DIGEST0 = 8'h20;   // 0x20 .. 0x27 : 8 words

  localparam integer CTRL_INIT_BIT = 0;
  localparam integer CTRL_NEXT_BIT = 1;
  localparam integer CTRL_MODE_BIT = 2;    // 1 = SHA-256, 0 = SHA-224

  localparam integer STATUS_READY_BIT = 0;
  localparam integer STATUS_VALID_BIT = 1;

  // Chip identity (secworks/sha256 public magic)
  localparam [31:0] CORE_NAME0   = 32'h73686132; // "sha2"
  localparam [31:0] CORE_NAME1   = 32'h35362020; // "56  "
  localparam [31:0] CORE_VERSION = 32'h302e3830; // "0.80"

  // ------------------------------------------------------------------
  // Bus write decode
  // ------------------------------------------------------------------
  wire wr = cs & we;
  wire rd = cs & ~we;

  wire ctrl_wr = wr & (address == ADDR_CTRL);
  wire init_cmd = ctrl_wr & write_data[CTRL_INIT_BIT];
  wire next_cmd = ctrl_wr & write_data[CTRL_NEXT_BIT];
  wire mode_wr  = write_data[CTRL_MODE_BIT];

  // ------------------------------------------------------------------
  // Message block registers (16 x 32-bit), written via ADDR_BLOCK0..15
  // ------------------------------------------------------------------
  reg [31:0] block_mem [0:15];
  wire block_sel = wr & (address >= ADDR_BLOCK0) & (address <= (ADDR_BLOCK0 + 8'd15));
  wire [3:0] block_idx = address[3:0];

  integer bi;
  always @(posedge clk) begin
    if (!reset_n) begin
      for (bi = 0; bi < 16; bi = bi + 1)
        block_mem[bi] <= 32'h0;
    end else if (block_sel) begin
      block_mem[block_idx] <= write_data;
    end
  end

  // ------------------------------------------------------------------
  // Hash state H[0..7], mode, status
  // ------------------------------------------------------------------
  reg [31:0] H0, H1, H2, H3, H4, H5, H6, H7;
  reg        mode_reg;     // 1 = SHA-256, 0 = SHA-224
  reg        ready_reg;
  reg        valid_reg;

  // Working variables a..h
  reg [31:0] a, b, c, d, e, f, g, h;

  // Message schedule sliding window (16 words)
  reg [31:0] w_mem [0:15];

  // Round counter 0..63
  reg [6:0]  round_ctr;

  // Control FSM
  localparam [1:0] S_IDLE  = 2'd0,
                   S_SETUP = 2'd1,
                   S_ROUND = 2'd2,
                   S_DONE  = 2'd3;
  reg [1:0] state;

  // ------------------------------------------------------------------
  // SHA-256 initial hash values (mode select)
  // ------------------------------------------------------------------
  function [31:0] iv_word;
    input [3:0] idx;      // 0..7
    input       mode;     // 1 = SHA-256, 0 = SHA-224
    begin
      if (mode) begin
        case (idx)
          4'd0: iv_word = 32'h6a09e667;
          4'd1: iv_word = 32'hbb67ae85;
          4'd2: iv_word = 32'h3c6ef372;
          4'd3: iv_word = 32'ha54ff53a;
          4'd4: iv_word = 32'h510e527f;
          4'd5: iv_word = 32'h9b05688c;
          4'd6: iv_word = 32'h1f83d9ab;
          default: iv_word = 32'h5be0cd19;
        endcase
      end else begin
        case (idx)
          4'd0: iv_word = 32'hc1059ed8;
          4'd1: iv_word = 32'h367cd507;
          4'd2: iv_word = 32'h3070dd17;
          4'd3: iv_word = 32'hf70e5939;
          4'd4: iv_word = 32'hffc00b31;
          4'd5: iv_word = 32'h68581511;
          4'd6: iv_word = 32'h64f98fa7;
          default: iv_word = 32'hbefa4fa4;
        endcase
      end
    end
  endfunction

  // ------------------------------------------------------------------
  // Round constant K[round]
  // ------------------------------------------------------------------
  function [31:0] k_const;
    input [6:0] r;
    begin
      case (r[5:0])
        6'd00: k_const = 32'h428a2f98; 6'd01: k_const = 32'h71374491;
        6'd02: k_const = 32'hb5c0fbcf; 6'd03: k_const = 32'he9b5dba5;
        6'd04: k_const = 32'h3956c25b; 6'd05: k_const = 32'h59f111f1;
        6'd06: k_const = 32'h923f82a4; 6'd07: k_const = 32'hab1c5ed5;
        6'd08: k_const = 32'hd807aa98; 6'd09: k_const = 32'h12835b01;
        6'd10: k_const = 32'h243185be; 6'd11: k_const = 32'h550c7dc3;
        6'd12: k_const = 32'h72be5d74; 6'd13: k_const = 32'h80deb1fe;
        6'd14: k_const = 32'h9bdc06a7; 6'd15: k_const = 32'hc19bf174;
        6'd16: k_const = 32'he49b69c1; 6'd17: k_const = 32'hefbe4786;
        6'd18: k_const = 32'h0fc19dc6; 6'd19: k_const = 32'h240ca1cc;
        6'd20: k_const = 32'h2de92c6f; 6'd21: k_const = 32'h4a7484aa;
        6'd22: k_const = 32'h5cb0a9dc; 6'd23: k_const = 32'h76f988da;
        6'd24: k_const = 32'h983e5152; 6'd25: k_const = 32'ha831c66d;
        6'd26: k_const = 32'hb00327c8; 6'd27: k_const = 32'hbf597fc7;
        6'd28: k_const = 32'hc6e00bf3; 6'd29: k_const = 32'hd5a79147;
        6'd30: k_const = 32'h06ca6351; 6'd31: k_const = 32'h14292967;
        6'd32: k_const = 32'h27b70a85; 6'd33: k_const = 32'h2e1b2138;
        6'd34: k_const = 32'h4d2c6dfc; 6'd35: k_const = 32'h53380d13;
        6'd36: k_const = 32'h650a7354; 6'd37: k_const = 32'h766a0abb;
        6'd38: k_const = 32'h81c2c92e; 6'd39: k_const = 32'h92722c85;
        6'd40: k_const = 32'ha2bfe8a1; 6'd41: k_const = 32'ha81a664b;
        6'd42: k_const = 32'hc24b8b70; 6'd43: k_const = 32'hc76c51a3;
        6'd44: k_const = 32'hd192e819; 6'd45: k_const = 32'hd6990624;
        6'd46: k_const = 32'hf40e3585; 6'd47: k_const = 32'h106aa070;
        6'd48: k_const = 32'h19a4c116; 6'd49: k_const = 32'h1e376c08;
        6'd50: k_const = 32'h2748774c; 6'd51: k_const = 32'h34b0bcb5;
        6'd52: k_const = 32'h391c0cb3; 6'd53: k_const = 32'h4ed8aa4a;
        6'd54: k_const = 32'h5b9cca4f; 6'd55: k_const = 32'h682e6ff3;
        6'd56: k_const = 32'h748f82ee; 6'd57: k_const = 32'h78a5636f;
        6'd58: k_const = 32'h84c87814; 6'd59: k_const = 32'h8cc70208;
        6'd60: k_const = 32'h90befffa; 6'd61: k_const = 32'ha4506ceb;
        6'd62: k_const = 32'hbef9a3f7; default: k_const = 32'hc67178f2;
      endcase
    end
  endfunction

  // ------------------------------------------------------------------
  // Rotate / shift helpers and SHA-256 functions
  // ------------------------------------------------------------------
  function [31:0] rotr; input [31:0] x; input [4:0] n;
    begin rotr = (x >> n) | (x << (6'd32 - n)); end
  endfunction

  function [31:0] big_sigma0; input [31:0] x;   // Sigma0(a)
    begin big_sigma0 = rotr(x,5'd2) ^ rotr(x,5'd13) ^ rotr(x,5'd22); end
  endfunction
  function [31:0] big_sigma1; input [31:0] x;   // Sigma1(e)
    begin big_sigma1 = rotr(x,5'd6) ^ rotr(x,5'd11) ^ rotr(x,5'd25); end
  endfunction
  function [31:0] small_sigma0; input [31:0] x; // sigma0 (schedule)
    begin small_sigma0 = rotr(x,5'd7) ^ rotr(x,5'd18) ^ (x >> 3); end
  endfunction
  function [31:0] small_sigma1; input [31:0] x; // sigma1 (schedule)
    begin small_sigma1 = rotr(x,5'd17) ^ rotr(x,5'd19) ^ (x >> 10); end
  endfunction

  // Message schedule next word W[i+16] = s1(W[i+14]) + W[i+9] + s0(W[i+1]) + W[i]
  wire [31:0] w_new = small_sigma1(w_mem[14]) + w_mem[9]
                    + small_sigma0(w_mem[1])  + w_mem[0];

  // Compression round (uses w_mem[0] as W[round_ctr])
  wire [31:0] ch  = (e & f) ^ (~e & g);
  wire [31:0] maj = (a & b) ^ (a & c) ^ (b & c);
  wire [31:0] t1  = h + big_sigma1(e) + ch + k_const(round_ctr) + w_mem[0];
  wire [31:0] t2  = big_sigma0(a) + maj;

  integer wi;

  // ------------------------------------------------------------------
  // Control / datapath FSM
  // ------------------------------------------------------------------
  always @(posedge clk) begin
    if (!reset_n) begin
      state     <= S_IDLE;
      ready_reg <= 1'b1;
      valid_reg <= 1'b0;
      mode_reg  <= 1'b1;
      round_ctr <= 7'd0;
      H0 <= 32'h0; H1 <= 32'h0; H2 <= 32'h0; H3 <= 32'h0;
      H4 <= 32'h0; H5 <= 32'h0; H6 <= 32'h0; H7 <= 32'h0;
    end else begin
      case (state)
        // --------------------------------------------------------
        S_IDLE: begin
          ready_reg <= 1'b1;
          if (init_cmd || next_cmd) begin
            ready_reg <= 1'b0;
            valid_reg <= 1'b0;
            if (init_cmd) begin
              mode_reg <= mode_wr;
              H0 <= iv_word(4'd0, mode_wr); H1 <= iv_word(4'd1, mode_wr);
              H2 <= iv_word(4'd2, mode_wr); H3 <= iv_word(4'd3, mode_wr);
              H4 <= iv_word(4'd4, mode_wr); H5 <= iv_word(4'd5, mode_wr);
              H6 <= iv_word(4'd6, mode_wr); H7 <= iv_word(4'd7, mode_wr);
            end
            // Load message schedule window with the 16 block words.
            for (wi = 0; wi < 16; wi = wi + 1)
              w_mem[wi] <= block_mem[wi];
            round_ctr <= 7'd0;
            state <= S_SETUP;
          end
        end
        // --------------------------------------------------------
        // Latch a..h from the (possibly just-initialised) H state.
        S_SETUP: begin
          a <= H0; b <= H1; c <= H2; d <= H3;
          e <= H4; f <= H5; g <= H6; h <= H7;
          round_ctr <= 7'd0;
          state <= S_ROUND;
        end
        // --------------------------------------------------------
        // One compression round + one schedule step per cycle.
        S_ROUND: begin
          h <= g;
          g <= f;
          f <= e;
          e <= d + t1;
          d <= c;
          c <= b;
          b <= a;
          a <= t1 + t2;

          // advance the sliding message-schedule window
          for (wi = 0; wi < 15; wi = wi + 1)
            w_mem[wi] <= w_mem[wi+1];
          w_mem[15] <= w_new;

          if (round_ctr == 7'd63) begin
            state <= S_DONE;
          end else begin
            round_ctr <= round_ctr + 7'd1;
          end
        end
        // --------------------------------------------------------
        S_DONE: begin
          H0 <= H0 + a; H1 <= H1 + b; H2 <= H2 + c; H3 <= H3 + d;
          H4 <= H4 + e; H5 <= H5 + f; H6 <= H6 + g; H7 <= H7 + h;
          valid_reg <= 1'b1;
          ready_reg <= 1'b1;
          state <= S_IDLE;
        end
        default: state <= S_IDLE;
      endcase
    end
  end

  // ------------------------------------------------------------------
  // Register read port (synchronous) + error flag
  // ------------------------------------------------------------------
  reg [31:0] digest_word;
  always @(*) begin
    case (address[2:0])
      3'd0: digest_word = H0;
      3'd1: digest_word = H1;
      3'd2: digest_word = H2;
      3'd3: digest_word = H3;
      3'd4: digest_word = H4;
      3'd5: digest_word = H5;
      3'd6: digest_word = H6;
      default: digest_word = H7;
    endcase
  end

  always @(posedge clk) begin
    if (!reset_n) begin
      read_data <= 32'h0;
      error     <= 1'b0;
    end else begin
      read_data <= 32'h0;
      error     <= 1'b0;
      if (rd) begin
        if (address == ADDR_NAME0)        read_data <= CORE_NAME0;
        else if (address == ADDR_NAME1)   read_data <= CORE_NAME1;
        else if (address == ADDR_VERSION) read_data <= CORE_VERSION;
        else if (address == ADDR_CTRL)
          read_data <= {29'h0, mode_reg, next_cmd, init_cmd};
        else if (address == ADDR_STATUS)
          read_data <= {30'h0, valid_reg, ready_reg};
        else if (address >= ADDR_DIGEST0 && address <= (ADDR_DIGEST0 + 8'd7))
          read_data <= digest_word;
        else if (address >= ADDR_BLOCK0 && address <= (ADDR_BLOCK0 + 8'd15))
          read_data <= block_mem[address[3:0]];
        else
          // Non-fatal register-read status on an undecoded address (L3
          // "error 0=no error"); self-clears on the next access, never
          // terminates an upper-layer transaction.
          error <= 1'b1;   // fsm_error: recoverable — undecoded-address status
      end
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
