module run_length
#(
    parameter DATA_WIDTH = 8                          // Width of the output run-length counter
)
(
    input  wire                          clk,         // Clock signal
    input  wire                          reset_n,     // Active-low reset signal
    input  wire                          data_in,     // Input data stream
    output reg                           data_out,    // Output data to indicate the previous data_in
    output reg  [$clog2(DATA_WIDTH):0]   run_value,   // Output the run length value
    output reg                           valid        // Output valid flag for run length
);

    reg [$clog2(DATA_WIDTH):0] run_length;
    reg                        prev_data_in;

    // ----------------------------------------------------------------
    // Run-length counting and run_value update
    //   - matching data_in  : increment the consecutive-run counter,
    //     saturating at DATA_WIDTH (then emit the run and restart at 1)
    //   - differing data_in : a transition, emit the previous run and
    //     restart the counter at 1 for the new value
    // ----------------------------------------------------------------
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            run_length   <= 'b0;
            run_value    <= 'b0;
            prev_data_in <= 1'b0;
        end else begin
            if (data_in == prev_data_in) begin
                if (run_length >= DATA_WIDTH[$clog2(DATA_WIDTH):0]) begin
                    // saturation : emit the full run, restart at 1
                    run_value  <= run_length;
                    run_length <= 'd1;
                end else begin
                    run_length <= run_length + 'd1;
                end
            end else begin
                // transition : emit the previous run length, restart at 1
                run_value  <= run_length;
                run_length <= 'd1;
            end
            prev_data_in <= data_in;
        end
    end

    // ----------------------------------------------------------------
    // valid / data_out generation
    //   valid is HIGH on a transition OR when the run saturates at
    //   DATA_WIDTH, and LOW otherwise (one-cycle pulse behaviour).
    // ----------------------------------------------------------------
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            valid    <= 1'b0;
            data_out <= 1'b0;
        end else begin
            if (data_in != prev_data_in) begin
                valid    <= 1'b1;
                data_out <= prev_data_in;
            end else if (run_length >= DATA_WIDTH[$clog2(DATA_WIDTH):0]) begin
                valid    <= 1'b1;
                data_out <= prev_data_in;
            end else begin
                valid    <= 1'b0;
            end
        end
    end

endmodule
