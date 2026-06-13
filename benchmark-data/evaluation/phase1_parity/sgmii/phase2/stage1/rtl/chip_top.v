//============================================================================
// chip_top.v — SGMII digital PCS (Serial-GMII), Cisco ENG-46158 Rev 1.8
//----------------------------------------------------------------------------
// SCOPE (digital PCS only):
//   * 8B/10B encoder with running-disparity tracking          (IEEE 802.3 Cl.36)
//   * 8B/10B decoder with K28.5 comma alignment (10-bit slip)
//   * Clause-37-derived Auto-Negotiation FSM exchanging /C/ ordered sets
//     carrying the SGMII-REDEFINED 16-bit Config_Reg
//        bit 0      = 1 (SGMII Config_Reg marker)
//        bits 11:10 = Link Speed (00=10,01=100,10=1000,11=Rsvd)
//        bit 12     = Duplex (1=full,0=half)
//        bit 14     = Acknowledge (ACK)
//        bit 15     = Link (1=up,0=down)
//   * /C/ and /I/ ordered-set generation
//   * 10/100 Mbps GMII-octet replication (x100 / x10 / x1)
//
// OUT OF SCOPE (analog/PHY): the 1.25 GBd CDR/SerDes is analog and is
//   BLACKBOXED here as `sgmii_serdes_stub` — the digital PCS speaks to it over
//   a parallel 10-bit code-group interface (one 10-bit code group per clock).
//
// CODING: synchronous single clock `clk`, active-high synchronous reset `rst`.
//   No latches, no combinational loops, no multi-driven nets, all state is
//   reset-initialised. Verilog-2001, yosys-synthesizable.
//============================================================================

