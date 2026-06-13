module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A    = 4'd0;  // reset state
    localparam S_F  = 4'd1;  // f=1 for one cycle
    localparam X0   = 4'd2;  // looking for first 1
    localparam X1   = 4'd3;  // saw 1, need 0
    localparam X2   = 4'd4;  // saw 10, need 1
    localparam G1   = 4'd5;  // g=1, first y-check cycle
    localparam G2   = 4'd6;  // g=1, second y-check cycle
    localparam GON  = 4'd7;  // g=1 permanently
    localparam GOFF = 4'd8;  // g=0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = S_F;
            S_F:  next = X0;
            X0:   next = x ? X1 : X0;
            X1:   next = x ? X1 : X2;
            X2:   next = x ? G1 : X0;
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

    assign f = (state == S_F);
    assign g = (state == G1) || (state == G2) || (state == GON);

endmodule
