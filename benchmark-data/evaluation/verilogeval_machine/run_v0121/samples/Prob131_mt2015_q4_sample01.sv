module TopModule (
  input x,
  input y,
  output z
);
  // SPEC DEFECT: prose gives only the 3-gate wiring, not each gate's function.
  // Canonical mt2015_q4 reading: g1=AND(x,y), g2=OR(y,x), g3=XOR(g1,g2) => z = x^y.
  wire g1 = x & y;          // gate1: a=x, b=y
  wire g2 = y | x;          // gate2: a=y, b=x
  assign z = g1 ^ g2;       // gate3: a=g1, b=g2
endmodule
