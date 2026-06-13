module TopModule(
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);
    localparam A     = 4'd0;  // reset / start state
    localparam SF    = 4'd1;  // f=1 for one cycle
    localparam X0    = 4'd2;  // x-monitor: nothing
    localparam X1    = 4'd3;  // saw "1"
    localparam X10   = 4'd4;  // saw "10"
    localparam GW1   = 4'd5;  // g=1, 1st y-check cycle
    localparam GW2   = 4'd6;  // g=1, 2nd y-check cycle
    localparam GPERM = 4'd7;  // g=1 permanently
    localparam GOFF  = 4'd8;  // g=0 permanently
    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = SF;                      // reset released -> f=1 next cycle
            SF:    next = X0;                      // after the one f=1 cycle
            X0:    next = x ? X1  : X0;
            X1:    next = x ? X1  : X10;           // "1" then "1" stays; "1" then "0" -> "10"
            X10:   next = x ? GW1 : X0;            // "10" then "1" => 101 detected
            GW1:   next = y ? GPERM : GW2;
            GW2:   next = y ? GPERM : GOFF;
            GPERM: next = GPERM;
            GOFF:  next = GOFF;
            default: next = X0;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)              // synchronous active-low reset
            state <= A;           // stay in A (f=0) while reset asserted
        else
            state <= next;        // A -> SF (f=1 for one cycle) -> begin x-monitor
    end

    assign f = (state == SF);
    assign g = (state == GW1) || (state == GW2) || (state == GPERM);
endmodule
