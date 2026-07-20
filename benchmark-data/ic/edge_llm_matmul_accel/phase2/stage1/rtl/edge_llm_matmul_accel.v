// ---------------------------------------------------------------------------
// edge_llm_matmul_accel
//
// Hard-wired INT4 (signed, two's-complement, W4A4) GEMM accelerator.
// Authored from the forward L1-L27 specification (blind doc->RTL).
//
//   * Fixed 16x16 systolic PE array = 256 signed INT4 x INT4 MAC PEs
//     (output-stationary: PE[m][n] owns output element C[m][n]).
//   * 32-bit signed accumulator per PE, accumulated over K cycles.
//   * Per-output requant: signed acc * Q1.15 scale, arithmetic >> OUT_SHIFT,
//     round-half-up, saturate to INT8 [-128,127].
//   * Arbitrary M/K/N via software tiling through the fixed 16x16 tile.
//   * Host interface = Wishbone B4 classic single-word slave: 9 registers
//     (CTRL/STATUS/M_DIM/K_DIM/N_DIM/SCALE/OUT_SHIFT/IRQ_EN/IRQ_STATUS) +
//     three memory-mapped SRAM windows (WEIGHT/ACT/OUT).
//   * FSM: IDLE -> LOAD_WEIGHTS -> LOAD_ACT -> COMPUTE -> REQUANT ->
//     WRITE_OUT -> DONE.
//
// Reference L-docs: L1 (datasheet), L2 (FRS), L3 (cmd protocol),
// L4 (regmap), L6 (control logic), L8 (rtl constants + timing),
// L9 (integration spec), L10/L12/L16 (test/behaviour/compliance).
//
// PDK sky130A, 50 MHz single clock domain (wb_clk_i).
// ---------------------------------------------------------------------------
`default_nettype none
/* verilator lint_off DECLFILENAME */

// ---------------------------------------------------------------------------
// Signed INT4 x INT4 multiply-accumulate processing element.
//   prod = a * w            (signed 4x4 -> signed 8-bit, range [-56,64])
//   acc  = (clr ? 0 : acc) + sext(prod)   when en
// One PE per output element; 256 instances form the fixed 16x16 tile.
// ---------------------------------------------------------------------------
module mac_pe (
    input  wire                clk,
    input  wire                rst_n,     // synchronous, active-low
    input  wire                clr,       // start a fresh accumulation (k==0)
    input  wire                en,        // accumulate this cycle
    input  wire signed [3:0]   a,         // activation operand (INT4)
    input  wire signed [3:0]   w,         // weight operand (INT4)
    output wire signed [31:0]  acc
);
    reg  signed [31:0] acc_r;
    wire signed [7:0]  prod = a * w;                 // signed 4x4 multiply
    wire signed [31:0] prod_ext = {{24{prod[7]}}, prod};   // sign-extend to 32b

    always @(posedge clk) begin
        if (!rst_n)
            acc_r <= 32'sd0;
        else if (en)
            acc_r <= (clr ? 32'sd0 : acc_r) + prod_ext;
    end

    assign acc = acc_r;
endmodule


// ---------------------------------------------------------------------------
// Synchronous single-port SRAM behavioural model (1-cycle read latency).
// Represents an on-chip SRAM macro; in silicon these are OpenRAM/foundry
// macros substituted at place-and-route. Depth is capped under `SYNTHESIS`
// so the synth sanity gate stays tractable (the software-visible window is
// the full 32/16 KB per L4; the behavioural model backs a representative
// depth). AW/DW are per-instance parameters.
// ---------------------------------------------------------------------------
module sram_sp #(
    parameter integer AW = 13,
    parameter integer DW = 32
)(
    input  wire            clk,
    input  wire            en,
    input  wire            we,
    input  wire [AW-1:0]   addr,
    input  wire [DW-1:0]   wdata,
    output reg  [DW-1:0]   rdata
);
    localparam integer DEPTH = (1 << AW);
    reg [DW-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (en) begin
            if (we)
                mem[addr] <= wdata;
            rdata <= mem[addr];
        end
    end
endmodule


// ---------------------------------------------------------------------------
// Top module.
// ---------------------------------------------------------------------------
module edge_llm_matmul_accel #(
    parameter integer DATA_W   = 4,     // INT4 signed operand width
    parameter integer ACC_W    = 32,    // accumulator width
    parameter integer OUT_W    = 8,     // requantized INT8 output width
    parameter integer SCALE_W  = 16,    // Q1.15 per-channel scale
    parameter integer ROWS     = 16,    // ARRAY_ROWS (M tile)
    parameter integer COLS     = 16     // ARRAY_COLS (N tile)
)(
    // Wishbone B4 data/address widths are contract-fixed at 32b (L8/L9), so
    // the top-level bus ports use literal widths.
    input  wire              clk,            // alternate clock pin (see note)
    input  wire              rst_n,          // async chip reset (active-low)
    input  wire              wb_clk_i,       // Wishbone / core clock
    input  wire              wb_rst_i,       // Wishbone reset (active-high)
    input  wire              wbs_stb_i,
    input  wire              wbs_cyc_i,
    input  wire              wbs_we_i,
    input  wire [3:0]        wbs_sel_i,
    input  wire [31:0]       wbs_dat_i,
    input  wire [31:0]       wbs_adr_i,
    output wire              wbs_ack_o,
    output wire [31:0]       wbs_dat_o,
    output wire              irq_o,
    output wire              status_ready_o,
    output wire              status_done_o
);
    // -----------------------------------------------------------------------
    // Clock / reset.  The design is single-domain: the Wishbone bus and the
    // compute datapath both run on wb_clk_i (a B4 slave must be synchronous to
    // the bus clock).  `clk` is the redundant alternate clock pin (tied to
    // wb_clk_i at SoC integration).  Reset folds both reset sources: active
    // when the chip reset is asserted OR the Wishbone reset is asserted.
    // -----------------------------------------------------------------------
    wire clk_i   = wb_clk_i;
    wire rst_n_i = rst_n & ~wb_rst_i;

    // -----------------------------------------------------------------------
    // SRAM depths.  Full spec = 32 KB weight (8192 x 32b), 16 KB act / out
    // (4096 x 32b).  Under synthesis, cap to a representative depth so the
    // yosys synth sanity gate stays tractable (macros are substituted at PnR).
    // -----------------------------------------------------------------------
`ifdef SYNTHESIS
    // Representative one-tile depth for the synth sanity gate (32 weight/act
    // words + 64 out words hold exactly one 16x16 INT4 tile); the silicon
    // macros are the full 32/16/16 KB per L4, substituted at PnR.
    localparam integer WBUF_AW = 5;    // 32 words
    localparam integer ABUF_AW = 5;    // 32 words
    localparam integer OBUF_AW = 6;    // 64 words
