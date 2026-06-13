module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    // A    : begin state (reset). f=0, g=0.
    // SF   : pulse f=1 for exactly one cycle.
    // X0   : watch x for first 1.
    // X1   : saw "1".
    // X10  : saw "10"; x=1 here completes "101".
    // G    : g=1, first y-watch cycle (the cycle after the match).
    // G2   : g=1, second y-watch cycle.
    // GON  : g=1 permanently (y was 1 within two cycles).
    // GOFF : g=0 permanently (y stayed 0 for two cycles).
    localparam A=4'd0, SF=4'd1, X0=4'd2, X1=4'd3, X10=4'd4,
               G=4'd5, G2=4'd6, GON=4'd7, GOFF=4'd8;

    reg [3:0] state, nstate;

    always @(*) begin
        case (state)
            A:    nstate = SF;
            SF:   nstate = X0;
            X0:   nstate = x ? X1  : X0;
            X1:   nstate = x ? X1  : X10;
            X10:  nstate = x ? G   : X0;
            G:    nstate = y ? GON : G2;
            G2:   nstate = y ? GON : GOFF;
            GON:  nstate = GON;
            GOFF: nstate = GOFF;
            default: nstate = A;
        endcase
    end

    // Synchronous active-low reset.
    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= nstate;
    end

    assign f = (state == SF);
    assign g = (state == G) || (state == G2) || (state == GON);

endmodule
