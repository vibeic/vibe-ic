module TopModule (
  input a,
  input b,
  input c,
  output out
);
    // K-map: out=0 only at a=b=c=0; minimal SOP -> a | b | c
    assign out = a | b | c;
endmodule
