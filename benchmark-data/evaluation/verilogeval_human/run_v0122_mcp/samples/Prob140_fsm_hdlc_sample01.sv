module TopModule (
  input  clk,
  input  reset,
  input  in,
  output disc,
  output flag,
  output err
);

  // Moore FSM. State encodes the recent history of consecutive 1s and which
  // terminating event was just recognized. Outputs are a pure function of state.
  //  S0..S6  : count of consecutive 1s seen so far (0 through 6)
  //  D       : just saw 0 after exactly 5 ones (01111 1 0 = 0111110) -> disc
  //  F       : just saw 0 after exactly 6 ones (0111111 0 = 01111110) -> flag
  //  E       : error (7 or more consecutive 1s) -> err, stays until a 0 arrives
  localparam S0 = 4'd0, S1 = 4'd1, S2 = 4'd2, S3 = 4'd3,
             S4 = 4'd4, S5 = 4'd5, S6 = 4'd6,
             D  = 4'd7, F  = 4'd8, E  = 4'd9;

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0: next = in ? S1 : S0;
      S1: next = in ? S2 : S0;
      S2: next = in ? S3 : S0;
      S3: next = in ? S4 : S0;
      S4: next = in ? S5 : S0;          // 4 ones
      S5: next = in ? S6 : D;           // 5 ones: a 0 -> discard
      S6: next = in ? E  : F;           // 6 ones: a 0 -> flag, another 1 -> error
      D:  next = in ? S1 : S0;          // the 0 that ended the run is consumed
      F:  next = in ? S1 : S0;
      E:  next = in ? E  : S0;          // hold error until a 0 breaks the run
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S0;
    else       state <= next;
  end

  assign disc = (state == D);
  assign flag = (state == F);
  assign err  = (state == E);

endmodule
