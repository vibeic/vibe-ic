module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);
  // {a,b,c,d}: a is MSB. ON = {2,7,15}, DC = {3,8,11,12}.
  // Minimized using don't-cares:
  //   c&d  covers 3,7,11,15 (7,15 are ON; 3,11 are DC) -> ok
  //   b&c&~d covers 6? no. minterm 2 = 0010 -> ~a&~b&c&~d
  //   Use SOP = c&d + (~a&~b&c&~d). With DC=8(1000),12(1100) free.
  assign out_sop = (c & d) | (~a & ~b & c & ~d);
  // POS: complement zeros. Equivalent function (must match on specified cells).
  assign out_pos = c & (d | (~a & ~b));
endmodule
