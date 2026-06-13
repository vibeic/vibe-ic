module TopModule (
    input        a,
    input        b,
    input        c,
    input        d,
    output       out
);
    // Minimal SOP from the 4-variable K-map (verified exhaustively):
    //   out = ~a&~d | ~b&~c | ~a&b&c | a&c&d
    assign out = (~a & ~d) | (~b & ~c) | (~a & b & c) | (a & c & d);
endmodule
