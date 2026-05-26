module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A    = 4'd0;
    localparam B    = 4'd1;
    localparam S0   = 4'd2;
    localparam S1   = 4'd3;
    localparam S2   = 4'd4;
    localparam G1   = 4'd5;
    localparam G2   = 4'd6;
    localparam GON  = 4'd7;
    localparam GOFF = 4'd8;

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = B;
            B:    next = S0;
            S0:   next = x ? S1 : S0;
            S1:   next = x ? S1 : S2;
            S2:   next = x ? G1 : S0;
            G1:   next = y ? GON : G2;
            G2:   next = y ? GON : GOFF;
            GON:  next = GON;
            GOFF: next = GOFF;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= next;
    end

    assign f = (state == B);
    assign g = (state == G1) || (state == G2) || (state == GON);

endmodule
