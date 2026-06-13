module TopModule (
  input  clk,
  input  reset,
  input  data,
  input  done_counting,
  input  ack,
  output shift_ena,
  output counting,
  output done
);

  localparam S=0, S1=1, S11=2, S110=3,
             B0=4, B1=5, B2=6, B3=7,
             COUNT=8, WAIT=9;
  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S:     next = data ? S1   : S;
      S1:    next = data ? S11  : S;
      S11:   next = data ? S11  : S110;
      S110:  next = data ? B0   : S;
      B0:    next = B1;
      B1:    next = B2;
      B2:    next = B3;
      B3:    next = COUNT;
      COUNT: next = done_counting ? WAIT : COUNT;
      WAIT:  next = ack ? S : WAIT;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S;
    else       state <= next;
  end

  assign shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
  assign counting  = (state == COUNT);
  assign done      = (state == WAIT);

endmodule
