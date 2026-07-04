module dig_stopwatch #(
    parameter CLK_FREQ = 50000000  // Default clock frequency
)(
    input  wire        clk,            // Input clock (parameterized frequency)
    input  wire        reset,          // Asynchronous active-high reset
    input  wire        start_stop,     // Start/Stop control
    input  wire        load,           // Asynchronous active-high load
    input  wire [4:0]  load_hours,     // Hours to load   (0-23)
    input  wire [5:0]  load_minutes,   // Minutes to load (0-59)
    input  wire [5:0]  load_seconds,   // Seconds to load (0-59)
    output reg  [5:0]  seconds,        // Seconds counter (0-59)
    output reg  [5:0]  minutes,        // Minutes counter (0-59)
    output reg  [4:0]  hours           // Hours counter   (0-23)
);

    localparam [31:0] COUNTER_MAX = CLK_FREQ - 1; // one-second tick boundary

    reg [31:0] counter;        // clock divider counter
    reg        load_pending;   // a load was requested; capture on its release
    reg [4:0]  cur_hours;
    reg [5:0]  cur_minutes;
    reg [5:0]  cur_seconds;

    // range-clamped load values (out-of-range -> max valid value)
    wire [4:0] ld_hours   = (load_hours   > 5'd23) ? 5'd23 : load_hours;
    wire [5:0] ld_minutes = (load_minutes > 6'd59) ? 6'd59 : load_minutes;
    wire [5:0] ld_seconds = (load_seconds > 6'd59) ? 6'd59 : load_seconds;

    // one-second tick : asserted on the clock the divider rolls over
    wire tick = start_stop & ~load & (counter == COUNTER_MAX);

    // ----------------------------------------------------------------
    // Clock divider : rolls over every CLK_FREQ clocks while running.
    // Reset/load start a fresh one-second interval; stop holds it.
    // ----------------------------------------------------------------
    always @(posedge clk or posedge reset or posedge load) begin
        if (reset)
            counter <= 32'd0;
        else if (load)
            counter <= 32'd0;
        else if (start_stop) begin
            if (counter == COUNTER_MAX)
                counter <= 32'd0;
            else
                counter <= counter + 32'd1;
        end
        // else paused: retain counter
    end

    // ----------------------------------------------------------------
    // load_pending : set the instant load is asserted (async), held
    // while load is high, cleared on the first clock after release.
    // ----------------------------------------------------------------
    always @(posedge clk or posedge reset or posedge load) begin
        if (reset)
            load_pending <= 1'b0;
        else if (load)
            load_pending <= 1'b1;
        else
            load_pending <= 1'b0;
    end

    // ----------------------------------------------------------------
    // Count-down state : capture the (clamped) load value when load is
    // released, otherwise decrement on each one-second tick.
    // ----------------------------------------------------------------
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            cur_hours   <= 5'd0;
            cur_minutes <= 6'd0;
            cur_seconds <= 6'd0;
        end else if (load_pending && !load) begin
            cur_hours   <= ld_hours;
            cur_minutes <= ld_minutes;
            cur_seconds <= ld_seconds;
        end else if (tick) begin
            if (cur_seconds != 6'd0) begin
                cur_seconds <= cur_seconds - 6'd1;
            end else if (cur_minutes != 6'd0) begin
                cur_seconds <= 6'd59;
                cur_minutes <= cur_minutes - 6'd1;
            end else if (cur_hours != 5'd0) begin
                cur_seconds <= 6'd59;
                cur_minutes <= 6'd59;
                cur_hours   <= cur_hours - 5'd1;
            end else begin
                // hold at 00:00:00
                cur_seconds <= 6'd0;
                cur_minutes <= 6'd0;
                cur_hours   <= 5'd0;
            end
        end
    end

    // ----------------------------------------------------------------
    // Output mux : reset -> 0, load -> clamped values (async), else state
    // ----------------------------------------------------------------
    always @(*) begin
        if (reset) begin
            hours   = 5'd0;
            minutes = 6'd0;
            seconds = 6'd0;
        end else if (load) begin
            hours   = ld_hours;
            minutes = ld_minutes;
            seconds = ld_seconds;
        end else begin
            hours   = cur_hours;
            minutes = cur_minutes;
            seconds = cur_seconds;
        end
    end

endmodule
