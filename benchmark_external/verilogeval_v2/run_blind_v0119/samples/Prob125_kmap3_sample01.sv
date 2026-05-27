module TopModule(
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // Minimal SOP absorbing don't-cares (Quine-McCluskey):
    //   ON  = {0010,0011,1000,1010,1011,1100,1110,1111}
    //   DC  = {0100,1001,1101}
    //   minimal cover: a | (~b & c)
    //   - 'a' swallows DC 1001,1101; '~b&c' swallows DC nothing needed but is a full prime.
    assign out = a | (~b & c);
endmodule
