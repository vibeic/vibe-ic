module TopModule (
  input clk,
  input reset,
  input in,
  output disc,
  output flag,
  output err
);

  // Moore FSM counting consecutive 1s.
  // D0..D6 = 0..6 consecutive ones seen.
  // DISC : reached after 0111110 (5 ones then 0) -> assert disc one cycle.
  // FLAG : reached after 01111110 (6 ones then 0) -> assert flag one cycle.
  // ERR  : 7 or more consecutive ones -> assert err until a 0 arrives.
  localparam D0=4'd0, D1=4'd1, D2=4'd2, D3=4'd3, D4=4'd4, D5=4'd5, D6=4'd6,
             DISC=4'd7, FLAG=4'd8, ERR=4'd9;

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      D0:   next = in ? D1 : D0;
      D1:   next = in ? D2 : D0;
      D2:   next = in ? D3 : D0;
      D3:   next = in ? D4 : D0;
      D4:   next = in ? D5 : D0;
      D5:   next = in ? D6   : DISC;  // 5 ones; a 0 is a stuffed bit to discard
      D6:   next = in ? ERR  : FLAG;  // 6 ones; a 0 is a frame flag
      DISC: next = in ? D1 : D0;      // trailing 0 already consumed
      FLAG: next = in ? D1 : D0;      // trailing 0 already consumed
      ERR:  next = in ? ERR : D0;     // stay in err while 1s continue
      default: next = D0;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= D0;          // behave as though previous input were 0
    else
      state <= next;
  end

  assign disc = (state == DISC);
  assign flag = (state == FLAG);
  assign err  = (state == ERR);

endmodule
