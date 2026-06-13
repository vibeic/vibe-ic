module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);
    // A     : beginning/reset state (f=0,g=0)
    // FSET  : one-cycle f=1 pulse after reset de-asserts
    // S0    : looking for x=1 (start of the 1,0,1 pattern)
    // S1    : saw "1", expecting 0
    // S2    : saw "10", expecting 1 -> on x=1 the pattern completes
    // G1    : g=1, first cycle; check y
    // G2    : g=1, second cycle; check y
    // GHOLD : g=1 permanently (until reset)
    // GOFF  : g=0 permanently (until reset)
    localparam A=4'd0, FSET=4'd1, S0=4'd2, S1=4'd3, S2=4'd4,
               G1=4'd5, G2=4'd6, GHOLD=4'd7, GOFF=4'd8;

    reg [3:0] state, nstate;

    always @(*) begin
        case (state)
            A:     nstate = FSET;                 // resetn already de-asserted here
            FSET:  nstate = S0;
            S0:    nstate = x ? S1 : S0;          // wait for first 1
            S1:    nstate = x ? S1 : S2;          // "1"; on 0 -> "10"
            S2:    nstate = x ? G1 : S0;          // "10"; on 1 -> "101" detected
            G1:    nstate = y ? GHOLD : G2;       // 1st g cycle: y now?
            G2:    nstate = y ? GHOLD : GOFF;     // 2nd g cycle: last chance for y
            GHOLD: nstate = GHOLD;
            GOFF:  nstate = GOFF;
            default: nstate = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)            // synchronous active-low reset
            state <= A;
        else
            state <= nstate;
    end

    // Moore outputs (functions of state only).
    assign f = (state == FSET);
    assign g = (state == G1) || (state == G2) || (state == GHOLD);
endmodule
