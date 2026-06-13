module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);

  localparam [2:0] S    = 3'd0,
                   S1   = 3'd1,
                   S11  = 3'd2,
                   S110 = 3'd3,
                   DONE = 3'd4;

  reg [2:0] state, next_state;

  always @(*) begin
    case (state)
      S:    next_state = data ? S1   : S;
      S1:   next_state = data ? S11  : S;
      S11:  next_state = data ? S11  : S110;
      S110: next_state = data ? DONE : S;
      DONE: next_state = DONE;
      default: next_state = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S;
    else
      state <= next_state;
  end

  assign start_shifting = (state == DONE);

endmodule
