module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // Serial 2's complementer, Moore.
  // State S0: have not yet seen a 1 (pass input through, output = x).
  // State S1: have seen the first 1 (complement subsequent bits, output = ~x).
  reg state;
  localparam S0 = 1'b0, S1 = 1'b1;
  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= S0;
    else begin
      case (state)
        S0: state <= x ? S1 : S0;
        S1: state <= S1;
      endcase
    end
  end
  // Moore-style output depends on state and current input mapping of 2's comp:
  // While in S0 (before first 1): z = x (copy). On the bit that is the first 1
  // and after: z = complement. Equivalent: z = (state==S1) ? ~x : x.
  assign z = (state == S1) ? ~x : x;
endmodule
