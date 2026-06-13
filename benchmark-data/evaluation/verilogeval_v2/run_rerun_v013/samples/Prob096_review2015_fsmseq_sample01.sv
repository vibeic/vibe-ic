module TopModule (
  input  clk,
  input  reset,
  input  data,
  output start_shifting
);

  // Moore FSM detecting the sequence 1101 in the data stream.
  // Once detected, stay in DONE (start_shifting=1) until reset.
  reg [2:0] state;

  localparam S0   = 3'd0; // no progress
  localparam S1   = 3'd1; // "1"
  localparam S2   = 3'd2; // "11"
  localparam S3   = 3'd3; // "110"
  localparam DONE = 3'd4; // "1101" detected

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else begin
      case (state)
        S0:      state <= data ? S1 : S0;
        S1:      state <= data ? S2 : S0;
        S2:      state <= data ? S2 : S3;
        S3:      state <= data ? DONE : S0;
        DONE:    state <= DONE;
        default: state <= S0;
      endcase
    end
  end

  assign start_shifting = (state == DONE);

endmodule