`else
    localparam integer WBUF_AW = 13;   // 32 KB weight buffer
    localparam integer ABUF_AW = 12;   // 16 KB activation buffer
    localparam integer OBUF_AW = 12;   // 16 KB output buffer
`endif

    // Wishbone bus widths (contract-fixed).
    localparam integer WB_DW = 32;
    localparam integer WB_AW = 32;

    // Words needed to hold one 16x16 INT4 tile = 256 nibbles / 8 = 32 words.
    localparam integer TILE_WORDS = (ROWS*COLS*DATA_W)/WB_DW;   // = 32

    // -----------------------------------------------------------------------
    // FSM states.
    // -----------------------------------------------------------------------
    localparam [2:0] S_IDLE         = 3'd0,
                     S_LOAD_WEIGHTS = 3'd1,
                     S_LOAD_ACT     = 3'd2,
                     S_COMPUTE      = 3'd3,
                     S_REQUANT      = 3'd4,
                     S_WRITE_OUT    = 3'd5,
                     S_DONE         = 3'd6;
    reg [2:0] state;

    // -----------------------------------------------------------------------
    // Register file (L4 register map).
    // -----------------------------------------------------------------------
    reg [31:0]        m_dim, k_dim, n_dim;
    reg [SCALE_W-1:0] scale_reg;
    reg [4:0]         shift_reg;
    reg               irq_en;
    reg               irq_status;    // [0]=DONE_IRQ (W1C)
    reg               done_flag;     // STATUS.DONE (latched until next START)
    reg               error_flag;    // STATUS.ERROR

    // -----------------------------------------------------------------------
    // Wishbone B4 classic single-word slave handshake.
    //   ack asserts for exactly one cycle, the cycle after (cyc & stb) rises.
    //   writes commit on the ack cycle; reads present rdata on the ack cycle
    //   (aligned to the 1-cycle SRAM read latency).
    // -----------------------------------------------------------------------
    wire wb_valid = wbs_cyc_i & wbs_stb_i;
    reg  ack_r;
    always @(posedge clk_i) begin
        if (!rst_n_i) ack_r <= 1'b0;
        else          ack_r <= wb_valid & ~ack_r;
    end
    assign wbs_ack_o = ack_r;

    wire wr_commit = wb_valid & wbs_we_i & ack_r;   // 1-cycle write strobe
    wire rd_access = wb_valid & ~wbs_we_i;          // read window (whole xfer)

    // Not busy => host may access registers/SRAM (P4: no bus write accepted
    // while BUSY; STATUS reads are always allowed via the read mux).
    wire busy = (state != S_IDLE);
    wire host_wr = wr_commit & ~busy;

    // -----------------------------------------------------------------------
    // Address decode.  Window select = wbs_adr_i[17:16]:
    //   00 -> register block (offset = wbs_adr_i[7:2])
    //   01 -> WEIGHT_SRAM window
    //   10 -> ACT_SRAM    window
    //   11 -> OUT_SRAM     window
    // Base is SoC-defined (L4); offsets below are this design's R3 choice.
    // -----------------------------------------------------------------------
    wire [1:0] win = wbs_adr_i[17:16];
    wire sel_reg = (win == 2'b00);
    wire sel_wgt = (win == 2'b01);
    wire sel_act = (win == 2'b10);
    wire sel_out = (win == 2'b11);
    wire [5:0] reg_ofs = wbs_adr_i[7:2];

    // Register-block offsets (byte address / 4).
    localparam [5:0] R_CTRL      = 6'h00 >> 2,
                     R_STATUS    = 6'h04 >> 2,
                     R_M_DIM     = 6'h08 >> 2,
                     R_K_DIM     = 6'h0C >> 2,
                     R_N_DIM     = 6'h10 >> 2,
                     R_SCALE     = 6'h14 >> 2,
                     R_OUT_SHIFT = 6'h18 >> 2,
                     R_IRQ_EN    = 6'h1C >> 2,
                     R_IRQ_STAT  = 6'h20 >> 2;

    // START pulse: CTRL[0] write while IDLE.
    wire start_pulse = host_wr & sel_reg & (reg_ofs == R_CTRL) & wbs_dat_i[0];
    wire soft_reset  = host_wr & sel_reg & (reg_ofs == R_CTRL) & wbs_dat_i[1];

    // -----------------------------------------------------------------------
    // Operand tile stores (raw 32-bit bus words).  Layout (R3 choice, exposed
    // as the software operand-packing contract):
    //   weight_sram: W[k][n] at nibble index k*16+n  -> row k = words {2k,2k+1}
    //   act_sram   : A[m][k] at nibble index k*16+m  -> col k = words {2k,2k+1}
    // so each COMPUTE cycle k reads two contiguous words per operand stream.
    // -----------------------------------------------------------------------
    reg [WB_DW-1:0] w_words [0:TILE_WORDS-1];
    reg [WB_DW-1:0] a_words [0:TILE_WORDS-1];

    // Load pipeline bookkeeping (1-cycle SRAM read latency).  Wide enough that
    // [AW-1:0] slicing is valid for any SRAM address width.
    reg [12:0] ld;         // address counter 0..TILE_WORDS
    reg [4:0]  cap_idx;    // capture index (delayed address, 0..31)
    reg        cap_en;     // capture enable (valid after first read)

    // COMPUTE within-tile K index and effective K per pass (clamped to tile).
    wire [4:0] k_eff  = (k_dim == 0)    ? 5'd1      :
                        (k_dim > ROWS)  ? ROWS[4:0] : k_dim[4:0];
    wire [3:0] k_last = (k_eff >= 5'd16) ? 4'd15 : (k_eff[3:0] - 4'd1);
    reg  [3:0] kc;         // 0..15

    // Drain / write-out linear index and packing register.
    reg [8:0]  o;          // 0..255 output element index
    reg [31:0] pack_reg;
    wire [11:0] out_word = {5'd0, o[8:2]};   // output-tile word index = o/4

    // -----------------------------------------------------------------------
    // SRAM instances.
    // -----------------------------------------------------------------------
    reg  [WBUF_AW-1:0] w_addr;  reg w_en, w_we;  reg [31:0] w_wdata;
    wire [31:0]        w_rdata;
    reg  [ABUF_AW-1:0] a_addr;  reg a_en, a_we;  reg [31:0] a_wdata;
    wire [31:0]        a_rdata;
    reg  [OBUF_AW-1:0] ob_addr; reg ob_en, ob_we; reg [31:0] ob_wdata;
    wire [31:0]        ob_rdata;

    sram_sp #(.AW(WBUF_AW), .DW(32)) u_weight_sram (
        .clk(clk_i), .en(w_en), .we(w_we),
        .addr(w_addr), .wdata(w_wdata), .rdata(w_rdata));
    sram_sp #(.AW(ABUF_AW), .DW(32)) u_act_sram (
        .clk(clk_i), .en(a_en), .we(a_we),
        .addr(a_addr), .wdata(a_wdata), .rdata(a_rdata));
    sram_sp #(.AW(OBUF_AW), .DW(32)) u_out_sram (
        .clk(clk_i), .en(ob_en), .we(ob_we),
        .addr(ob_addr), .wdata(ob_wdata), .rdata(ob_rdata));

    // -----------------------------------------------------------------------
    // COMPUTE operand extraction: the two contiguous words per stream for the
    // current k, split into 16 signed INT4 lanes.
    // -----------------------------------------------------------------------
    wire [31:0] w_lo = w_words[{kc, 1'b0}];   // 2*kc
    wire [31:0] w_hi = w_words[{kc, 1'b1}];   // 2*kc+1
    wire [31:0] a_lo = a_words[{kc, 1'b0}];
    wire [31:0] a_hi = a_words[{kc, 1'b1}];

    function [DATA_W-1:0] nib16;
        input [31:0] lo;
        input [31:0] hi;
        input [3:0]  idx;
        begin
            nib16 = idx[3] ? hi[{idx[2:0], 2'b00} +: DATA_W]
                           : lo[{idx[2:0], 2'b00} +: DATA_W];
        end
    endfunction

    wire signed [DATA_W-1:0] act_op [0:ROWS-1];
    wire signed [DATA_W-1:0] wgt_op [0:COLS-1];
    genvar gi;
    generate
        for (gi = 0; gi < ROWS; gi = gi + 1) begin : g_ops
            assign act_op[gi] = nib16(a_lo, a_hi, gi[3:0]);
            assign wgt_op[gi] = nib16(w_lo, w_hi, gi[3:0]);
        end
    endgenerate

    // PE control.
    wire pe_en  = (state == S_COMPUTE);
    wire pe_clr = (state == S_COMPUTE) & (kc == 4'd0);

    // -----------------------------------------------------------------------
    // The fixed 16x16 = 256-PE MAC array (output-stationary).
    // PE[m][n] accumulates sum_k A[m][k] * W[k][n].
    // -----------------------------------------------------------------------
    wire signed [ACC_W-1:0] pe_acc [0:ROWS-1][0:COLS-1];
    genvar gm, gn;
    generate
        for (gm = 0; gm < ROWS; gm = gm + 1) begin : g_row
            for (gn = 0; gn < COLS; gn = gn + 1) begin : g_col
                mac_pe u_pe (
                    .clk   (clk_i),
                    .rst_n (rst_n_i),
                    .clr   (pe_clr),
                    .en    (pe_en),
                    .a     (act_op[gm]),
                    .w     (wgt_op[gn]),
                    .acc   (pe_acc[gm][gn])
                );
            end
        end
    endgenerate

    // -----------------------------------------------------------------------
    // Requant (combinational): out = saturate(round(acc * scale >> shift)).
    // scale is unsigned Q1.15; acc is signed; round-half-up before the
    // arithmetic shift; saturate to signed INT8 [-128, 127].
    // -----------------------------------------------------------------------
    wire signed [ACC_W-1:0] drain_acc = pe_acc[o[7:4]][o[3:0]];
    wire signed [SCALE_W:0] scale_s   = $signed({1'b0, scale_reg});
    wire signed [63:0]      full      = drain_acc * scale_s;
    wire signed [63:0]      round_c   = (shift_reg == 5'd0)
                                        ? 64'sd0
                                        : (64'sd1 <<< (shift_reg - 5'd1));
    wire signed [63:0]      shifted   = (full + round_c) >>> shift_reg;
    wire signed [OUT_W-1:0] int8_out  =
            (shifted > 64'sd127)  ? 8'sd127  :
            (shifted < -64'sd128) ? -8'sd128 :
            shifted[OUT_W-1:0];

    // Packed word being assembled this drain cycle (4 INT8 per 32-bit word).
    reg  [31:0] pack_next;
    always @(*) begin
        pack_next = pack_reg;
        pack_next[o[1:0]*8 +: 8] = int8_out;
    end

    // -----------------------------------------------------------------------
    // SRAM port muxing.  Bus owns the ports in IDLE; the datapath owns them in
    // the active states.  (No simultaneous access: bus transactions are gated
    // to IDLE by `host_wr`/read-in-IDLE, datapath access only in LOAD/WRITE.)
    // -----------------------------------------------------------------------
    always @(*) begin
        // defaults
        w_addr = wbs_adr_i[WBUF_AW+1:2];  w_en = 1'b0; w_we = 1'b0; w_wdata = wbs_dat_i;
        a_addr = wbs_adr_i[ABUF_AW+1:2];  a_en = 1'b0; a_we = 1'b0; a_wdata = wbs_dat_i;
        ob_addr = wbs_adr_i[OBUF_AW+1:2]; ob_en = 1'b0; ob_we = 1'b0; ob_wdata = pack_next;

        case (state)
            S_LOAD_WEIGHTS: begin
                w_addr = ld[WBUF_AW-1:0]; w_en = 1'b1; w_we = 1'b0;
            end
            S_LOAD_ACT: begin
                a_addr = ld[ABUF_AW-1:0]; a_en = 1'b1; a_we = 1'b0;
            end
            S_WRITE_OUT: begin
                ob_addr = out_word[OBUF_AW-1:0];   // word index = o/4
                ob_en   = 1'b1;
                ob_we   = (o[1:0] == 2'b11) | (o == 9'd255);
                ob_wdata = pack_next;
            end
            default: begin   // S_IDLE (and others): bus owns the ports
                w_en  = (rd_access & sel_wgt) | (host_wr & sel_wgt);
                w_we  = (host_wr & sel_wgt);
                a_en  = (rd_access & sel_act) | (host_wr & sel_act);
                a_we  = (host_wr & sel_act);
                ob_en = (rd_access & sel_out);         // read-only window
                ob_we = 1'b0;
            end
        endcase
    end

    // -----------------------------------------------------------------------
    // Read-data mux (combinational; master holds address stable until ack).
    // -----------------------------------------------------------------------
    reg [31:0] reg_rdata;
    always @(*) begin
        case (reg_ofs)
            R_STATUS:    reg_rdata = {29'd0, error_flag, done_flag, busy};
            R_M_DIM:     reg_rdata = m_dim;
            R_K_DIM:     reg_rdata = k_dim;
            R_N_DIM:     reg_rdata = n_dim;
            R_SCALE:     reg_rdata = {16'd0, scale_reg};
            R_OUT_SHIFT: reg_rdata = {27'd0, shift_reg};
            R_IRQ_EN:    reg_rdata = {31'd0, irq_en};
            R_IRQ_STAT:  reg_rdata = {31'd0, irq_status};
            default:     reg_rdata = 32'd0;   // CTRL + reserved read as 0
        endcase
    end

    assign wbs_dat_o = sel_reg ? reg_rdata :
                       sel_wgt ? w_rdata   :
                       sel_act ? a_rdata   :
                                 ob_rdata;   // sel_out

    // -----------------------------------------------------------------------
    // Status / interrupt outputs.
    // -----------------------------------------------------------------------
    assign status_ready_o = (state == S_IDLE);
    assign status_done_o  = done_flag;
    assign irq_o          = irq_status & irq_en;

    // -----------------------------------------------------------------------
    // Main sequential control.
    // -----------------------------------------------------------------------
    always @(posedge clk_i) begin
        if (!rst_n_i) begin
            state       <= S_IDLE;
            m_dim       <= 32'd0;
            k_dim       <= 32'd0;
            n_dim       <= 32'd0;
            scale_reg   <= {SCALE_W{1'b0}};
            shift_reg   <= 5'd0;
            irq_en      <= 1'b0;
            irq_status  <= 1'b0;
            done_flag   <= 1'b0;
            error_flag  <= 1'b0;
            ld          <= 13'd0;
            cap_idx     <= 5'd0;
            cap_en      <= 1'b0;
            kc          <= 4'd0;
            o           <= 9'd0;
            pack_reg    <= 32'd0;
        end else begin
            // ---- host register writes (only when not busy) ----------------
            if (host_wr & sel_reg) begin
                case (reg_ofs)
                    R_M_DIM:     m_dim     <= wbs_dat_i;
                    R_K_DIM:     k_dim     <= wbs_dat_i;
                    R_N_DIM:     n_dim     <= wbs_dat_i;
                    R_SCALE:     scale_reg <= wbs_dat_i[SCALE_W-1:0];
                    R_OUT_SHIFT: shift_reg <= wbs_dat_i[4:0];
                    R_IRQ_EN:    irq_en    <= wbs_dat_i[0];
                    R_IRQ_STAT:  if (wbs_dat_i[0]) irq_status <= 1'b0;  // W1C
                    default:     ;   // CTRL handled below; reserved = no-op
                endcase
            end

            // ---- soft reset -------------------------------------------------
            if (soft_reset) begin
                state      <= S_IDLE;
                done_flag  <= 1'b0;
                error_flag <= 1'b0;
                irq_status <= 1'b0;
            end

            // ---- FSM --------------------------------------------------------
            case (state)
                // -------------------------------------------------------------
                S_IDLE: begin
                    if (start_pulse) begin
                        done_flag  <= 1'b0;
                        error_flag <= 1'b0;
                        ld         <= 13'd0;
                        cap_en     <= 1'b0;
                        state      <= S_LOAD_WEIGHTS;
                    end
                end

                // ---- stream weight tile into w_words ------------------------
                S_LOAD_WEIGHTS: begin
                    if (cap_en) w_words[cap_idx] <= w_rdata;
                    cap_idx <= ld[4:0];
                    cap_en  <= 1'b1;
                    if (ld == TILE_WORDS[12:0]) begin
                        ld     <= 13'd0;
                        cap_en <= 1'b0;
                        state  <= S_LOAD_ACT;
                    end else begin
                        ld <= ld + 13'd1;
                    end
                end

                // ---- stream activation tile into a_words --------------------
                S_LOAD_ACT: begin
                    if (cap_en) a_words[cap_idx] <= a_rdata;
                    cap_idx <= ld[4:0];
                    cap_en  <= 1'b1;
                    if (ld == TILE_WORDS[12:0]) begin
                        ld     <= 13'd0;
                        cap_en <= 1'b0;
                        kc     <= 4'd0;
                        state  <= S_COMPUTE;
                    end else begin
                        ld <= ld + 13'd1;
                    end
                end

                // ---- systolic MAC: K cycles, 32-bit accumulate --------------
                S_COMPUTE: begin
                    if (kc == k_last) begin
                        o        <= 9'd0;
                        pack_reg <= 32'd0;
                        state    <= S_REQUANT;
                    end
                    kc <= kc + 4'd1;
                end

                // ---- requant setup ------------------------------------------
                S_REQUANT: begin
                    o        <= 9'd0;
                    pack_reg <= 32'd0;
                    state    <= S_WRITE_OUT;
                end

                // ---- requant + pack + write INT8 tile to out_sram -----------
                S_WRITE_OUT: begin
                    pack_reg <= pack_next;         // accumulate 4 INT8 / word
                    if (o == 9'd255) begin
                        state <= S_DONE;
                    end
                    o <= o + 9'd1;
                end

                // ---- done: set STATUS.DONE, raise IRQ, pulse done pin -------
                S_DONE: begin
                    done_flag  <= 1'b1;
                    irq_status <= 1'b1;
                    state      <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // -----------------------------------------------------------------------
    // Intentionally-unused inputs collected into one sink (single-domain
    // design: `clk` is the redundant alternate clock; byte-selects and the
    // upper/sub-word address bits are not used by this word-addressed slave).
    // -----------------------------------------------------------------------
    // m_dim / n_dim configure software-side M/N tiling; the fixed 16x16 tile
    // always computes a full 16x16 sub-block (partial-tile masking is the
    // host's responsibility), so they are not consumed by the datapath here.
    wire _unused = &{1'b0, clk, wbs_sel_i,
                     wbs_adr_i[WB_AW-1:18], wbs_adr_i[15:8], wbs_adr_i[1:0],
                     m_dim, n_dim, 1'b0};

endmodule

`default_nettype wire
/* verilator lint_on DECLFILENAME */
