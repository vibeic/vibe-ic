module sgd_linear_regression #(
    parameter DATA_WIDTH = 16,
    parameter LEARNING_RATE = 3'd1
) (
    input  logic clk,                               // Clock
    input  logic reset,                             // Asynchronous reset
    input  logic signed [DATA_WIDTH-1:0] x_in,      // Input data (x)
    input  logic signed [DATA_WIDTH-1:0] y_true,    // True output (target)
    output logic signed [DATA_WIDTH-1:0] w,     // Trained weight
    output logic signed [DATA_WIDTH-1:0] b      // Trained bias
);
    localparam NBW_PRED  = 2*DATA_WIDTH + 1;
    localparam NBW_ERROR = NBW_PRED + 1;
    localparam NBW_DELTA = 3 + NBW_ERROR + DATA_WIDTH;

    // Learning rate as a signed constant (allowed values 0, 1, 2 -> MSB is 0,
    // so zero-extension keeps the value; a signed operand is required so the
    // delta multiplications stay fully signed and sign-extend a negative error).
    localparam logic signed [3:0] LR_S = {1'b0, LEARNING_RATE[2:0]};

    // Intermediate values
    logic signed [NBW_PRED-1:0] y_pred;
    logic signed [NBW_ERROR-1:0] error;
    logic signed [NBW_DELTA-1:0] delta_w;
    logic signed [NBW_DELTA-1:0] delta_b;

    // Predicted output caculation
    always_comb begin
      y_pred = (w * x_in) + b;
    end

    // Error calculation: error = y_true - y_pred (combinational, zero latency)
    always_comb begin
      error = y_true - y_pred;
    end

    // Weight and bias update terms (combinational, zero latency)
    //   delta_w = LEARNING_RATE * error * x_in
    //   delta_b = LEARNING_RATE * error
    always_comb begin
      delta_w = LR_S * error * x_in;
      delta_b = LR_S * error;
    end

    // Register update: w and b take the DATA_WIDTH least significant bits of
    // the full-precision sums; asynchronous active-high reset clears both.
    always_ff @(posedge clk or posedge reset) begin
      if (reset) begin
        w <= '0;
        b <= '0;
      end else begin
        w <= DATA_WIDTH'(w + delta_w);
        b <= DATA_WIDTH'(b + delta_b);
      end
    end

endmodule
