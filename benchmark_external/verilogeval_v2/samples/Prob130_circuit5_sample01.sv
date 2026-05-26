module TopModule (
  input  [3:0] a,
  input  [3:0] b,
  input  [3:0] c,
  input  [3:0] d,
  input  [3:0] e,
  output [3:0] q
);
  reg [3:0] r;
  always @(*) begin
    case (c)
      4'h0: r = b;
      4'h1: r = e;
      4'h2: r = a;
      4'h3: r = d;
      default: r = 4'hf;
    endcase
  end
  assign q = r;
endmodule
