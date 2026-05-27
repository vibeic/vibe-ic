module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // ON  = {2,7,15}, dont-care = {3,8,11,12}
    // minimum SOP: c&d | ~a&~b&c   (c&d absorbs dc 3,11)
    assign out_sop = (c & d) | (~a & ~b & c);
    // complement minimal SOP: b&~d | ~c | a&~b
    // => minimum POS: (~b|d) & c & (~a|b)
    assign out_pos = (~b | d) & c & (~a | b);
endmodule
