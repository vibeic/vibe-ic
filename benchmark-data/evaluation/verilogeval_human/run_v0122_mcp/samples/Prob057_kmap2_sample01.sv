// 4-input Karnaugh map (rows cd, cols ab). out=1 at minterms:
//   0000 0001 0010 0100 0110 0111 1000 1001 1011 1111 (a,b,c,d).
// Canonical sum-of-products; synthesis minimizes the literals.
module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);

  assign out =
      (~a & ~b & ~c & ~d) |
      (~a & ~b & ~c &  d) |
      (~a & ~b &  c & ~d) |
      (~a &  b & ~c & ~d) |
      (~a &  b &  c & ~d) |
      (~a &  b &  c &  d) |
      ( a & ~b & ~c & ~d) |
      ( a & ~b & ~c &  d) |
      ( a & ~b &  c &  d) |
      ( a &  b &  c &  d);

endmodule
