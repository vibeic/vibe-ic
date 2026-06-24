module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    // Moore FSM. Synchronous active-low reset (resetn=0) holds state A.
    //  A   : reset/begin. When resetn deasserted, next edge -> FPULSE.
    //  FPULSE: f=1 for one clock cycle, then begin watching x.
    //  X0/X1/X2: detect the sequence x=1,0,1 (overlapping). On the third bit
    //            completing 1,0,1, set g=1 the following cycle (state GY0).
    //  GY0 : g=1, first y-check cycle. y=1 -> GON; else GY1.
    //  GY1 : g=1, second y-check cycle. y=1 -> GON; else GOFF.
    //  GON : g=1 permanently. GOFF: g=0 permanently. (until reset)

    localparam A      = 4'd0;
    localparam FPULSE = 4'd1;
    localparam X0     = 4'd2;   // seen nothing useful
    localparam X1     = 4'd3;   // seen '1'
    localparam X2     = 4'd4;   // seen '1,0'
    localparam GY0    = 4'd5;   // g=1, y-watch cycle 1
    localparam GY1    = 4'd6;   // g=1, y-watch cycle 2
    localparam GON    = 4'd7;   // g=1 forever
    localparam GOFF   = 4'd8;   // g=0 forever

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:      next = FPULSE;
            FPULSE: next = X0;
            // overlapping detector for 1,0,1
            X0:     next = x ? X1 : X0;
            X1:     next = x ? X1 : X2;          // saw 1; on 0 -> have 1,0
            X2:     next = x ? GY0 : X0;         // saw 1,0; on 1 -> 1,0,1 done
            GY0:    next = y ? GON : GY1;
            GY1:    next = y ? GON : GOFF;
            GON:    next = GON;
            GOFF:   next = GOFF;
            default: next = X0;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn) state <= A;
        else         state <= next;
    end

    assign f = (state == FPULSE);
    assign g = (state == GY0) || (state == GY1) || (state == GON);

endmodule