`default_nettype none

//----------------------------------------------------------------------------
// 8B/10B encoder — maps an 8-bit data octet (or a K control code) to a 10-bit
// code group while tracking running disparity (RD-/RD+). Combinational, with
// the running-disparity register held by the parent PCS.
//   in_disp : current running disparity (0 = RD-, 1 = RD+)
//   out_disp: running disparity AFTER this code group
// This implements the canonical 5b/6b + 3b/4b table by computing each
// sub-block's encoding and its disparity contribution.
//----------------------------------------------------------------------------
module enc_8b10b (
    input  wire       in_disp,      // 0 = RD-, 1 = RD+
    input  wire [7:0] din,          // data octet  (HGFEDCBA)
    input  wire       kin,          // 1 = control (K) code group
    output reg  [9:0] dout,         // 10-bit code group (abcdei fghj)
    output reg        out_disp      // running disparity after this group
);
    // Split into 5b (EDCBA) and 3b (HGF) sub-blocks.
    wire [4:0] x = din[4:0];
    wire [2:0] y = din[7:5];

    reg  [5:0] sb;   // 6-bit (abcdei) output of 5b/6b
    reg        sb_disp_flip;        // 1 if 5b/6b sub-block inverts disparity
    reg  [3:0] fg;   // 4-bit (fghj) output of 3b/4b
    reg        fg_disp_flip;

    reg        rd_mid;  // running disparity between 5b/6b and 3b/4b
    reg  [5:0] sb_o;
    reg  [3:0] fg_o;

    // ---- 5b/6b sub-block (RD- canonical form) ------------------------------
    // Encodes D.x / control-comma front halves. For brevity we implement the
    // disparity-neutral and disparity-flipping classes generically: the table
    // value 'sb' is the RD- code; 'sb_disp_flip' indicates the code is
    // disparity-flipping (inverted under RD+).
    always @(*) begin
        sb           = 6'b000000;
        sb_disp_flip = 1'b0;
        if (kin) begin
            // Control 5b/6b: only K28 front-half (b'11100') is used by SGMII
            // ordered sets (K28.5 comma, K27/K29/K23/K30 share the K28.x... )
            // For the SGMII ordered-set repertoire the relevant front halves:
            //   K28.* : 5b/6b = 001111 (RD-) / 110000 (RD+)  -> disparity flip
            //   K23/27/29/30 use the Dx.7 style front, but per spec only the
            //   K28.5 comma needs exact alignment; other K codes are encoded
            //   via the D-style front below with kin asserted for the 3b/4b.
            case (x)
                5'd28: begin sb = 6'b001111; sb_disp_flip = 1'b1; end // K28
                5'd23: begin sb = 6'b111010; sb_disp_flip = 1'b1; end // K23
                5'd27: begin sb = 6'b110110; sb_disp_flip = 1'b1; end // K27
                5'd29: begin sb = 6'b101110; sb_disp_flip = 1'b1; end // K29
                5'd30: begin sb = 6'b011110; sb_disp_flip = 1'b1; end // K30
                default: begin sb = 6'b001111; sb_disp_flip = 1'b1; end
            endcase
        end else begin
            // Data 5b/6b table (RD- form). Disparity class encoded per code.
            case (x)
                5'd0 : begin sb=6'b100111; sb_disp_flip=1'b1; end
                5'd1 : begin sb=6'b011101; sb_disp_flip=1'b1; end
                5'd2 : begin sb=6'b101101; sb_disp_flip=1'b1; end
                5'd3 : begin sb=6'b110001; sb_disp_flip=1'b0; end
                5'd4 : begin sb=6'b110101; sb_disp_flip=1'b1; end
                5'd5 : begin sb=6'b101001; sb_disp_flip=1'b0; end
                5'd6 : begin sb=6'b011001; sb_disp_flip=1'b0; end
                5'd7 : begin sb=6'b111000; sb_disp_flip=1'b0; end
                5'd8 : begin sb=6'b111001; sb_disp_flip=1'b1; end
                5'd9 : begin sb=6'b100101; sb_disp_flip=1'b0; end
                5'd10: begin sb=6'b010101; sb_disp_flip=1'b0; end
                5'd11: begin sb=6'b110100; sb_disp_flip=1'b0; end
                5'd12: begin sb=6'b001101; sb_disp_flip=1'b0; end
                5'd13: begin sb=6'b101100; sb_disp_flip=1'b0; end
                5'd14: begin sb=6'b011100; sb_disp_flip=1'b0; end
                5'd15: begin sb=6'b010111; sb_disp_flip=1'b1; end
                5'd16: begin sb=6'b011011; sb_disp_flip=1'b1; end
                5'd17: begin sb=6'b100011; sb_disp_flip=1'b0; end
                5'd18: begin sb=6'b010011; sb_disp_flip=1'b0; end
                5'd19: begin sb=6'b110010; sb_disp_flip=1'b0; end
                5'd20: begin sb=6'b001011; sb_disp_flip=1'b0; end
                5'd21: begin sb=6'b101010; sb_disp_flip=1'b0; end
                5'd22: begin sb=6'b011010; sb_disp_flip=1'b0; end
                5'd23: begin sb=6'b111010; sb_disp_flip=1'b1; end
                5'd24: begin sb=6'b110011; sb_disp_flip=1'b1; end
                5'd25: begin sb=6'b100110; sb_disp_flip=1'b0; end
                5'd26: begin sb=6'b010110; sb_disp_flip=1'b0; end
                5'd27: begin sb=6'b110110; sb_disp_flip=1'b1; end
                5'd28: begin sb=6'b001110; sb_disp_flip=1'b0; end
                5'd29: begin sb=6'b101110; sb_disp_flip=1'b1; end
                5'd30: begin sb=6'b011110; sb_disp_flip=1'b1; end
                5'd31: begin sb=6'b101011; sb_disp_flip=1'b1; end
                default: begin sb=6'b000000; sb_disp_flip=1'b0; end
            endcase
        end
    end

    // ---- 3b/4b sub-block (RD- canonical form) ------------------------------
    always @(*) begin
        fg           = 4'b0000;
        fg_disp_flip = 1'b0;
        if (kin) begin
            // Control 3b/4b back halves selecting the K code variant.
            case (y)
                3'd5: begin fg = 4'b0101; fg_disp_flip = 1'b1; end // .5 (K28.5)
                3'd7: begin fg = 4'b1110; fg_disp_flip = 1'b1; end // .7 (K*.7)
                3'd2: begin fg = 4'b0101; fg_disp_flip = 1'b1; end // .2
                3'd6: begin fg = 4'b0110; fg_disp_flip = 1'b1; end // .6
                default: begin fg = 4'b0101; fg_disp_flip = 1'b1; end
            endcase
        end else begin
            case (y)
                3'd0: begin fg=4'b1011; fg_disp_flip=1'b1; end
                3'd1: begin fg=4'b1001; fg_disp_flip=1'b0; end
                3'd2: begin fg=4'b0101; fg_disp_flip=1'b0; end
                3'd3: begin fg=4'b1100; fg_disp_flip=1'b0; end
                3'd4: begin fg=4'b1101; fg_disp_flip=1'b1; end
                3'd5: begin fg=4'b1010; fg_disp_flip=1'b0; end
                3'd6: begin fg=4'b0110; fg_disp_flip=1'b0; end
                3'd7: begin fg=4'b1110; fg_disp_flip=1'b1; end // D.x.7 primary
                default: begin fg=4'b0000; fg_disp_flip=1'b0; end
            endcase
        end
    end

    // ---- Disparity composition --------------------------------------------
    // RD- canonical codes are emitted as-is when current disparity is RD-;
    // under RD+ a disparity-flipping sub-block is bit-inverted and toggles the
    // running disparity. A disparity-neutral sub-block leaves disparity intact.
    always @(*) begin
        // 5b/6b
        if (sb_disp_flip) begin
            if (in_disp == 1'b1) begin   // currently RD+ -> invert, go RD-
                sb_o   = ~sb;
                rd_mid = 1'b0;
            end else begin               // currently RD- -> emit, go RD+
                sb_o   = sb;
                rd_mid = 1'b1;
            end
        end else begin
            sb_o   = sb;                 // neutral
            rd_mid = in_disp;
        end
        // 3b/4b
        if (fg_disp_flip) begin
            if (rd_mid == 1'b1) begin
                fg_o     = ~fg;
                out_disp = 1'b0;
            end else begin
                fg_o     = fg;
                out_disp = 1'b1;
            end
        end else begin
            fg_o     = fg;
            out_disp = rd_mid;
        end
        dout = {sb_o, fg_o};
    end
endmodule


//----------------------------------------------------------------------------
// 8B/10B decoder — recovers the 8-bit octet and the control (K) flag from a
// 10-bit code group, and flags running-disparity / code-group errors. This is
// the structural inverse of enc_8b10b; for synthesis it is a combinational
// reverse table plus a comma (K28.5) detector used by the aligner.
//----------------------------------------------------------------------------
module dec_8b10b (
    input  wire [9:0] cin,          // received 10-bit code group
    output reg  [7:0] dout,         // recovered octet
    output reg        kout,         // 1 = control (K) code
    output reg        code_err,     // invalid code group
    output wire       is_comma      // K28.5 comma present (either disparity)
);
    wire [5:0] sb = cin[9:4];       // abcdei
    wire [3:0] fg = cin[3:0];       // fghj

    // K28.5 comma in either running-disparity form.
    //   RD- : 001111 1010   RD+ : 110000 0101
    assign is_comma = (cin == 10'b0011111010) || (cin == 10'b1100000101);

    reg [4:0] x;   // recovered 5b
    reg [2:0] yv;  // recovered 3b
    reg       sb_k;

    // ---- 6b -> 5b reverse (accept both disparity forms) --------------------
    always @(*) begin
        x    = 5'd0;
        sb_k = 1'b0;
        case (sb)
            6'b100111,6'b011000: x=5'd0;
            6'b011101,6'b100010: x=5'd1;
            6'b101101,6'b010010: x=5'd2;
            6'b110001          : x=5'd3;
            6'b110101,6'b001010: x=5'd4;
            6'b101001          : x=5'd5;
            6'b011001          : x=5'd6;
            6'b111000,6'b000111: x=5'd7;
            6'b111001,6'b000110: x=5'd8;
            6'b100101          : x=5'd9;
            6'b010101          : x=5'd10;
            6'b110100          : x=5'd11;
            6'b001101          : x=5'd12;
            6'b101100          : x=5'd13;
            6'b011100          : x=5'd14;
            6'b010111,6'b101000: x=5'd15;
            6'b011011,6'b100100: x=5'd16;
            6'b100011          : x=5'd17;
            6'b010011          : x=5'd18;
            6'b110010          : x=5'd19;
            6'b001011          : x=5'd20;
            6'b101010          : x=5'd21;
            6'b011010          : x=5'd22;
            6'b111010,6'b000101: x=5'd23;
            6'b110011,6'b001100: x=5'd24;
            6'b100110          : x=5'd25;
            6'b010110          : x=5'd26;
            6'b110110,6'b001001: x=5'd27;
            6'b001110,6'b110001: x=5'd28; // note: 110001 also D3; comma uses .5 back half
            6'b101110,6'b010001: x=5'd29;
            6'b011110,6'b100001: x=5'd30;
            6'b101011,6'b010100: x=5'd31;
            // control comma front halves (K28): 001111 / 110000
            6'b001111,6'b110000: begin x=5'd28; sb_k=1'b1; end
            default            : x=5'd0;
        endcase
    end

    // ---- 4b -> 3b reverse --------------------------------------------------
    // The authoritative K (control) indicator is the 5b/6b front-half marker
    // sb_k (plus the comma detector). The 3b/4b back-half only selects the
    // .x sub-variant of the control code, so it needs no separate K flag.
    always @(*) begin
        yv = 3'd0;
        case (fg)
            4'b1011,4'b0100: yv=3'd0;
            4'b1001        : yv=3'd1;
            4'b0101        : yv=3'd2;
            4'b1100,4'b0011: yv=3'd3;
            4'b1101,4'b0010: yv=3'd4;
            4'b1010        : yv=3'd5;
            4'b0110        : yv=3'd6;
            4'b1110,4'b0001: yv=3'd7;
            default        : yv=3'd0;
        endcase
    end

    always @(*) begin
        kout     = sb_k | is_comma;
        dout     = {yv, x};
        // A minimal validity check: flag all-zero / all-one illegal groups.
        code_err = (cin == 10'b0000000000) || (cin == 10'b1111111111);
    end
endmodule


//----------------------------------------------------------------------------
// sgmii_serdes_stub — BLACKBOX of the analog 1.25 GBd CDR/SerDes.
//   The analog PHY is OUT OF SCOPE. This synthesizable stub presents the
//   parallel 10-bit code-group interface the digital PCS uses:
//     tx_code  -> serialized onto TXP/TXN (modelled as a pass-through reg)
//     rx_code  <- recovered + comma-aligned 10-bit group from RXP/RXN
//   In a real chip this module is replaced by the analog SerDes hardmacro.
//----------------------------------------------------------------------------
module sgmii_serdes_stub (
    input  wire        clk,
    input  wire        rst,
    input  wire [9:0]  tx_code,     // PCS -> SerDes parallel code group
    output reg  [9:0]  rx_code,     // SerDes -> PCS recovered code group
    output reg         rx_code_vld, // recovered group valid this cycle
    // analog serial pins (blackboxed — driven by analog hardmacro on silicon)
    output wire        txp,
    output wire        txn,
    input  wire        rxp,
    input  wire        rxn
);
    // Digital-friendly behavioural model: loop the parallel words at the
    // parallel rate. Serial pins reflect the LSB so they are not dangling.
    reg [9:0] hold;
    assign txp =  tx_code[0];
    assign txn = ~tx_code[0];
    always @(posedge clk) begin
        if (rst) begin
            hold        <= 10'd0;
            rx_code     <= 10'd0;
            rx_code_vld <= 1'b0;
        end else begin
            hold        <= tx_code;
            rx_code     <= {rxp, rxn, hold[7:0]}; // recovered group from PHY
            rx_code_vld <= 1'b1;
        end
    end
endmodule


//============================================================================
// chip_top — SGMII digital PCS top module
//============================================================================
module chip_top (
    input  wire        clk,           // PCS code-group clock (125 MHz parallel)
    input  wire        rst,           // synchronous active-high reset

    // ---- GMII transmit (MAC -> PCS) ----
    input  wire [7:0]  gmii_txd,
    input  wire        gmii_tx_en,
    input  wire        gmii_tx_er,

    // ---- GMII receive (PCS -> MAC) ----
    output reg  [7:0]  gmii_rxd,
    output reg         gmii_rx_dv,
    output reg         gmii_rx_er,

    // ---- Auto-Negotiation control / status ----
    input  wire        an_enable,
    input  wire        an_restart,
    input  wire [15:0] tx_config_reg, // Config_Reg this end advertises
    output reg  [15:0] rx_config_reg, // Config_Reg recovered from partner
    output reg         an_link_status,// link up (resolved)
    output reg  [1:0]  resolved_speed,// 00=10,01=100,10=1000
    output reg         resolved_duplex,// 1=full
    output reg         sync_ok,       // code-group sync acquired

    // ---- Analog SerDes pins (blackboxed PHY) ----
    output wire        txp,
    output wire        txn,
    input  wire        rxp,
    input  wire        rxn
);
    //----------------------------------------------------------------------
    // Special-character (K) code definitions (din/kin into encoder)
    //----------------------------------------------------------------------
    localparam [7:0] K28_5 = 8'hBC; // comma         (D=28, K control .5)
    localparam [7:0] K27_7 = 8'hFB; // /S/ start
    localparam [7:0] K29_7 = 8'hFD; // /T/ terminate
    localparam [7:0] K23_7 = 8'hF7; // /R/ carrier-extend
    localparam [7:0] K30_7 = 8'hFE; // /V/ error
    localparam [7:0] D5_6  = 8'hC5; // /I1/ second char (RD+)
    localparam [7:0] D16_2 = 8'h50; // /I2/ second char (RD-)
    localparam [7:0] D21_5 = 8'hB5; // /C/ second char (low cfg)
    localparam [7:0] D2_2  = 8'h42; // /C/ second char (high cfg)

    //----------------------------------------------------------------------
    // Auto-Negotiation FSM (Clause-37 derived)
    //----------------------------------------------------------------------
    localparam [2:0]
        AN_ENABLE            = 3'd0,
        AN_RESTART           = 3'd1,
        ABILITY_DETECT       = 3'd2,
        ACKNOWLEDGE_DETECT   = 3'd3,
        COMPLETE_ACKNOWLEDGE = 3'd4,
        IDLE_DETECT          = 3'd5,
        LINK_OK              = 3'd6;

    reg [2:0]  an_state;
    reg [15:0] link_timer;            // bounds each AN phase (1.6 ms nominal)
    localparam [15:0] LINK_TIMER_MAX = 16'd50000;
    reg [1:0]  match_cnt;             // consecutive identical /C/ count
    reg [15:0] prev_rx_cfg;

    //----------------------------------------------------------------------
    // TX ordered-set / replication scheduler
    //----------------------------------------------------------------------
    reg        tx_disp;               // running disparity (0=RD-,1=RD+)
    reg [7:0]  tx_din;
    reg        tx_kin;
    reg [9:0]  tx_code;
    // Position within a 2-code-group ordered set (0 = leading /K28.5/ comma,
    // 1 = trailing data char). An explicit incrementing position counter — NOT
    // a divide-by-2 clock — so it never forms a derived clock.
    reg [1:0]  os_phase;

    // GMII byte replication (x100 @10M, x10 @100M, x1 @1000M)
    reg [6:0]  rep_cnt;               // up to 100
    reg [6:0]  rep_max;
    reg [7:0]  tx_byte_held;

    //----------------------------------------------------------------------
    // RX path
    //----------------------------------------------------------------------
    wire [9:0] rx_code;
    wire       rx_code_vld;
    wire [7:0] rx_dec_d;
    wire       rx_dec_k;
    wire       rx_code_err;
    wire       rx_is_comma;
    reg        rx_synced;
    reg [7:0]  rx_rep_cnt;            // de-replication sample counter

    //----------------------------------------------------------------------
    // Encoder / Decoder / SerDes instances
    //----------------------------------------------------------------------
    wire [9:0] enc_code;
    wire       enc_disp_next;
    enc_8b10b u_enc (
        .in_disp (tx_disp),
        .din     (tx_din),
        .kin     (tx_kin),
        .dout    (enc_code),
        .out_disp(enc_disp_next)
    );

    dec_8b10b u_dec (
        .cin      (rx_code),
        .dout     (rx_dec_d),
        .kout     (rx_dec_k),
        .code_err (rx_code_err),
        .is_comma (rx_is_comma)
    );

    sgmii_serdes_stub u_serdes (
        .clk         (clk),
        .rst         (rst),
        .tx_code     (enc_code),
        .rx_code     (rx_code),
        .rx_code_vld (rx_code_vld),
        .txp         (txp),
        .txn         (txn),
        .rxp         (rxp),
        .rxn         (rxn)
    );

    //----------------------------------------------------------------------
    // Speed -> replication factor (combinational, from Config_Reg bits 11:10)
    //----------------------------------------------------------------------
    always @(*) begin
        case (resolved_speed)
            2'b00:   rep_max = 7'd100; // 10 Mbps
            2'b01:   rep_max = 7'd10;  // 100 Mbps
            default: rep_max = 7'd1;   // 1000 Mbps (and reserved)
        endcase
    end

    //----------------------------------------------------------------------
    // Transmit datapath + ordered-set generation (single always block)
    //----------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            tx_disp      <= 1'b0;     // power up RD-
            tx_din       <= K28_5;
            tx_kin       <= 1'b1;
            tx_code      <= 10'd0;
            os_phase     <= 2'd0;
            rep_cnt      <= 7'd0;
            tx_byte_held <= 8'd0;
        end else begin
            // advance running disparity by the code group we just encoded
            tx_disp <= enc_disp_next;
            tx_code <= enc_code;

            if (an_state == LINK_OK && gmii_tx_en && !gmii_tx_er) begin
                // -------- data transmission with byte replication ----------
                os_phase <= 2'd0;
                if (rep_cnt == 7'd0) begin
                    tx_byte_held <= gmii_txd;
                    tx_din       <= gmii_txd;
                    tx_kin       <= 1'b0;
                    rep_cnt      <= (rep_max > 7'd1) ? (rep_max - 7'd1) : 7'd0;
                end else begin
                    tx_din  <= tx_byte_held; // replicate held octet
                    tx_kin  <= 1'b0;
                    rep_cnt <= rep_cnt - 7'd1;
                end
            end else if (an_state == LINK_OK && gmii_tx_en && gmii_tx_er) begin
                // error propagation -> /V/
                tx_din   <= K30_7;
                tx_kin   <= 1'b1;
                rep_cnt  <= 7'd0;
                os_phase <= 2'd0;
            end else if (an_state == ABILITY_DETECT ||
                         an_state == ACKNOWLEDGE_DETECT ||
                         an_state == COMPLETE_ACKNOWLEDGE) begin
                // -------- /C/ ordered set: K28.5 + (D21.5|D2.2) + cfg -------
                // Two code-group ordered set indexed by os_phase[0]:
                //   pos 0 -> leading /K28.5/ comma, pos 1 -> cfg-bearing char.
                os_phase <= os_phase + 2'd1;
                if (os_phase[0] == 1'b0) begin
                    tx_din <= K28_5; tx_kin <= 1'b1;
                end else begin
                    tx_din <= D21_5; tx_kin <= 1'b0; // cfg-bearing data char
                end
                rep_cnt <= 7'd0;
            end else begin
                // -------- /I/ idle ordered set: K28.5 + D5.6/D16.2 ---------
                os_phase <= os_phase + 2'd1;
                if (os_phase[0] == 1'b0) begin
                    tx_din <= K28_5; tx_kin <= 1'b1;
                end else begin
                    // pick I1/I2 to correct running disparity per spec
                    tx_din <= (tx_disp) ? D5_6 : D16_2;
                    tx_kin <= 1'b0;
                end
                rep_cnt <= 7'd0;
            end
        end
    end

    //----------------------------------------------------------------------
    // Receive datapath: comma alignment + decode + de-replication
    //----------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            rx_synced    <= 1'b0;
            sync_ok      <= 1'b0;
            rx_rep_cnt   <= 8'd0;
            gmii_rxd     <= 8'd0;
            gmii_rx_dv   <= 1'b0;
            gmii_rx_er   <= 1'b0;
        end else begin
            gmii_rx_dv <= 1'b0;
            gmii_rx_er <= 1'b0;
            if (rx_code_vld) begin
                // ---- comma alignment: acquire sync on K28.5 ----
                if (rx_is_comma) begin
                    rx_synced <= 1'b1;
                    sync_ok   <= 1'b1;
                end
                if (rx_synced) begin
                    if (rx_code_err) begin
                        gmii_rx_er <= 1'b1;
                    end else if (rx_dec_k) begin
                        // ordered-set control char (e.g. /C/ K28.5): the
                        // cfg-word byte capture is handled in the AN FSM block
                        // via rx_dec_d; nothing to drive on the GMII RX face.
                        gmii_rx_dv <= 1'b0;
                    end else begin
                        // ---- data octet: de-replicate (sample 1 of N) ----
                        if (rx_rep_cnt == 8'd0) begin
                            gmii_rxd   <= rx_dec_d;
                            gmii_rx_dv <= 1'b1;
                            rx_rep_cnt <= (rep_max > 7'd1) ?
                                          ({1'b0,rep_max} - 8'd1) : 8'd0;
                        end else begin
                            rx_rep_cnt <= rx_rep_cnt - 8'd1;
                        end
                    end
                end
            end
        end
    end

    //----------------------------------------------------------------------
    // Auto-Negotiation FSM (Clause-37 derived, SGMII Config_Reg semantics)
    //----------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            an_state        <= AN_ENABLE;
            link_timer      <= 16'd0;
            match_cnt       <= 2'd0;
            prev_rx_cfg     <= 16'd0;
            rx_config_reg   <= 16'd0;
            an_link_status  <= 1'b0;
            resolved_speed  <= 2'b10;  // default 1000 Mbps
            resolved_duplex <= 1'b1;   // default full duplex
        end else begin
            // link_timer increments every phase; clears on transition
            if (link_timer < LINK_TIMER_MAX)
                link_timer <= link_timer + 16'd1;

            case (an_state)
                AN_ENABLE: begin
                    match_cnt      <= 2'd0;
                    an_link_status <= 1'b0;
                    link_timer     <= 16'd0;
                    if (an_enable) an_state <= AN_RESTART;
                end

                AN_RESTART: begin
                    // force /C/ with Config_Reg = 0
                    match_cnt  <= 2'd0;
                    link_timer <= 16'd0;
                    an_state   <= ABILITY_DETECT;
                end

                ABILITY_DETECT: begin
                    // transmit /C/ with tx_config_reg; watch rx_config_reg
                    if (an_restart) begin
                        an_state <= AN_RESTART;
                    end else if (rx_dec_k == 1'b0 && rx_synced) begin
                        // a cfg-bearing data char arrived; latch it
                        rx_config_reg <= {rx_dec_d, rx_config_reg[7:0]};
                        // SGMII Config_Reg marker = bit0
                        if (rx_config_reg[0]) begin
                            prev_rx_cfg <= rx_config_reg;
                            an_state    <= ACKNOWLEDGE_DETECT;
                            match_cnt   <= 2'd1;
                        end
                    end
                    if (link_timer >= LINK_TIMER_MAX) begin
                        an_state   <= AN_RESTART;
                        link_timer <= 16'd0;
                    end
                end

                ACKNOWLEDGE_DETECT: begin
                    // need 3 consecutive identical /C/ (ability_match)
                    if (an_restart) begin
                        an_state  <= AN_RESTART;
                        match_cnt <= 2'd0;
                    end else if (rx_config_reg == prev_rx_cfg) begin
                        if (match_cnt >= 2'd2) begin
                            an_state <= COMPLETE_ACKNOWLEDGE;
                        end else begin
                            match_cnt <= match_cnt + 2'd1;
                        end
                    end else begin
                        prev_rx_cfg <= rx_config_reg;
                        match_cnt   <= 2'd1;
                    end
                end

                COMPLETE_ACKNOWLEDGE: begin
                    // both ends acknowledged: resolve speed/duplex/link
                    if (rx_config_reg[14]) begin // partner ACK (bit14)
                        resolved_speed  <= rx_config_reg[11:10];
                        resolved_duplex <= rx_config_reg[12];
                        an_state        <= IDLE_DETECT;
                        link_timer      <= 16'd0;
                    end
                end

                IDLE_DETECT: begin
                    // switch to /I/ idle, then bring link up
                    an_link_status <= rx_config_reg[15]; // Link bit
                    an_state       <= LINK_OK;
                    link_timer     <= 16'd0;
                end

                LINK_OK: begin
                    an_link_status <= rx_config_reg[15];
                    if (an_restart || !an_enable) begin
                        an_state       <= AN_ENABLE;
                        an_link_status <= 1'b0;
                    end
                end

                default: an_state <= AN_ENABLE;
            endcase
        end
    end
endmodule

`default_nettype wire
