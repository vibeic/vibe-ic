module TopModule (
  input  clk,
  input  reset,
  input  in,
  output disc,
  output flag,
  output err
);

  localparam S0=0, S1=1, S2=2, S3=3, S4=4, S5=5, S6=6,
             DISC=7, FLAG=8, ERR=9;
  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0:   next = in ? S1 : S0;
      S1:   next = in ? S2 : S0;
      S2:   next = in ? S3 : S0;
      S3:   next = in ? S4 : S0;
      S4:   next = in ? S5 : S0;
      S5:   next = in ? S6 : DISC;   // 5 ones then 0 -> discard
      S6:   next = in ? ERR : FLAG;  // 6 ones then 0 -> flag; another 1 -> error
      DISC: next = in ? S1 : S0;
      FLAG: next = in ? S1 : S0;
      ERR:  next = in ? ERR : S0;    // stay in error until a 0 arrives
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S0;
    else       state <= next;
  end

  assign disc = (state == DISC);
  assign flag = (state == FLAG);
  assign err  = (state == ERR);

endmodule
