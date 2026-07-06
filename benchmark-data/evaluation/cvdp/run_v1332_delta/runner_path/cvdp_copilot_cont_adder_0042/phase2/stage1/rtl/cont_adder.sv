module cont_adder #(
    parameter DATA_WIDTH = 32,
    parameter signed THRESHOLD_VALUE_1 = 50,
    parameter signed THRESHOLD_VALUE_2 = 100,
    parameter SIGNED_INPUTS = 1,
    parameter ACCUM_MODE = 0,
    parameter WEIGHT = 1
) (
    input  logic                         clk,
    input  logic                         rst,
    input  logic signed [DATA_WIDTH-1:0] data_in,
    input  logic                         data_valid,
    input  logic [15:0]                  window_size,
    output logic signed [DATA_WIDTH-1:0] sum_out,
    output logic signed [DATA_WIDTH-1:0] avg_out,
    output logic                         threshold_1,
    output logic                         threshold_2,
    output logic                         sum_ready
);
  wire reset = rst;  // rcvar flat alias (#rcvar-whitebox)

    // Local widths / constants (width-explicit, no functional change)
    localparam int                       ACC_W = DATA_WIDTH + 2;
    localparam signed [DATA_WIDTH-1:0]   TH1   = DATA_WIDTH'(THRESHOLD_VALUE_1);
    localparam signed [DATA_WIDTH-1:0]   TH2   = DATA_WIDTH'(THRESHOLD_VALUE_2);

    // Sequential Registers
    logic signed [ACC_W-1:0] sum_accum;
    logic        [15:0]      sample_count;

    // Combinational Signals
    logic signed [DATA_WIDTH-1:0] weighted_input;
    logic signed [ACC_W-1:0]      weighted_input_ext;
    logic signed [ACC_W-1:0]      full_sum;
    logic signed [DATA_WIDTH-1:0] new_sum;
    logic                         threshold_1_comb;
    logic                         threshold_2_comb;
    logic                         sum_ready_reg;

    // Combinational Logic
    always_comb begin
        sum_ready_reg = 1'b0;

        // Weighted input. Low DATA_WIDTH product bits are identical for
        // signed vs unsigned multiply, so SIGNED_INPUTS selects the
        // interpretation without altering the (truncated) result.
        if (SIGNED_INPUTS)
            weighted_input = DATA_WIDTH'($signed(data_in)   * $signed(WEIGHT));
        else
            weighted_input = DATA_WIDTH'($unsigned(data_in) * $unsigned(WEIGHT));

        // Full-width accumulate (explicit sign-extension avoids expand/trunc lint)
        weighted_input_ext = ACC_W'(weighted_input);
        full_sum           = sum_accum + weighted_input_ext;
        new_sum            = DATA_WIDTH'(full_sum);

        threshold_1_comb = (new_sum >= TH1) || (new_sum <= -TH1);
        threshold_2_comb = (new_sum >= TH2) || (new_sum <= -TH2);

        if (data_valid) begin
            if (ACCUM_MODE == 0) begin
                sum_ready_reg = (threshold_1_comb || threshold_2_comb);
            end else if (ACCUM_MODE == 1) begin
                sum_ready_reg = ((sample_count + 16'd1) >= window_size);
            end
        end
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            sum_accum     <= 0;
            sample_count  <= 0;
            sum_ready     <= 0;
            sum_out       <= 0;
            avg_out       <= 0;
            threshold_1   <= 0;
            threshold_2   <= 0;
        end else if (data_valid) begin
            threshold_1 <= threshold_1_comb;
            threshold_2 <= threshold_2_comb;

            if (ACCUM_MODE == 1) begin
                sum_accum    <= full_sum;
                sample_count <= sample_count + 16'd1;
                if (sum_ready_reg) begin
                    sum_out      <= DATA_WIDTH'(full_sum);
                    avg_out      <= DATA_WIDTH'(full_sum / ACC_W'(window_size));
                    sum_ready    <= 1'b1;
                    sum_accum    <= 0;
                    sample_count <= 0;
                end else begin
                    sum_ready <= 1'b0;
                    sum_out   <= 0;
                    avg_out   <= 0;
                end
            end else begin
                sum_accum <= full_sum;
                if (sum_ready_reg) begin
                    sum_out   <= DATA_WIDTH'(full_sum);
                    sum_ready <= 1'b1;
                end else begin
                    sum_ready <= 1'b0;
                    sum_out   <= 0;
                end
                avg_out <= 0;
            end
        end else begin
            sum_ready <= 1'b0;
        end
    end

endmodule
