// Prob131_mt2015_q4 — three 2-input gates wired per the prose.
// SPEC-DEFECT: prose omits the gate TYPES. Using the canonical mt2015_q4
// definitions (gate1=AND, gate2=OR, gate3=XOR):
//   g1 = x & y;  g2 = y | x;  z = g1 ^ g2  ==  x ^ y.
module TopModule (
  input x,
  input y,
  output z
);

  wire g1 = x & y;   // first gate: a=x, b=y
  wire g2 = y | x;   // second gate: a=y, b=x (commutative)
  assign z = g1 ^ g2; // third gate: a=g1, b=g2

endmodule
