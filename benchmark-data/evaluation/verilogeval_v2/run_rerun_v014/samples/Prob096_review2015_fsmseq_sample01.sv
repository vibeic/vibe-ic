module TopModule (
  input  clk,
  input  reset,
  input  data,
  output start_shifting
);

  // Detect the sequence 1101 in the input stream. Once seen, hold
  // start_shifting = 1 forever (until synchronous active-high reset).
  localparam S0   = 3'd0;  // no progress
  localparam S1   = 3'd1;  // "1"
  localparam S2   = 3'd2;  // "11"
  localparam S3   = 3'd3;  // "110"
  localparam DONE = 3'd4;  // "1101" detected

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      S0:      next = data ? S1 : S0;
      S1:      next = data ? S2 : S0;
      S2:      next = data ? S2 : S3;
      S3:      next = data ? DONE : S0;
      DONE:    next = DONE;
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else
      state <= next;
  end

  assign start_shifting = (state == DONE);

endmodule
