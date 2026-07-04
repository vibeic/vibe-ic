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
    logic [31:0] cyc;                        // free-running clk counter (warm-up guard)
    logic prev_system_clk;                   // To store the previous clock state (rising edge detection)
    logic edge_detected;                     // Flag for detecting rising edges
    logic jitter_pre;                        // pre-output: jitter decision, delayed one clk to output

    // Rising edge detection of system_clk, sampled on clk
    assign edge_detected = system_clk & ~prev_system_clk;

    always @(posedge clk) begin
        if (rst) begin
            edge_count      <= 32'd1;
            edge_count_r    <= 32'd0;
            prev_system_clk <= 1'b0;
            jitter_detected <= 1'b0;
            jitter_pre      <= 1'b0;
            cyc             <= 32'd0;
        end else begin
            prev_system_clk <= system_clk;
            cyc             <= cyc + 32'd1;

            // one-cycle pulse source (default low) + one-clk delayed output
            jitter_pre      <= 1'b0;
            jitter_detected <= jitter_pre;

            if (edge_detected) begin
                // store the just-measured interval, restart counting from this edge
                edge_count_r <= edge_count;
                edge_count   <= 32'd1;

                // jitter when interval differs from threshold (after warm-up)
                if ((edge_count != JITTER_THRESHOLD) &&
                    (edge_count != 32'd0)            &&
                    (cyc        >  JITTER_THRESHOLD))
                    jitter_pre <= 1'b1;
            end else begin
                edge_count <= edge_count + 32'd1;
            end
        end
    end

endmodule
