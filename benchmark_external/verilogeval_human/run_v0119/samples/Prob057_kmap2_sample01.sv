module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);
    // Minimal SOP cover of the 4-var K-map (no don't-cares):
    // out = ~a&b&c | ~a&~d | a&c&d | ~b&~c
    assign out = (~a & b & c) | (~a & ~d) | (a & c & d) | (~b & ~c);
endmodule
