// Pure wiring: a->w, b->x, b->y, c->z.
module TopModule (
  input a,
  input b,
  input c,
  output w,
  output x,
  output y,
  output z
);

  assign w = a;
  assign x = b;
  assign y = b;
  assign z = c;

endmodule
