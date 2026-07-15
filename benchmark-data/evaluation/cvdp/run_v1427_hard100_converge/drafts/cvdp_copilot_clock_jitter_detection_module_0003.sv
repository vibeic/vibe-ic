module clock_jitter_detection_module #(
    parameter JITTER_THRESHOLD = 5    // Threshold (in clock cycles) for detecting jitter
)(
    input logic clk,               // Input clock
    input logic system_clk,        // Input system clock
    input logic rst,               // Active high reset
    output logic jitter_detected   // Output flag indicating jitter detection
);

    // Internal signals
    logic [31:0] edge_count, edge_count_r;   // Counters to measure time between rising edges
    logic prev_system_clk;                   // To store the previous clock state (rising edge detection)
    logic edge_detected;                     // Flag for detecting rising edges
    logic start_counter;                     // Counting enabled once the first rising edge is seen

    // Power-up determinism: known values before the first reset is applied
    initial begin
        edge_count      = 32'd0;
        edge_count_r    = 32'd0;
        prev_system_clk = 1'b0;
        edge_detected   = 1'b0;
        start_counter   = 1'b0;
        jitter_detected = 1'b0;
    end

    // Rising edge detection logic (detects when clock transitions from 0 to 1)
    always @(posedge clk) begin
        if (rst) begin
            // Initialize counters, edge detection, and jitter detection on reset
            edge_count      <= 32'd0;
            edge_count_r    <= 32'd0;
            prev_system_clk <= 1'b0;
            edge_detected   <= 1'b0;
            start_counter   <= 1'b0;
            jitter_detected <= 1'b0;
        end else begin
            prev_system_clk <= system_clk;

            if (system_clk && !prev_system_clk) begin
                // Rising edge of system_clk observed on this clk edge
                edge_detected <= 1'b1;
                start_counter <= 1'b1;     // start measuring from the first edge

                // Store the just-completed edge-to-edge cycle count for
                // comparison and restart the counter at 1 (the edge cycle
                // itself is the first cycle of the new interval)
                edge_count_r  <= edge_count;
                edge_count    <= 32'd1;

                // Compare the recorded edge timing against JITTER_THRESHOLD.
                // Only a complete edge-to-edge interval participates
                // (start_counter gates out the warm-up before the first edge,
                // when no full interval exists yet). Jitter = the measured
                // interval deviates from JITTER_THRESHOLD by MORE than one
                // clock cycle, in either direction.
                if (start_counter &&
                    ((edge_count > JITTER_THRESHOLD + 1) ||
                     (edge_count + 32'd1 < JITTER_THRESHOLD)))
                    jitter_detected <= 1'b1;
                else
                    jitter_detected <= 1'b0;
            end else begin
                edge_detected   <= 1'b0;
                // jitter_detected is a one-cycle pulse: it resets on the next
                // clock cycle unless additional jitter is identified
                jitter_detected <= 1'b0;

                // Keep counting clk cycles between rising edges (saturate so a
                // stalled system_clk can never wrap the counter)
                if (start_counter && (edge_count != 32'hFFFF_FFFF))
                    edge_count <= edge_count + 32'd1;
            end
        end
    end

endmodule
