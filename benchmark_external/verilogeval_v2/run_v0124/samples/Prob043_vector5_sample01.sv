module TopModule (
    input        a,
    input        b,
    input        c,
    input        d,
    input        e,
    output [24:0] out
);
    // out[24..20] : a vs (a,b,c,d,e)
    // out[19..15] : b vs (a,b,c,d,e)
    // out[14..10] : c vs (a,b,c,d,e)
    // out[ 9.. 5] : d vs (a,b,c,d,e)
    // out[ 4.. 0] : e vs (a,b,c,d,e)
    // out bit = 1 when the two compared bits are equal (XNOR)
    assign out = { ~(a^a), ~(a^b), ~(a^c), ~(a^d), ~(a^e),
                   ~(b^a), ~(b^b), ~(b^c), ~(b^d), ~(b^e),
                   ~(c^a), ~(c^b), ~(c^c), ~(c^d), ~(c^e),
                   ~(d^a), ~(d^b), ~(d^c), ~(d^d), ~(d^e),
                   ~(e^a), ~(e^b), ~(e^c), ~(e^d), ~(e^e) };
endmodule
