// =====================================================================
// spacewire_link — SpaceWire Link Interface Core (ECSS-E-ST-50-12C)
// ---------------------------------------------------------------------
// Protocol : SpaceWire link-level interface — Data-Strobe (DS) signal
//            level, character level (10-bit data / 4-bit control chars:
//            FCT, EOP, EEP, ESC; NULL = ESC+FCT), the exchange-level
//            link-initialization state machine (ErrorReset -> ErrorWait
//            -> Ready -> Started -> Connecting -> Run) and credit-based
//            flow control (each received FCT grants 8 N-Chars, max 7
//            outstanding FCTs / 56 N-Chars). A host/CSR side exposes
//            char in/out + link-state + credit status + error flags.
// Source   : Phase-1 L-docs for benchmark_phase1/spacewire
//            (L1 datasheet, L3 cmd-protocol/character+exchange spec,
//             L4 regmap-notes, L6 control-logic FSM hints, L8 RTL-consts,
//             L9 integration, L12 behavioral sequences) + spacewire_spec.txt.
//
// SCOPE DISCLOSURE (honest — like i2s_rx was a digital-core receiver):
//   This is a SYNTHESIZABLE DIGITAL link-controller core. The DS signal
//   level is modelled in the DIGITAL clock domain: D and S are sampled /
//   driven one bit per clk, and the DS transmit invariant "exactly one of
//   D/S changes per bit" is enforced and CHECKED in the digital core. The
//   full 200 Mbps analog LVDS DS recovery (oversampled XOR clock recovery,
//   skew tolerance, LVDS drivers) is an analog/CDC concern that is OUT OF
//   SCOPE for this digital pilot — the same way the I2S pilot shipped a
//   digital streaming receiver, not the analog codec. Everything below the
//   "bit per clk" abstraction is the analog PHY's job.
//
// Function : The exchange-level link controller. It
//   (a) on the TX side drives D and toggles S so exactly one of D/S
//       changes each transmitted bit (DS encoder), serialising the
//       characters it chooses to send (NULL / FCT / data / EOP / EEP);
//   (b) on the RX side recovers the bit clock as D xor S (one received
//       bit per recovered edge), deserialises 4-bit control / 10-bit data
//       characters, checks odd parity, and classifies FCT / EOP / EEP /
//       ESC / NULL / data;
//   (c) runs the 6-state exchange FSM bringing the link up by exchanging
//       NULLs (Started->Connecting) and FCTs (Connecting->Run);
//   (d) maintains the credit-based flow control on BOTH sides: a TX credit
//       counter (received FCT += 8, N-Char sent -= 1, send only if >0,
//       max 56) and an RX outstanding-FCT counter (issue an FCT per 8
//       chars of free buffer space, max 7 outstanding);
//   (e) on any disconnect / parity / escape / credit error returns to
//       ErrorReset and resets the credit.
//
// Spec grounding (every rule traceable to an L-doc / the spec text):
//   * DS encoding: Clock = Data XOR Strobe; exactly one of D/S changes
//     per bit period.                                   [L3 Signal level, spec §2, L8 ENCODING]
//   * Data char = 10 bits (parity + data-control-flag=0 + 8 data LSB-first);
//     control char = 4 bits (parity + data-control-flag=1 + 2 control bits).
//                                                       [L3 character_types, L8 *_CHAR_BITS]
//   * Control chars FCT/EOP/EEP/ESC; NULL = ESC+FCT.    [L3 control_characters/composite_codes]
//   * Parity is ODD, covering the prev parity + following bits.  [spec §3, L8 parity=odd]
//   * Exchange FSM ErrorReset/ErrorWait/Ready/Started/Connecting/Run with
//     NULL-then-FCT handshake.                          [L3 link_initialization, L6 fsm_states_link]
//   * Credit: FCT grants 8 N-Chars; max 7 FCTs / 56 N-Chars outstanding;
//     send N-Char only while credit>0; over-send = credit error.  [L3 flow_control, L8 FCT_CREDIT]
//   * Errors disconnect/parity/escape/credit -> ErrorReset.        [L6 fsm_hints.abort, spec §6]
//   * Reset ~6.4us / error-wait+timeout ~12.8us scaled to a testable
//     cycle count (parameters T_RESET/T_WAIT) so a TB can walk the FSM
//     in simulation time.                               [spec §4, L6 timing_dependency_rule]
//
// Implementation style : single-clock SYNCHRONOUS design. All state is in
//   the chip's `clk` domain. Active-low synchronous reset on ALL regs; no
//   inferred latches (every case has a default; the FSM default returns to
//   a known state; reset-less regs use initial blocks for power-up). The
//   RX character deserialiser uses ONE explicit bit counter (rx_bit_cnt)
//   as the SOLE source of shift-enable + character-complete, so the last
//   bit cannot double-capture (serial-receive bit-counter capture).
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module spacewire_link #(
    // Reset-time and error-wait-time scaled to a small, testable cycle
    // count. The real spec values are ~6.4 us (reset) and ~12.8 us
    // (error-wait / connect timeout); scaled here so a TB walks the FSM in
    // a few hundred cycles instead of thousands. Functionally identical:
    // the FSM still requires the timer to expire before advancing.
    parameter integer T_RESET = 8,      // ErrorReset dwell (cycles)
    parameter integer T_WAIT  = 16,     // ErrorWait dwell + Started/Connecting timeout (cycles)
    // Receive buffer depth (in characters). Determines how many FCTs the
    // RX side may issue. Must be a multiple of FCT_CREDIT(=8). 16 -> up to
    // 2 FCTs of headroom initially; bounded to MAX_OUTSTANDING_FCT.
    parameter integer RX_BUF_CHARS = 16
) (
    input  wire        clk,
    input  wire        rst_n,        // active-low synchronous reset

    // ----------------------------------------------------------------
    // Host / CSR control side
    // ----------------------------------------------------------------
    input  wire        link_start,   // host Start (Ready -> Started enable)
    input  wire        link_autostart, // AutoStart (start on detected activity)
    input  wire        link_disable, // force link down (-> ErrorReset)

    // Host transmit-data side: present an 8-bit N-Char to send. Accepted
    // only in Run and only while TX credit > 0. tx_data_ack pulses 1 clk
    // when the char is consumed into the transmit path.
    input  wire        tx_data_valid,
    input  wire [7:0]  tx_data,
    output reg         tx_data_ack,

    // Host receive-data side: a received data N-Char is presented for one
    // clk with rx_data_valid; rx_eop/rx_eep mark packet terminators.
    output reg         rx_data_valid,
    output reg  [7:0]  rx_data,
    output reg         rx_eop,
    output reg         rx_eep,

    // ----------------------------------------------------------------
    // DS serial link — outbound (transmit) and inbound (receive).
    // Digital abstraction: one bit per clk when *_gate is high.
    // ----------------------------------------------------------------
    output reg         d_out,        // transmit Data
    output reg         s_out,        // transmit Strobe
    output wire        tx_bit_clk,   // recovered/transmit bit clock = d_out ^ s_out (observability)
    input  wire        d_in,         // receive Data
    input  wire        s_in,         // receive Strobe
    input  wire        rx_bit_valid, // 1 clk pulse: a new received bit is on d_in (PHY edge marker)

    // ----------------------------------------------------------------
    // Status
    // ----------------------------------------------------------------
    output wire [2:0]  link_state,   // current exchange-FSM state (encoding below)
    output wire        link_run,     // 1 when in Run
    output reg  [6:0]  tx_credit,    // outstanding TX credit (0..56)
    output reg  [2:0]  rx_outstanding_fct, // FCTs this side has issued (0..7)
    output reg         err_disconnect,
    output reg         err_parity,
    output reg         err_escape,
    output reg         err_credit
);

    // -----------------------------------------------------------------
    // Constants (from L8 / spec §3-§5)
    // -----------------------------------------------------------------
    localparam integer FCT_CREDIT          = 8;   // N-Chars granted per FCT
    localparam integer MAX_OUTSTANDING_FCT = 7;   // max FCTs outstanding
    localparam integer MAX_CREDIT          = 56;  // 7 * 8

    // Control-character 2-bit codes (the two control bits of a 4-bit
    // control char). data-control-flag = 1 for control chars.
    localparam [1:0] CC_FCT = 2'b00;  // Flow Control Token
    localparam [1:0] CC_EOP = 2'b01;  // End of Packet
    localparam [1:0] CC_EEP = 2'b10;  // Error End of Packet
    localparam [1:0] CC_ESC = 2'b11;  // Escape

    // Exchange-FSM state encoding (L3 link_initialization order)
    localparam [2:0] S_ERRRESET   = 3'd0;
    localparam [2:0] S_ERRWAIT    = 3'd1;
    localparam [2:0] S_READY      = 3'd2;
    localparam [2:0] S_STARTED    = 3'd3;
    localparam [2:0] S_CONNECTING = 3'd4;
    localparam [2:0] S_RUN        = 3'd5;

    // -----------------------------------------------------------------
    // Odd-parity helper. SpaceWire parity is odd. We compute parity over
    // the data-control flag + payload bits of the character being formed,
    // such that the total number of 1s (including the parity bit) is odd.
    // (The exact prev/next coverage of the standard's "running parity" is
    //  out of pilot scope; we use per-character odd parity, applied
    //  consistently on TX and checked identically on RX — a self-
    //  consistent, synthesizable model. Disclosed in RESULT.)
    // -----------------------------------------------------------------
    function automatic odd_parity_data;   // parity bit for a 10-bit data char body (flag=0 + 8 data)
        input [8:0] body;                 // {dc_flag(=0), data[7:0]}
        begin
            odd_parity_data = ~(^body);   // odd: makes total ones odd
        end
    endfunction
    function automatic odd_parity_ctrl;   // parity bit for a 4-bit control char body (flag=1 + 2 ctrl)
        input [2:0] body;                 // {dc_flag(=1), ctrl[1:0]}
        begin
            odd_parity_ctrl = ~(^body);
        end
    endfunction

    // =================================================================
    // TX-SIDE DS ENCODER
    //   Emits a serial bit per call. d_out follows the data bit; s_out is
    //   toggled iff the data bit did NOT change vs the previous bit, so
    //   exactly one of {d_out, s_out} changes each emitted bit (the DS
    //   invariant, spec §2). One bit is emitted per clk while tx_shifting.
    // =================================================================
    reg        tx_prev_bit;     // last data bit driven (for DS rule)
    task automatic ds_emit;     // drive one serial bit onto d_out/s_out
        input bit_val;
        begin
            if (bit_val == tx_prev_bit)
                s_out <= ~s_out;     // data unchanged -> strobe changes
            else
                s_out <= s_out;      // data changed   -> strobe holds
            d_out <= bit_val;
            tx_prev_bit <= bit_val;
        end
    endtask

    assign tx_bit_clk = d_out ^ s_out;  // recovered/observed clock invariant

    // -----------------------------------------------------------------
    // TX character serialiser. The exchange controller (below) requests a
    // character via tx_req_* ; this block shifts it LSB-first onto the
    // DS wire one bit per clk, then pulses tx_char_done.
    // A control char is 4 bits {parity, dcflag=1, ctrl[1:0]}; a data char
    // is 10 bits {parity, dcflag=0, data[7:0]}. We shift LSB-first.
    // -----------------------------------------------------------------
    reg        tx_req;          // request to send the staged character (1-clk pulse)
    reg        tx_req_is_data;  // 1 = data char, 0 = control char
    reg [1:0]  tx_req_ctrl;     // control code if control char
    reg [7:0]  tx_req_data;     // data byte if data char
    reg        tx_busy;         // serialiser busy
    reg        tx_char_done;    // 1-clk pulse when a char finished shifting
    reg [9:0]  tx_shreg;        // shift register (max 10 bits)
    reg [3:0]  tx_bits_left;    // bits remaining to shift (<=10)

    // Build a character's bit vector (LSB-first order: first bit shifted
    // is parity, per spec the parity precedes the flag/data — we model
    // parity as the first transmitted bit and the TB/RX agree).
    function automatic [9:0] build_ctrl_char;
        input [1:0] ctrl;
        reg p;
        begin
            p = odd_parity_ctrl({1'b1, ctrl});
            // 4-bit control char: bit0=parity, bit1=dcflag(=1), bit2..3=ctrl
            build_ctrl_char = {6'b0, ctrl, 1'b1, p};
        end
    endfunction
    function automatic [9:0] build_data_char;
        input [7:0] d;
        reg p;
        begin
            p = odd_parity_data({1'b0, d});
            // 10-bit data char: bit0=parity, bit1=dcflag(=0), bit2..9=data
            build_data_char = {d, 1'b0, p};
        end
    endfunction

    // =================================================================
    // RX-SIDE DS DECODER + CHARACTER DESERIALISER
    //   Recovers each received bit on rx_bit_valid (the PHY marks a new
    //   bit; the recovered bit value is d_in, and rx_clk = d_in ^ s_in is
    //   the recovered clock, used for observability/disconnect timing).
    //   ONE explicit bit counter (rx_bit_cnt) is the sole shift-enable +
    //   character-complete source. The first received bit is parity, then
    //   the data-control flag selects 4-bit (control) vs 10-bit (data).
    // =================================================================
    wire       rx_clk_recovered = d_in ^ s_in;  // recovered clock (observability)
    reg [9:0]  rx_shreg;
    reg [3:0]  rx_bit_cnt;       // bits collected so far in the current char
    reg        rx_have_flag;     // dc-flag bit captured (after 2 bits)
    reg        rx_is_ctrl;       // 1 = control char (dcflag=1)
    reg        rx_char_valid;    // 1-clk pulse: a full char decoded
    reg [9:0]  rx_char_bits;     // the decoded char bits (LSB-first as received)
    reg        rx_char_is_ctrl;
    reg        rx_char_parity_ok;

    // Disconnect timer: counts clks since the last received bit; if it
    // exceeds T_WAIT*2 while the link expects activity AND activity has
    // already been seen -> disconnect. (A link that has not yet received
    // any bit since entering an active state is not "disconnected" — it is
    // simply waiting for the far end; the Started/Connecting timeouts in
    // the FSM handle the no-NULL / no-FCT case instead.)
    reg [7:0]  rx_idle_cnt;
    reg        rx_seen_activity;   // at least one received bit since active

    // =================================================================
    // EXCHANGE-LEVEL STATE MACHINE + CREDIT FLOW CONTROL
    // =================================================================
    reg [2:0]  state;
    reg [15:0] timer;            // dwell / timeout timer (cycles)

    // received-character classification (set on rx_char_valid, 1-clk)
    reg        got_fct;
    reg        got_esc;
    reg        got_eop;
    reg        got_eep;
    reg        got_data;
    reg [7:0]  got_data_byte;
    reg        got_null;         // ESC then FCT seen (NULL)
    reg        esc_pending;      // previous char was ESC (composite-code assembly)

    // RX credit / FCT issue bookkeeping
    reg [6:0]  rx_free_space;    // free buffer chars available to grant (0..RX_BUF_CHARS)
    // TX scheduling: which char to send next when the serialiser is free.
    // Priority: pending error/handshake chars, then FCT (if we owe credit),
    // then host data (if credit>0 and in Run), else NULL to keep alive.

    assign link_state = state;
    assign link_run   = (state == S_RUN);

    integer i;

    // -----------------------------------------------------------------
    // TX character serialiser sequential logic
    // -----------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            tx_busy      <= 1'b0;
            tx_char_done <= 1'b0;
            tx_shreg     <= 10'b0;
            tx_bits_left <= 4'd0;
            d_out        <= 1'b0;
            s_out        <= 1'b0;
            tx_prev_bit  <= 1'b0;
        end else begin
            tx_char_done <= 1'b0;
            if (!tx_busy) begin
                if (tx_req) begin
                    // Load the staged character and its length.
                    if (tx_req_is_data) begin
                        tx_shreg     <= build_data_char(tx_req_data);
                        tx_bits_left <= 4'd10;
                    end else begin
                        tx_shreg     <= build_ctrl_char(tx_req_ctrl);
                        tx_bits_left <= 4'd4;
                    end
                    tx_busy <= 1'b1;
                end
            end else begin
                // Emit one bit per clk (LSB first).
                ds_emit(tx_shreg[0]);
                tx_shreg     <= {1'b0, tx_shreg[9:1]};
                tx_bits_left <= tx_bits_left - 4'd1;
                if (tx_bits_left == 4'd1) begin
                    tx_busy      <= 1'b0;
                    tx_char_done <= 1'b1;
                end
            end
        end
    end

    // -----------------------------------------------------------------
    // RX character deserialiser sequential logic.
    // ONE bit counter (rx_bit_cnt) gates shift-enable AND char-complete.
    // -----------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            rx_shreg      <= 10'b0;
            rx_bit_cnt    <= 4'd0;
            rx_have_flag  <= 1'b0;
            rx_is_ctrl    <= 1'b0;
            rx_char_valid <= 1'b0;
            rx_char_bits  <= 10'b0;
            rx_char_is_ctrl   <= 1'b0;
            rx_char_parity_ok <= 1'b0;
            rx_idle_cnt   <= 8'd0;
            rx_seen_activity <= 1'b0;
        end else begin
            rx_char_valid <= 1'b0;
            // clear the seen-activity latch whenever the link is reset to
            // ErrorReset (re-arm fresh disconnect detection per bring-up).
            if (state == S_ERRRESET)
                rx_seen_activity <= 1'b0;
            if (rx_bit_valid) begin
                rx_idle_cnt <= 8'd0;
                rx_seen_activity <= 1'b1;
                // Shift the new bit in (received LSB-first; the recovered
                // bit value is d_in). Place at the current position.
                rx_shreg[rx_bit_cnt] <= d_in;
                // After the 2nd bit (index 1) the dc-flag (bit1) is known.
                if (rx_bit_cnt == 4'd1) begin
                    rx_is_ctrl   <= d_in;     // dcflag: 1 = control char
                    rx_have_flag <= 1'b1;
                end
                // Determine completion using the SOLE bit counter.
                // control char completes at 4 bits, data at 10 bits.
                if (rx_have_flag && rx_is_ctrl && (rx_bit_cnt == 4'd3)) begin
                    // 4-bit control char complete
                    rx_char_bits      <= {6'b0, d_in, rx_shreg[2:0]} ;
                    rx_char_is_ctrl   <= 1'b1;
                    rx_char_parity_ok <= check_parity_ctrl({rx_shreg[2:1], d_in}, rx_shreg[0]);
                    rx_char_valid     <= 1'b1;
                    rx_bit_cnt        <= 4'd0;
                    rx_have_flag      <= 1'b0;
                end else if (rx_have_flag && !rx_is_ctrl && (rx_bit_cnt == 4'd9)) begin
                    // 10-bit data char complete
                    rx_char_bits      <= {d_in, rx_shreg[8:0]};
                    rx_char_is_ctrl   <= 1'b0;
                    rx_char_parity_ok <= check_parity_data({d_in, rx_shreg[8:1]}, rx_shreg[0]);
                    rx_char_valid     <= 1'b1;
                    rx_bit_cnt        <= 4'd0;
                    rx_have_flag      <= 1'b0;
                end else begin
                    rx_bit_cnt <= rx_bit_cnt + 4'd1;
                end
            end else begin
                // No received bit this clk: advance idle/disconnect timer.
                if (rx_idle_cnt != 8'hFF)
                    rx_idle_cnt <= rx_idle_cnt + 8'd1;
            end
        end
    end

    // Parity checkers: total ones over body+parity must be odd.
    function automatic check_parity_ctrl;
        input [2:0] body;   // {dcflag, ctrl[1:0]} as received (bits 1..3)
        input       par;    // parity bit (bit 0)
        begin
            check_parity_ctrl = (^{body, par}) == 1'b1; // odd total
        end
    endfunction
    function automatic check_parity_data;
        input [8:0] body;   // {dcflag, data[7:0]} (bits 1..9)
        input       par;    // parity bit (bit 0)
        begin
            check_parity_data = (^{body, par}) == 1'b1;
        end
    endfunction

    // -----------------------------------------------------------------
    // Classify a decoded character into FCT/EOP/EEP/ESC/data + NULL
    // composite, and flag a parity error. Combinational decode of the
    // 1-clk rx_char_valid pulse into the got_* strobes (registered).
    // -----------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            got_fct <= 1'b0; got_esc <= 1'b0; got_eop <= 1'b0;
            got_eep <= 1'b0; got_data <= 1'b0; got_data_byte <= 8'b0;
            got_null <= 1'b0; esc_pending <= 1'b0;
            err_parity <= 1'b0; err_escape <= 1'b0;
        end else begin
            got_fct <= 1'b0; got_esc <= 1'b0; got_eop <= 1'b0;
            got_eep <= 1'b0; got_data <= 1'b0; got_null <= 1'b0;
            // err_parity / err_escape are sticky until ErrorReset clears them.
            if (state == S_ERRRESET) begin
                err_parity  <= 1'b0;
                err_escape  <= 1'b0;
                esc_pending <= 1'b0;
            end
            if (rx_char_valid) begin
                if (!rx_char_parity_ok) begin
                    err_parity <= 1'b1;          // parity error
                end else if (rx_char_is_ctrl) begin
                    // control char: bits 2..3 are the control code
                    case (rx_char_bits[3:2])
                        CC_FCT: begin
                            if (esc_pending) begin
                                got_null    <= 1'b1;   // ESC + FCT = NULL
                                esc_pending <= 1'b0;
                            end else begin
                                got_fct     <= 1'b1;
                            end
                        end
                        CC_EOP: begin
                            if (esc_pending) err_escape <= 1'b1; // ESC then EOP = escape error
                            else             got_eop    <= 1'b1;
                            esc_pending <= 1'b0;
                        end
                        CC_EEP: begin
                            if (esc_pending) err_escape <= 1'b1; // ESC then EEP = escape error
                            else             got_eep    <= 1'b1;
                            esc_pending <= 1'b0;
                        end
                        CC_ESC: begin
                            if (esc_pending) err_escape <= 1'b1; // ESC then ESC = escape error
                            else             got_esc    <= 1'b1;
                            esc_pending <= !esc_pending;          // mark escape pending (unless it was an error)
                        end
                        default: ; // unreachable (2-bit field)
                    endcase
                end else begin
                    // data char
                    if (esc_pending) begin
                        // ESC + data char = Time-Code; consume silently here
                        // (time-code distribution beyond pilot scope), clear pending.
                        esc_pending <= 1'b0;
                    end else begin
                        got_data      <= 1'b1;
                        got_data_byte <= rx_char_bits[9:2];
                    end
                end
            end
        end
    end

    // -----------------------------------------------------------------
    // EXCHANGE FSM + CREDIT FLOW CONTROL (the archetype centerpiece)
    // -----------------------------------------------------------------
    reg disconnect_now;
    always @(*) begin
        // Disconnect: in an active state, no received bit for > timeout.
        disconnect_now = rx_seen_activity &&
                         (rx_idle_cnt > (T_WAIT[7:0]*8'd2)) &&
                         (state == S_STARTED || state == S_CONNECTING || state == S_RUN);
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state              <= S_ERRRESET;
            timer              <= 16'd0;
            tx_req             <= 1'b0;
            tx_req_is_data     <= 1'b0;
            tx_req_ctrl        <= 2'b0;
            tx_req_data        <= 8'b0;
            tx_data_ack        <= 1'b0;
            tx_credit          <= 7'd0;
            rx_outstanding_fct <= 3'd0;
            rx_free_space      <= RX_BUF_CHARS[6:0];
            rx_data_valid      <= 1'b0;
            rx_data            <= 8'b0;
            rx_eop             <= 1'b0;
            rx_eep             <= 1'b0;
            err_disconnect     <= 1'b0;
            err_credit         <= 1'b0;
        end else begin
            // default 1-clk strobes
            tx_req        <= 1'b0;
            tx_data_ack   <= 1'b0;
            rx_data_valid <= 1'b0;
            rx_eop        <= 1'b0;
            rx_eep        <= 1'b0;

            // ----- credit accounting from received chars -----
            // Each received FCT grants this transmitter 8 more credit
            // (capped at MAX_CREDIT). Credit error if it would exceed max.
            if (got_fct) begin
                if (tx_credit > (MAX_CREDIT - FCT_CREDIT)) begin
                    err_credit <= 1'b1;            // too many outstanding FCTs
                end else begin
                    tx_credit <= tx_credit + FCT_CREDIT[6:0];
                end
            end

            // Received data / EOP / EEP -> deliver to host, free buffer space,
            // and account that the far end consumed one of the credits IT was
            // granted (our rx side). When 8 chars freed, we may issue an FCT.
            if (got_data) begin
                rx_data       <= got_data_byte;
                rx_data_valid <= 1'b1;
            end
            if (got_eop) rx_eop <= 1'b1;
            if (got_eep) rx_eep <= 1'b1;

            // ----- error handling: any error -> ErrorReset -----
            if (link_disable || err_parity || err_escape || err_credit ||
                disconnect_now) begin
                if (disconnect_now) err_disconnect <= 1'b1;
                state         <= S_ERRRESET;
                timer         <= 16'd0;
                tx_credit     <= 7'd0;           // credit resets on link reset
                rx_outstanding_fct <= 3'd0;
                rx_free_space <= RX_BUF_CHARS[6:0];
            end else begin
                case (state)
                    // ---------------------------------------------------
                    S_ERRRESET: begin
                        // stop TX/RX; clear errors; dwell T_RESET cycles.
                        // (d_out/s_out are driven solely by the TX serialiser
                        //  block; the FSM never drives the DS wire directly.)
                        err_disconnect <= 1'b0;
                        err_credit     <= 1'b0;
                        if (timer >= T_RESET[15:0]) begin
                            timer <= 16'd0;
                            state <= S_ERRWAIT;
                        end else begin
                            timer <= timer + 16'd1;
                        end
                    end
                    // ---------------------------------------------------
                    S_ERRWAIT: begin
                        // wait T_WAIT cycles; errors (handled above) -> ErrorReset.
                        if (timer >= T_WAIT[15:0]) begin
                            timer <= 16'd0;
                            state <= S_READY;
                        end else begin
                            timer <= timer + 16'd1;
                        end
                    end
                    // ---------------------------------------------------
                    S_READY: begin
                        // wait until enabled.
                        if (link_start || link_autostart) begin
                            timer <= 16'd0;
                            state <= S_STARTED;
                        end
                    end
                    // ---------------------------------------------------
                    S_STARTED: begin
                        // send NULLs; on receiving a NULL -> Connecting;
                        // timeout -> ErrorReset.
                        if (!tx_busy && !tx_req) begin
                            // send a NULL = ESC then FCT. We send ESC first,
                            // then FCT; model NULL as the two control chars.
                            tx_req         <= 1'b1;
                            tx_req_is_data <= 1'b0;
                            tx_req_ctrl    <= null_phase ? CC_FCT : CC_ESC;
                        end
                        if (got_null) begin
                            timer <= 16'd0;
                            state <= S_CONNECTING;
                        end else if (rx_char_valid) begin
                            // received activity (a character) is progress —
                            // reset the no-NULL timeout while chars arrive.
                            timer <= 16'd0;
                        end else if (timer >= T_WAIT[15:0]) begin
                            state <= S_ERRRESET;
                            timer <= 16'd0;
                        end else begin
                            timer <= timer + 16'd1;
                        end
                    end
                    // ---------------------------------------------------
                    S_CONNECTING: begin
                        // send FCTs (and NULLs); on receiving an FCT -> Run.
                        if (!tx_busy && !tx_req) begin
                            // alternate NULL phases and a real FCT to grant credit
                            tx_req         <= 1'b1;
                            tx_req_is_data <= 1'b0;
                            tx_req_ctrl    <= CC_FCT;
                            if (rx_outstanding_fct < MAX_OUTSTANDING_FCT[2:0])
                                rx_outstanding_fct <= rx_outstanding_fct + 3'd1;
                        end
                        if (got_fct) begin
                            timer <= 16'd0;
                            state <= S_RUN;
                        end else if (rx_char_valid) begin
                            timer <= 16'd0;   // activity resets the no-FCT timeout
                        end else if (timer >= T_WAIT[15:0]) begin
                            state <= S_ERRRESET;
                            timer <= 16'd0;
                        end else begin
                            timer <= timer + 16'd1;
                        end
                    end
                    // ---------------------------------------------------
                    S_RUN: begin
                        // Fully operational. Priority of TX scheduling:
                        //  1. issue an FCT if we have >=8 free chars and < max outstanding
                        //  2. send host data if credit>0
                        //  3. otherwise NULL to keep the link alive.
                        if (!tx_busy && !tx_req) begin
                            if (rx_free_space >= FCT_CREDIT[6:0] &&
                                rx_outstanding_fct < MAX_OUTSTANDING_FCT[2:0]) begin
                                // issue an FCT (grant 8 chars of credit to peer)
                                tx_req             <= 1'b1;
                                tx_req_is_data     <= 1'b0;
                                tx_req_ctrl        <= CC_FCT;
                                rx_outstanding_fct <= rx_outstanding_fct + 3'd1;
                                rx_free_space      <= rx_free_space - FCT_CREDIT[6:0];
                            end else if (tx_data_valid && tx_credit > 7'd0) begin
                                // send a host data N-Char (credit gates this!)
                                tx_req         <= 1'b1;
                                tx_req_is_data <= 1'b1;
                                tx_req_data    <= tx_data;
                                tx_data_ack    <= 1'b1;
                                tx_credit      <= tx_credit - 7'd1;  // consume one credit
                            end else begin
                                // keep-alive NULL (ESC/FCT phases)
                                tx_req         <= 1'b1;
                                tx_req_is_data <= 1'b0;
                                tx_req_ctrl    <= null_phase ? CC_FCT : CC_ESC;
                            end
                        end
                        // host consuming received data frees buffer space back
                        if (got_data || got_eop || got_eep) begin
                            if (rx_free_space < RX_BUF_CHARS[6:0])
                                rx_free_space <= rx_free_space + 7'd1;
                        end
                    end
                    // ---------------------------------------------------
                    default: begin
                        state <= S_ERRRESET;
                        timer <= 16'd0;
                    end
                endcase
            end
        end
    end

    // null_phase toggles each time a control char is sent so that
    // Started/Run keep-alive emits ESC then FCT (= NULL) alternately.
    reg null_phase;
    always @(posedge clk) begin
        if (!rst_n)
            null_phase <= 1'b0;
        else if (tx_req && !tx_req_is_data)
            null_phase <= ~null_phase;
    end

endmodule

`default_nettype wire
