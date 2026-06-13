module TopModule (
  input a,
  input b,
  input c,
  input d,
  input e,
  output [24:0] out
);
    // Equality (XNOR) of each first operand against each of {a,b,c,d,e}.
    // out[24:20] compares a vs {a,b,c,d,e}, [19:15] b vs ..., etc.
    assign out = ~( { {5{a}}, {5{b}}, {5{c}}, {5{d}}, {5{e}} }
                  ^ { {5{ {a,b,c,d,e} }} } );
endmodule
