// 25 pairwise one-bit equality comparisons of {a,b,c,d,e}.
// out[24]=~a^a, out[23]=~a^b, ... out[0]=~e^e.
// out[24 - (i*5+j)] = ~vec[i] ^ vec[j], i,j in 0..4 (a..e).
// ~x ^ y is XNOR (1 when bits equal). Build by XNOR of two assembled
// 25-bit operand vectors:
//   left  = each of a..e replicated 5 times (a a a a a b b b b b ...)
//   right = a..e repeated 5 times          (a b c d e a b c d e ...)
// Then bit position 24 is the first pair, descending to bit 0.
module TopModule (
  input a,
  input b,
  input c,
  input d,
  input e,
  output [24:0] out
);

  wire [24:0] left;
  wire [24:0] right;

  // MSB-first: index 24 = first pair (a,a)
  assign left  = { {5{a}}, {5{b}}, {5{c}}, {5{d}}, {5{e}} };
  assign right = { {5{ {a,b,c,d,e} }} };

  // XNOR: 1 when the two compared bits are equal
  assign out = ~(left ^ right);

endmodule
