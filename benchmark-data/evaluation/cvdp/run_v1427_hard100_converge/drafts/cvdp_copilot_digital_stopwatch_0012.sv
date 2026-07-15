module dig_stopwatch #(
    parameter CLK_FREQ = 50000000  // Default clock frequency is 50 MHz
)(
    input  wire       clk,          // Input clock (parameterized frequency)
    input  wire       reset,        // Reset signal (async, active high)
    input  wire       start_stop,   // Start/Stop control
    input  wire       load,         // Asynchronous active-high load control
    input  wire [4:0] load_hours,   // Hours load value   (valid 0-23)
    input  wire [5:0] load_minutes, // Minutes load value (valid 0-59)
    input  wire [5:0] load_seconds, // Seconds load value (valid 0-59)
    output reg  [5:0] seconds,      // Seconds counter (0-59)
    output reg  [5:0] minutes,      // Minutes counter (0-59)
    output reg  [4:0] hour          // Hour counter (0-23)
);

    localparam COUNTER_MAX = CLK_FREQ - 1;  // Max divider count for one second
    reg [$clog2(COUNTER_MAX):0] counter;    // Clock divider counter

    // Clamp out-of-range load values to their maximum valid value
    wire [4:0] hours_clamped   = (load_hours   > 5'd23) ? 5'd23 : load_hours;
    wire [5:0] minutes_clamped = (load_minutes > 6'd59) ? 6'd59 : load_minutes;
    wire [5:0] seconds_clamped = (load_seconds > 6'd59) ? 6'd59 : load_seconds;

    // One-second rollover tick: fires on the clk edge where the divider wraps.
    wire one_sec_tick = start_stop && (counter == COUNTER_MAX);

    // Clock divider: counts only while running (start_stop high, load low).
    // Pausing (start_stop low) RETAINS the partial count so resume is
    // seamless; loading restarts the one-second interval.
    always @(posedge clk or posedge reset or posedge load) begin
        if (reset) begin
            counter <= 0;
        end else if (load) begin
            counter <= 0;
        end else if (start_stop) begin
            if (counter == COUNTER_MAX)
                counter <= 0;
            else
                counter <= counter + 1'b1;
        end
    end

    // Countdown timer: reset > load > decrement (cascaded borrow chain).
    always @(posedge clk or posedge reset or posedge load) begin
        if (reset) begin
            seconds <= 6'd0;
            minutes <= 6'd0;
            hour    <= 5'd0;
        end else if (load) begin
            seconds <= seconds_clamped;
            minutes <= minutes_clamped;
            hour    <= hours_clamped;
        end else if (one_sec_tick) begin
            if (seconds != 6'd0) begin
                seconds <= seconds - 6'd1;
            end else if (minutes != 6'd0) begin
                seconds <= 6'd59;
                minutes <= minutes - 6'd1;
            end else if (hour != 5'd0) begin
                seconds <= 6'd59;
                minutes <= 6'd59;
                hour    <= hour - 5'd1;
            end
            // else: hold at 00:00:00 until reset or a new load
        end
    end

endmodule
