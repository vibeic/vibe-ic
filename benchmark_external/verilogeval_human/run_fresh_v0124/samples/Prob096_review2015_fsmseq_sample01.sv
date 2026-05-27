module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);

  localparam S0   = 3'd0,  // start / nothing matched
             S1   = 3'd1,  // matched "1"
             S2   = 3'd2,  // matched "11"
             S3   = 3'd3,  // matched "110"
             DONE = 3'd4;  // matched "1101"
  reg [2:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else begin
      case (state)
        S0:   state <= data ? S1 : S0;
        S1:   state <= data ? S2 : S0;
        S2:   state <= data ? S2 : S3;
        S3:   state <= data ? DONE : S0;
        DONE: state <= DONE;
        default: state <= S0;
      endcase
    end
  end

  assign start_shifting = (state == DONE);

endmodule
