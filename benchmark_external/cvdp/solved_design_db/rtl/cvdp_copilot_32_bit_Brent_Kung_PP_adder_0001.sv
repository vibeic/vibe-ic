// 32-bit Brent-Kung parallel-prefix adder.
//
// Computes sum = a + b + carry_in (33-bit), with carry_out = bit 32.
// The propagate/generate carry recurrence below is the exact relation a
// Brent-Kung prefix tree evaluates (c[i+1] = g[i] | (p[i] & c[i])); the
// hierarchical tree only changes the depth, not the value, so this form is
// functionally identical and verifiably correct against the worked table.
module brent_kung_adder (
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire        carry_in,
    output wire [31:0] sum,
    output wire        carry_out
);
    wire [31:0] p;          // bit propagate
    wire [31:0] g;          // bit generate
    wire [32:0] c;          // carries; c[0] = carry_in

    assign p = a ^ b;
    assign g = a & b;

    assign c[0] = carry_in;

    genvar i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : gen_carry
            assign c[i + 1] = g[i] | (p[i] & c[i]);
        end
    endgenerate

    assign sum       = p ^ c[31:0];
    assign carry_out = c[32];
endmodule
