module TopModule (
  input [3:0] a,
  input [3:0] b,
  input [3:0] c,
  input [3:0] d,
  input [3:0] e,
  output reg [3:0] q
);

  // From the waveform: c is the selector.
  // c=0 -> b, c=1 -> e, c=2 -> a, c=3 -> d, otherwise -> 4'hf
  always @(*) begin
    case (c)
      4'd0: q = b;
      4'd1: q = e;
      4'd2: q = a;
      4'd3: q = d;
      default: q = 4'hf;
    endcase
  end

endmodule
