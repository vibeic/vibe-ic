// =====================================================================
// sent_rx — SENT (SAE J2716) Receiver / Decoder IP block
// ---------------------------------------------------------------------
// Protocol : Single Edge Nibble Transmission (SENT), SAE J2716
// Source   : Phase-1 L-docs for benchmark_phase1/sent
//            (L1 datasheet, L3 cmd-protocol/frame, L6 control-logic FSM,
//             L8 RTL-constants/timing, L9 integration, L17 signal catalog)
//
// Function : Recovers data nibbles from the single-wire SENT stream by
//            measuring the time (in the chip's own `clk` ticks) between
//            successive FALLING edges of the SENT signal.  Every frame
//            opens with a synchronization/calibration pulse of nominally
//            56 SENT-ticks; the receiver measures that pulse to recover
//            the per-frame tick time, then decodes each following pulse
//            as a nibble whose value = round(period / tick_time) - 12.
//            The frame is status-nibble + 1..N data nibbles + CRC-4 nibble.
//            Outputs the decoded data nibbles, a CRC-valid flag, and a
//            one-clock frame-valid strobe.
//
// Spec grounding (every rule traceable to an L-doc):
//   * Data carried as falling-edge-to-falling-edge period in ticks. [L1,L3,L17]
//   * tick (unit time) recovered each frame from the 56-tick
//     synchronization/calibration pulse: tick = cal_period / 56.   [L3,L6,L8]
//   * nibble pulse period = 12 + value ticks, value 0..15
//     => value = round(period_ticks / tick) - 12, clamp 0..15.     [L3,L8]
//   * Frame order: CAL pulse -> status nibble -> 1..6 data nibbles
//     -> CRC-4 nibble (-> optional pause).                         [L3,L8,L17]
//   * CRC-4 (SAE J2716) over the data nibbles, seed 5, nibble-wise
//     polynomial table (x^4 + x^3 + x^2 + 1).                       [L3,L8]
//   * Receiver FSM: WAIT_CAL -> DECODE_STATUS -> DECODE_DATA
//     -> DECODE_CRC -> FRAME_DONE -> WAIT_CAL.                      [L6]
//   * Resync rule: a pulse whose measured tick-count >= the CAL
//     threshold is treated as a new calibration pulse (the CAL pulse
//     is longer than any nibble pulse), so the decoder self-recovers. [L9]
//
// Implementation style : single-clock SYNCHRONOUS receiver.  The external
//   single-wire SENT signal is asynchronous to the chip's `clk`; it is
//   double-flop CDC-synchronized, then falling edges are detected in the
//   `clk` domain.  A free-running counter measures the clk-cycle interval
//   between successive falling edges; that interval IS the pulse period in
//   `clk` ticks.  `clk` must be many times faster than one SENT-tick so the
//   periods resolve (standard oversampled receiver).  The 56-tick CAL pulse
//   gives the clk-cycles-per-SENT-tick scale for the current frame.
//
// Hygiene: active-low synchronous reset on ALL state; every reg reset;
//   no inferred latches (all branches assign, FSM has default); no
//   full/parallel-case reliance; reset-less regs N/A (all reset).
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module sent_rx #(
    // Number of fast-channel DATA nibbles in a frame (1..6 per L8).  6 is
    // the canonical two-12-bit-channel sensor configuration.
    parameter integer NUM_DATA_NIBBLES = 6,
    // Width of the free-running clk-cycle period counter.  Must hold the
    // longest pulse (the ~56-tick CAL pulse) in clk cycles.  16 bits covers
    // a CAL pulse up to 65535 clk cycles (e.g. tick = ~1170 clk @ 56 ticks).
    parameter integer PERIOD_W = 16
) (
    input  wire                              clk,         // chip sample clock
    input  wire                              rst_n,       // active-low sync reset

    // ---- SENT single-wire serial input (receiver side) ----
    input  wire                              sent_in,     // single SENT signal wire [L17]

    // ---- Recovered fast-channel outputs ----
    output reg  [4*NUM_DATA_NIBBLES-1:0]     data_nibbles,// concatenated decoded data nibbles
                                                          //   [3:0]=first data nibble, etc.
    output reg  [3:0]                        status_nibble,// decoded status & serial-comm nibble
    output reg                               crc_ok,      // 1 = recomputed CRC-4 == received CRC nibble
    output reg                               frame_valid  // 1-clk strobe: a complete frame decoded
);

    // -----------------------------------------------------------------
    // Derived constants
    // -----------------------------------------------------------------
    localparam integer SYNC_CAL_TICKS  = 56;   // nominal CAL pulse, SENT ticks [L8]
    localparam integer NIBBLE_OFFSET   = 12;   // nibble period = 12 + value    [L8]
    localparam integer NIBBLE_VALUE_MAX= 15;   // value range 0..15             [L8]
    // A pulse is the CAL pulse if its period (in ticks) is at least this many.
    // Nibble periods top out at 27 ticks (12+15); the CAL pulse is ~56, so a
    // generous midpoint threshold (>=40 ticks) cleanly separates them. [L8,L9]
    localparam integer CAL_TICK_THRESH = 40;

    // Nibble index counter must hold 0..(NUM_DATA_NIBBLES) (status counted
    // separately).  Sized for the data-nibble count.
    localparam integer NIDX_W = (NUM_DATA_NIBBLES <= 1) ? 1 :
                                $clog2(NUM_DATA_NIBBLES + 1);

    // -----------------------------------------------------------------
    // 1. CDC synchronizer — 2-flop for the async single-wire input.
    // -----------------------------------------------------------------
    reg [1:0] sin_sync;
    always @(posedge clk) begin
        if (!rst_n) sin_sync <= 2'b11;            // line idles HIGH [L8/L17]
        else        sin_sync <= {sin_sync[0], sent_in};
    end
    wire sin_s = sin_sync[1];                     // synchronized SENT signal

    // -----------------------------------------------------------------
    // 2. Falling-edge detection in `clk` domain.  SENT measures
    //    falling-edge to falling-edge. [L1,L3,L17]
    // -----------------------------------------------------------------
    reg sin_s_d;
    always @(posedge clk) begin
        if (!rst_n) sin_s_d <= 1'b1;              // idle-high
        else        sin_s_d <= sin_s;
    end
    wire falling = (~sin_s) & sin_s_d;            // HIGH->LOW edge

    // -----------------------------------------------------------------
    // 3. Period measurement: free-running clk-cycle counter between
    //    successive falling edges.  On a falling edge the counter value
    //    is the just-completed pulse period in clk cycles, and the
    //    counter restarts.
    // -----------------------------------------------------------------
    reg [PERIOD_W-1:0] period_cnt;                // clk cycles since last falling edge
    reg [PERIOD_W-1:0] last_period;               // captured pulse period (clk cycles)
    reg                pulse_stb;                  // 1-clk: a new pulse period is ready
    reg                armed;                      // set after the FIRST falling edge

    always @(posedge clk) begin
        if (!rst_n) begin
            period_cnt  <= {PERIOD_W{1'b0}};
            last_period <= {PERIOD_W{1'b0}};
            pulse_stb   <= 1'b0;
            armed       <= 1'b0;
        end else begin
            pulse_stb <= 1'b0;
            if (falling) begin
                // The FIRST falling edge only STARTS measurement (the count
                // before it is the pre-frame idle gap, not a real pulse).
                // Every subsequent falling edge closes a true pulse period.
                if (armed) begin
                    last_period <= period_cnt;    // period of the pulse that just ended
                    pulse_stb   <= 1'b1;
                end
                armed      <= 1'b1;
                period_cnt <= {{(PERIOD_W-1){1'b0}}, 1'b1}; // restart (count this cycle)
            end else if (period_cnt != {PERIOD_W{1'b1}}) begin
                period_cnt <= period_cnt + 1'b1;  // saturate to avoid wrap
            end
        end
    end

    // -----------------------------------------------------------------
    // 4. Per-frame tick scale.  On the CAL pulse, tick_clk = cal_period/56.
    //    Stored as clk-cycles-per-SENT-tick for the current frame.
    // -----------------------------------------------------------------
    reg [PERIOD_W-1:0] tick_clk;                  // clk cycles per 1 SENT tick

    // Combinational nibble decode for the current pulse period, using the
    // frame's tick scale: value = round(period/tick) - 12, clamped 0..15.
    // round(period/tick) = (period + tick/2) / tick.
    wire [PERIOD_W-1:0] tick_half   = (tick_clk >> 1);
    wire [PERIOD_W+1:0] period_ext  = {2'b00, last_period} + {2'b00, tick_half};
    // Guard divide-by-zero (tick_clk==0 before first calibration).
    wire [PERIOD_W+1:0] ticks_meas  = (tick_clk == {PERIOD_W{1'b0}}) ? {(PERIOD_W+2){1'b0}}
                                                                     : (period_ext / {2'b00, tick_clk});
    wire [PERIOD_W+1:0] val_pre     = (ticks_meas >= NIBBLE_OFFSET) ?
                                          (ticks_meas - NIBBLE_OFFSET) : {(PERIOD_W+2){1'b0}};
    wire [3:0]          nibble_val  = (val_pre > NIBBLE_VALUE_MAX) ? 4'hF : val_pre[3:0];

    // Is the just-ended pulse the (long) calibration pulse?  The CAL pulse
    // (~56 ticks) is always longer than any nibble pulse (<=27 ticks).
    //   * Cold start (no tick scale yet, tick_clk==0): the FIRST measured
    //     pulse is, by the protocol's frame-start rule, the CAL pulse.
    //   * Calibrated: raw period >= CAL_TICK_THRESH * tick_clk clk cycles.
    //     (CAL_TICK_THRESH ticks cleanly separates nibbles from the CAL pulse.)
    wire [PERIOD_W+1:0] cal_raw_thresh = CAL_TICK_THRESH[PERIOD_W+1:0] * {2'b00, tick_clk};
    wire                is_cal_pulse   = (tick_clk == {PERIOD_W{1'b0}})
                                            ? 1'b1
                                            : ({2'b00, last_period} >= cal_raw_thresh);

    // -----------------------------------------------------------------
    // 5. Receiver FSM.  [L6 fsm_states_receiver]
    // -----------------------------------------------------------------
    localparam [2:0] S_WAIT_CAL = 3'd0,  // wait for the 56-tick calibration pulse
                     S_STATUS   = 3'd1,  // next pulse = status nibble
                     S_DATA     = 3'd2,  // next NUM_DATA_NIBBLES pulses = data
                     S_CRC      = 3'd3,  // next pulse = CRC nibble
                     S_DONE     = 3'd4;  // emit frame_valid, return to WAIT_CAL

    reg [2:0]               state;
    reg [NIDX_W-1:0]        ndx;                  // data-nibble index within frame

    // Working / shadow registers accumulated during a frame.
    reg [4*NUM_DATA_NIBBLES-1:0] data_acc;
    reg [3:0]                    status_acc;
    reg [3:0]                    crc_running;     // CRC-4 accumulated over data nibbles
    reg [3:0]                    crc_rx;          // received CRC nibble

    // SAE J2716 CRC-4 step: nibble-wise update of a 4-bit CRC using the
    // standard polynomial x^4+x^3+x^2+1 (table 0,13,7,10,14,3,9,4,1,12,
    // 6,11,15,2,8,5).  crc_next = TABLE[crc ^ data_nibble].
    function [3:0] crc4_step;
        input [3:0] crc_in;
        input [3:0] data_in;
        reg   [3:0] idx;
        begin
            idx = crc_in ^ data_in;
            case (idx)
                4'd0:  crc4_step = 4'd0;
                4'd1:  crc4_step = 4'd13;
                4'd2:  crc4_step = 4'd7;
                4'd3:  crc4_step = 4'd10;
                4'd4:  crc4_step = 4'd14;
                4'd5:  crc4_step = 4'd3;
                4'd6:  crc4_step = 4'd9;
                4'd7:  crc4_step = 4'd4;
                4'd8:  crc4_step = 4'd1;
                4'd9:  crc4_step = 4'd12;
                4'd10: crc4_step = 4'd6;
                4'd11: crc4_step = 4'd11;
                4'd12: crc4_step = 4'd15;
                4'd13: crc4_step = 4'd2;
                4'd14: crc4_step = 4'd8;
                default: crc4_step = 4'd5;        // 4'd15  (default => no latch)
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            state         <= S_WAIT_CAL;
            ndx           <= {NIDX_W{1'b0}};
            tick_clk      <= {PERIOD_W{1'b0}};
            data_acc      <= {(4*NUM_DATA_NIBBLES){1'b0}};
            status_acc    <= 4'd0;
            crc_running   <= 4'd5;                // SAE J2716 CRC-4 seed = 5
            crc_rx        <= 4'd0;
            data_nibbles  <= {(4*NUM_DATA_NIBBLES){1'b0}};
            status_nibble <= 4'd0;
            crc_ok        <= 1'b0;
            frame_valid   <= 1'b0;
        end else begin
            frame_valid <= 1'b0;                  // single-cycle strobe by default

            // A CAL pulse anywhere forces (re)synchronization to a new frame.
            if (pulse_stb && is_cal_pulse) begin
                // Recalibrate the tick scale for the new frame: tick = cal/56.
                tick_clk    <= last_period / SYNC_CAL_TICKS[PERIOD_W-1:0];
                state       <= S_STATUS;
                ndx         <= {NIDX_W{1'b0}};
                crc_running <= 4'd5;              // reseed CRC-4 each frame
                data_acc    <= {(4*NUM_DATA_NIBBLES){1'b0}};
                status_acc  <= 4'd0;
            end else if (pulse_stb) begin
                // A normal nibble pulse, decoded with the frame's tick scale.
                case (state)
                    S_WAIT_CAL: begin
                        // Still waiting for the first CAL pulse: ignore nibbles.
                        state <= S_WAIT_CAL;
                    end

                    S_STATUS: begin
                        status_acc <= nibble_val;
                        // J2716 "recommended" CRC includes the status nibble;
                        // this build computes CRC over DATA nibbles only (the
                        // L3 default coverage), so status does NOT update CRC.
                        ndx        <= {NIDX_W{1'b0}};
                        state      <= S_DATA;
                    end

                    S_DATA: begin
                        // Place this nibble into its slot (first data nibble in
                        // [3:0], i.e. LSB-end), and fold it into the CRC.
                        data_acc[4*ndx +: 4] <= nibble_val;
                        crc_running          <= crc4_step(crc_running, nibble_val);
                        if (ndx == (NUM_DATA_NIBBLES-1)) begin
                            state <= S_CRC;
                        end else begin
                            ndx   <= ndx + 1'b1;
                        end
                    end

                    S_CRC: begin
                        crc_rx <= nibble_val;
                        state  <= S_DONE;
                        // Publish results; compare CRC on the DONE edge below.
                        data_nibbles  <= data_acc;
                        status_nibble <= status_acc;
                        crc_ok        <= (crc_running == nibble_val);
                        frame_valid   <= 1'b1;     // 1-clk frame-complete strobe
                        // After CRC, wait for the next CAL pulse to start anew.
                        state  <= S_WAIT_CAL;
                    end

                    S_DONE: begin
                        state <= S_WAIT_CAL;
                    end

                    default: begin                 // no inferred latch
                        state <= S_WAIT_CAL;
                    end
                endcase
            end
        end
    end

endmodule

`default_nettype wire
