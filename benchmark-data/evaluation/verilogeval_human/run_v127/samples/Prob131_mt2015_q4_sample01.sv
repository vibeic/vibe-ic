module TopModule (
    input  x,
    input  y,
    output z
);

  wire a1, a2, b1, b2;
  ModuleA A1 (.x(x), .y(y), .z(a1));
  ModuleA A2 (.x(x), .y(y), .z(a2));
  ModuleB B1 (.x(x), .y(y), .z(b1));
  ModuleB B2 (.x(x), .y(y), .z(b2));

  wire or_out  = a1 | b1;
  wire and_out = a2 & b2;
  assign z = or_out ^ and_out;
endmodule

module ModuleA (input x, input y, output z);
  assign z = (x^y) & x;
endmodule

module ModuleB (input x, input y, output z);
  assign z = (~x & ~y) | (x & y);
endmodule
