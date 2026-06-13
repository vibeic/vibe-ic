module TopModule (
    input  clk,
    input  resetn,   // synchronous active-low reset
    input  x,
    input  y,
    output f,
    output g
);
    localparam A      = 4'd0;  // reset/begin state
    localparam SF     = 4'd1;  // f = 1 for one cycle
    localparam X0     = 4'd2;  // monitoring x: no useful prefix
    localparam X1     = 4'd3;  // x: seen "1"
    localparam X2     = 4'd4;  // x: seen "10"
    localparam G1     = 4'd5;  // g = 1, first y-monitor cycle
    localparam G2     = 4'd6;  // g = 1, second y-monitor cycle
    localparam GPERM  = 4'd7;  // g = 1 permanently
    localparam GOFF   = 4'd8;  // g = 0 permanently

    reg [3:0] state;

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else begin
            case (state)
                A:     state <= SF;
                SF:    state <= X0;
                X0:    state <= x ? X1 : X0;
                X1:    state <= x ? X1 : X2;
                X2:    state <= x ? G1 : X0;     // 101 detected on x==1
                G1:    state <= y ? GPERM : G2;
                G2:    state <= y ? GPERM : GOFF;
                GPERM: state <= GPERM;
                GOFF:  state <= GOFF;
                default: state <= A;
            endcase
        end
    end

    // Moore outputs
    assign f = (state == SF);
    assign g = (state == G1) || (state == G2) || (state == GPERM);
endmodule
