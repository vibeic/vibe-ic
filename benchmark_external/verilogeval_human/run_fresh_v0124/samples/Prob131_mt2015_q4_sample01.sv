module ModA (input x, input y, output z);
  assign z = (x ^ y) & x;
endmodule

module ModB (input x, input y, output z);
  assign z = ~(x ^ y);
endmodule

module TopModule (
  input x,
  input y,
  output z
);

  wire a1, a2, b1, b2;
  wire or_out, and_out;

  ModA A1 (.x(x), .y(y), .z(a1));
  ModA A2 (.x(x), .y(y), .z(a2));
  ModB B1 (.x(x), .y(y), .z(b1));
  ModB B2 (.x(x), .y(y), .z(b2));

  assign or_out  = a1 | b1;
  assign and_out = a2 & b2;
  assign z = or_out ^ and_out;

endmodule
