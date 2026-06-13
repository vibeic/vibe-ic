// 3-input Karnaugh map. out=0 only at a=b=c=0; out=1 otherwise.
// Minimum SOP: out = a | b | c.
module TopModule (
  input a,
  input b,
  input c,
  output out
);

  assign out = a | b | c;

endmodule
