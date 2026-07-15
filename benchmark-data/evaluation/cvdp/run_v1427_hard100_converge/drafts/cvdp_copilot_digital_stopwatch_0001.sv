module dig_stopwatch #(
    parameter int CLK_FREQ = 50_000_000  // input clock frequency in Hz (integer, >= 1)
) (
    input  logic       clk,         // input clock used for 1 Hz pulse generation
    input  logic       reset,       // asynchronous active-high reset
    input  logic       start_stop,  // 1 = run, 0 = pause (counters and partial count held)
    output logic [5:0] seconds,     // 0-59
    output logic [5:0] minutes,     // 0-59
    output logic       hour         // sets to 1 when one hour has elapsed
);

    // -------------------------------------------------------------------
    // Internal clock divider: counts CLK_FREQ input-clock cycles and emits
    // a single pulse, one input-clock period wide, once every second.
    // The partial cycle count is RETAINED while paused so that counting
    // resumes from the exact point where it was stopped.
    // -------------------------------------------------------------------
    localparam int CNT_W = ($clog2(CLK_FREQ) > 0) ? $clog2(CLK_FREQ) : 1;
    localparam logic [CNT_W-1:0] CNT_MAX = CLK_FREQ - 1;

    logic [CNT_W-1:0] div_cnt;
    logic             running;
    logic             one_sec_pulse;

    // Stopwatch runs only while start_stop is high and it has not yet
    // reached the one-hour terminal state (holds at 1:00:00 until reset).
    assign running       = start_stop && !hour;

    // Single input-clock-period pulse marking that one full second elapsed.
    assign one_sec_pulse = running && (div_cnt == CNT_MAX);

    always_ff @(posedge clk or posedge reset) begin
        if (reset)
            div_cnt <= '0;
        else if (running) begin
            if (one_sec_pulse)
                div_cnt <= '0;
            else
                div_cnt <= div_cnt + 1'b1;
        end
        // paused: div_cnt holds its partial count (resume is seamless)
    end

    // -------------------------------------------------------------------
    // Time counters: cascaded rollover, updated once per one-second pulse.
    //   seconds: 0..59 -> wrap, carry into minutes
    //   minutes: 0..59 -> wrap, carry into hour
    //   hour   : single bit; once set, stopwatch holds 1:00:00 until reset
    // -------------------------------------------------------------------
    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            seconds <= 6'd0;
            minutes <= 6'd0;
            hour    <= 1'b0;
        end else if (one_sec_pulse) begin
            if (seconds == 6'd59) begin
                seconds <= 6'd0;
                if (minutes == 6'd59) begin
                    minutes <= 6'd0;
                    hour    <= 1'b1;  // one hour reached: hold at 1:00:00
                end else begin
                    minutes <= minutes + 6'd1;
                end
            end else begin
                seconds <= seconds + 6'd1;
            end
        end
    end

endmodule
