// Detect the sequence 1101 in 'data'. Once found, start_shifting=1 forever
// (until synchronous active-high reset). Moore FSM.
module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);

  localparam S0 = 3'd0, S1 = 3'd1, S2 = 3'd2, S3 = 3'd3, DONE = 3'd4;
  reg [2:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else begin
      case (state)
        S0:      state <= data ? S1 : S0;   // need 1
        S1:      state <= data ? S2 : S0;   // 1, need another 1
        S2:      state <= data ? S2 : S3;   // 11, then need 0
        S3:      state <= data ? DONE : S0; // 110, then need 1
        DONE:    state <= DONE;             // 1101 found, latch
        default: state <= S0;
      endcase
    end
  end

  assign start_shifting = (state == DONE);

endmodule
