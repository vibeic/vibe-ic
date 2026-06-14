//======================================================================
// sha256.v  -- NIST FIPS-180-4 SHA-256 / SHA-224 hash accelerator
//
// Authored fresh from L1-L9 spec (clean-room). No vendor RTL referenced.
//
// External contract (L3):
//   clk, reset_n(sync active-LOW), cs, we, address[7:0],
//   write_data[31:0], read_data[31:0], error
//
// Register map (L4/L5):
//   0x00 NAME0   (R) chip id word0
//   0x01 NAME1   (R) chip id word1
//   0x02 VERSION (R)
//   0x08 CTRL    (R/W) bit0=INIT bit1=NEXT bit2=MODE(1=SHA256,0=SHA224)
//   0x09 STATUS  (R)   bit0=READY bit1=VALID
//   0x10-0x1F BLOCK0..15  (W) 512-bit message block (16 x 32-bit)
//   0x20-0x27 DIGEST0..7  (R) 256-bit digest (SHA-224 uses first 7)
//
// Algorithm: iterative single-cycle round (reference-style), 64 rounds.
// Padding is performed by SW (per L2): the block presented is already padded.
//======================================================================

`default_nettype none

module sha256 (
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
    // Address map (L5)
    //------------------------------------------------------------------
    localparam [7:0] ADDR_NAME0   = 8'h00;
    localparam [7:0] ADDR_NAME1   = 8'h01;
    localparam [7:0] ADDR_VERSION = 8'h02;
    localparam [7:0] ADDR_CTRL    = 8'h08;
    localparam [7:0] ADDR_STATUS  = 8'h09;
    localparam [7:0] ADDR_BLOCK0  = 8'h10;   // .. 0x1F (16 words)
    localparam [7:0] ADDR_BLOCK15 = 8'h1F;
    localparam [7:0] ADDR_DIGEST0 = 8'h20;   // .. 0x27 (8 words)
    localparam [7:0] ADDR_DIGEST7 = 8'h27;

    // Read-only identity constants
    localparam [31:0] NAME0_VALUE   = 32'h73686132;  // "sha2"
    localparam [31:0] NAME1_VALUE   = 32'h35362020;  // "56  "
    localparam [31:0] VERSION_VALUE = 32'h302e3830;  // "0.80"

    // CTRL bit positions
    localparam CTRL_INIT_BIT = 0;
    localparam CTRL_NEXT_BIT = 1;
    localparam CTRL_MODE_BIT = 2;
    // STATUS bit positions
    localparam STATUS_READY_BIT = 0;
    localparam STATUS_VALID_BIT = 1;

    //------------------------------------------------------------------
    // SW-visible register storage
    //------------------------------------------------------------------
    reg [31:0] block_reg [0:15];      // BLOCK0..15
    reg [31:0] digest_reg [0:7];      // DIGEST0..7 (latched result)
    reg        mode_reg;              // 1 = SHA-256, 0 = SHA-224
    reg        ready_reg;             // STATUS bit0
    reg        valid_reg;             // STATUS bit1

    // one-shot command pulses derived from CTRL writes
    reg        init_cmd;
    reg        next_cmd;

    //------------------------------------------------------------------
    // SHA-256 round constants K[0..63] (NIST FIPS-180-4 sec 4.2.2)
    //------------------------------------------------------------------
    function [31:0] kval;
        input [5:0] idx;
        begin
            case (idx)
                6'd0:  kval = 32'h428a2f98; 6'd1:  kval = 32'h71374491;
                6'd2:  kval = 32'hb5c0fbcf; 6'd3:  kval = 32'he9b5dba5;
                6'd4:  kval = 32'h3956c25b; 6'd5:  kval = 32'h59f111f1;
                6'd6:  kval = 32'h923f82a4; 6'd7:  kval = 32'hab1c5ed5;
                6'd8:  kval = 32'hd807aa98; 6'd9:  kval = 32'h12835b01;
                6'd10: kval = 32'h243185be; 6'd11: kval = 32'h550c7dc3;
                6'd12: kval = 32'h72be5d74; 6'd13: kval = 32'h80deb1fe;
                6'd14: kval = 32'h9bdc06a7; 6'd15: kval = 32'hc19bf174;
                6'd16: kval = 32'he49b69c1; 6'd17: kval = 32'hefbe4786;
                6'd18: kval = 32'h0fc19dc6; 6'd19: kval = 32'h240ca1cc;
                6'd20: kval = 32'h2de92c6f; 6'd21: kval = 32'h4a7484aa;
                6'd22: kval = 32'h5cb0a9dc; 6'd23: kval = 32'h76f988da;
                6'd24: kval = 32'h983e5152; 6'd25: kval = 32'ha831c66d;
                6'd26: kval = 32'hb00327c8; 6'd27: kval = 32'hbf597fc7;
                6'd28: kval = 32'hc6e00bf3; 6'd29: kval = 32'hd5a79147;
                6'd30: kval = 32'h06ca6351; 6'd31: kval = 32'h14292967;
                6'd32: kval = 32'h27b70a85; 6'd33: kval = 32'h2e1b2138;
                6'd34: kval = 32'h4d2c6dfc; 6'd35: kval = 32'h53380d13;
                6'd36: kval = 32'h650a7354; 6'd37: kval = 32'h766a0abb;
                6'd38: kval = 32'h81c2c92e; 6'd39: kval = 32'h92722c85;
                6'd40: kval = 32'ha2bfe8a1; 6'd41: kval = 32'ha81a664b;
                6'd42: kval = 32'hc24b8b70; 6'd43: kval = 32'hc76c51a3;
                6'd44: kval = 32'hd192e819; 6'd45: kval = 32'hd6990624;
                6'd46: kval = 32'hf40e3585; 6'd47: kval = 32'h106aa070;
                6'd48: kval = 32'h19a4c116; 6'd49: kval = 32'h1e376c08;
                6'd50: kval = 32'h2748774c; 6'd51: kval = 32'h34b0bcb5;
                6'd52: kval = 32'h391c0cb3; 6'd53: kval = 32'h4ed8aa4a;
                6'd54: kval = 32'h5b9cca4f; 6'd55: kval = 32'h682e6ff3;
                6'd56: kval = 32'h748f82ee; 6'd57: kval = 32'h78a5636f;
                6'd58: kval = 32'h84c87814; 6'd59: kval = 32'h8cc70208;
                6'd60: kval = 32'h90befffa; 6'd61: kval = 32'ha4506ceb;
                6'd62: kval = 32'hbef9a3f7; 6'd63: kval = 32'hc67178f2;
                default: kval = 32'h0;
            endcase
        end
    endfunction

    //------------------------------------------------------------------
    // SHA-256 helper functions (NIST FIPS-180-4 sec 4.1.2)
    //------------------------------------------------------------------
    function [31:0] rotr; input [31:0] x; input [4:0] n;
        begin rotr = (x >> n) | (x << (6'd32 - n)); end
    endfunction
    function [31:0] shr; input [31:0] x; input [4:0] n;
        begin shr = (x >> n); end
    endfunction
    function [31:0] ch; input [31:0] x,y,z;
        begin ch = (x & y) ^ (~x & z); end
    endfunction
    function [31:0] maj; input [31:0] x,y,z;
        begin maj = (x & y) ^ (x & z) ^ (y & z); end
    endfunction
    function [31:0] big_sigma0; input [31:0] x;
        begin big_sigma0 = rotr(x,5'd2) ^ rotr(x,5'd13) ^ rotr(x,5'd22); end
    endfunction
    function [31:0] big_sigma1; input [31:0] x;
        begin big_sigma1 = rotr(x,5'd6) ^ rotr(x,5'd11) ^ rotr(x,5'd25); end
    endfunction
    function [31:0] small_sigma0; input [31:0] x;
        begin small_sigma0 = rotr(x,5'd7) ^ rotr(x,5'd18) ^ shr(x,5'd3); end
    endfunction
    function [31:0] small_sigma1; input [31:0] x;
        begin small_sigma1 = rotr(x,5'd17) ^ rotr(x,5'd19) ^ shr(x,5'd10); end
    endfunction

    // NIST initial hash values H0..H7 for SHA-256 / SHA-224
    function [31:0] h_init256; input [2:0] i;
        begin
            case (i)
                3'd0: h_init256 = 32'h6a09e667; 3'd1: h_init256 = 32'hbb67ae85;
                3'd2: h_init256 = 32'h3c6ef372; 3'd3: h_init256 = 32'ha54ff53a;
                3'd4: h_init256 = 32'h510e527f; 3'd5: h_init256 = 32'h9b05688c;
                3'd6: h_init256 = 32'h1f83d9ab; 3'd7: h_init256 = 32'h5be0cd19;
                default: h_init256 = 32'h0;
            endcase
        end
    endfunction
    function [31:0] h_init224; input [2:0] i;
        begin
            case (i)
                3'd0: h_init224 = 32'hc1059ed8; 3'd1: h_init224 = 32'h367cd507;
                3'd2: h_init224 = 32'h3070dd17; 3'd3: h_init224 = 32'hf70e5939;
                3'd4: h_init224 = 32'hffc00b31; 3'd5: h_init224 = 32'h68581511;
                3'd6: h_init224 = 32'h64f98fa7; 3'd7: h_init224 = 32'hbefa4fa4;
                default: h_init224 = 32'h0;
            endcase
        end
    endfunction

    //------------------------------------------------------------------
    // Core datapath state
    //------------------------------------------------------------------
    // FSM
    localparam [1:0] S_IDLE   = 2'd0;
    localparam [1:0] S_ROUNDS = 2'd1;
    localparam [1:0] S_FINAL  = 2'd2;
    reg [1:0]  state;

    reg [31:0] H0,H1,H2,H3,H4,H5,H6,H7;          // persistent chained hash
    reg [31:0] a,b,c,d,e,f,g,h;                  // working variables
    reg [31:0] W [0:15];                          // 16-deep rolling W window
    reg [6:0]  round;                             // 0..63 (need 7 bits)

    integer    n;

    // combinational message-schedule word for the current round
    wire [31:0] w_new = small_sigma1(W[14]) + W[9] + small_sigma0(W[1]) + W[0];
    wire [31:0] w_cur = W[0];

    // round temporaries
    wire [31:0] t1 = h + big_sigma1(e) + ch(e,f,g) + kval(round[5:0]) + w_cur;
    wire [31:0] t2 = big_sigma0(a) + maj(a,b,c);

    //------------------------------------------------------------------
    // Register-file read (combinational), with error flag
    //------------------------------------------------------------------
    always @(*) begin
        read_data = 32'h0;
        error     = 1'b0;
        if (cs && !we) begin
            if (address == ADDR_NAME0)        read_data = NAME0_VALUE;
            else if (address == ADDR_NAME1)   read_data = NAME1_VALUE;
            else if (address == ADDR_VERSION) read_data = VERSION_VALUE;
            else if (address == ADDR_CTRL)    read_data = {29'b0, mode_reg, next_cmd, init_cmd};
            else if (address == ADDR_STATUS)  read_data = {30'b0, valid_reg, ready_reg};
            else if (address >= ADDR_DIGEST0 && address <= ADDR_DIGEST7)
                                              read_data = digest_reg[address[2:0]];
            else if (address >= ADDR_BLOCK0 && address <= ADDR_BLOCK15)
                                              read_data = block_reg[address[3:0]];
            else begin
                read_data = 32'h0;
                error     = 1'b1;   // undefined address read
            end
        end
    end

    //------------------------------------------------------------------
    // Sequential: register writes + hash FSM (synchronous active-LOW reset)
    //------------------------------------------------------------------
    always @(posedge clk) begin
        if (!reset_n) begin
            // reset: idle, register file defaults, READY=1
            state     <= S_IDLE;
            ready_reg <= 1'b1;
            valid_reg <= 1'b0;
            mode_reg  <= 1'b1;       // default SHA-256
            init_cmd  <= 1'b0;
            next_cmd  <= 1'b0;
            round     <= 7'd0;
            for (n = 0; n < 16; n = n + 1) block_reg[n] <= 32'h0;
            for (n = 0; n < 8;  n = n + 1) digest_reg[n] <= 32'h0;
            H0 <= 32'h0; H1 <= 32'h0; H2 <= 32'h0; H3 <= 32'h0;
            H4 <= 32'h0; H5 <= 32'h0; H6 <= 32'h0; H7 <= 32'h0;
        end else begin
            // default: clear one-shot command pulses each cycle
            init_cmd <= 1'b0;
            next_cmd <= 1'b0;

            //--------------------------------------------------------------
            // SW register writes (only when idle/ready for control; block
            // writes allowed any time but spec uses them while READY)
            //--------------------------------------------------------------
            if (cs && we) begin
                if (address >= ADDR_BLOCK0 && address <= ADDR_BLOCK15) begin
                    block_reg[address[3:0]] <= write_data;
                end else if (address == ADDR_CTRL) begin
                    mode_reg <= write_data[CTRL_MODE_BIT];
                    // INIT priority over NEXT (per L5 note)
                    if (write_data[CTRL_INIT_BIT])      init_cmd <= 1'b1;
                    else if (write_data[CTRL_NEXT_BIT]) next_cmd <= 1'b1;
                end
                // other addresses: read-only / reserved -> ignore writes
            end

            //--------------------------------------------------------------
            // Hash FSM
            //--------------------------------------------------------------
            case (state)
                S_IDLE: begin
                    if (ready_reg && (init_cmd || next_cmd)) begin
                        // load working variables + W window
                        if (init_cmd) begin
                            // INIT: H[] = NIST initial constants for selected mode
                            if (mode_reg) begin
                                H0<=h_init256(0);H1<=h_init256(1);H2<=h_init256(2);H3<=h_init256(3);
                                H4<=h_init256(4);H5<=h_init256(5);H6<=h_init256(6);H7<=h_init256(7);
                                a<=h_init256(0);b<=h_init256(1);c<=h_init256(2);d<=h_init256(3);
                                e<=h_init256(4);f<=h_init256(5);g<=h_init256(6);h<=h_init256(7);
                            end else begin
                                H0<=h_init224(0);H1<=h_init224(1);H2<=h_init224(2);H3<=h_init224(3);
                                H4<=h_init224(4);H5<=h_init224(5);H6<=h_init224(6);H7<=h_init224(7);
                                a<=h_init224(0);b<=h_init224(1);c<=h_init224(2);d<=h_init224(3);
                                e<=h_init224(4);f<=h_init224(5);g<=h_init224(6);h<=h_init224(7);
                            end
                        end else begin
                            // NEXT: continue from current chained H[]
                            a<=H0;b<=H1;c<=H2;d<=H3;e<=H4;f<=H5;g<=H6;h<=H7;
                        end
                        // preload W[0..15] from block registers (big-endian word order)
                        for (n = 0; n < 16; n = n + 1) W[n] <= block_reg[n];
                        round     <= 7'd0;
                        ready_reg <= 1'b0;
                        valid_reg <= 1'b0;
                        state     <= S_ROUNDS;
                    end
                end

                S_ROUNDS: begin
                    // one round per cycle
                    h <= g;
                    g <= f;
                    f <= e;
                    e <= d + t1;
                    d <= c;
                    c <= b;
                    b <= a;
                    a <= t1 + t2;
                    // advance message schedule window
                    for (n = 0; n < 15; n = n + 1) W[n] <= W[n+1];
                    W[15] <= w_new;
                    if (round == 7'd63) state <= S_FINAL;
                    round <= round + 7'd1;
                end

                S_FINAL: begin
                    // add working vars back into chained hash (NIST: H_i += working)
                    H0 <= H0 + a; H1 <= H1 + b; H2 <= H2 + c; H3 <= H3 + d;
                    H4 <= H4 + e; H5 <= H5 + f; H6 <= H6 + g; H7 <= H7 + h;
                    // publish digest
                    digest_reg[0] <= H0 + a; digest_reg[1] <= H1 + b;
                    digest_reg[2] <= H2 + c; digest_reg[3] <= H3 + d;
                    digest_reg[4] <= H4 + e; digest_reg[5] <= H5 + f;
                    digest_reg[6] <= H6 + g; digest_reg[7] <= H7 + h;
                    valid_reg <= 1'b1;
                    ready_reg <= 1'b1;
                    state     <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
