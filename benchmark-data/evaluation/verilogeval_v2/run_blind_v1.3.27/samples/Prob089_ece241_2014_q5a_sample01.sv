// program-SOLVED serial 2's complementer (LSB-first Moore, carry-derived); deterministic, no AI.
module TopModule(
    input clk,
    input areset,
    input x,
    output z
);
    localparam [1:0] P=2'd0, Q=2'd1, R=2'd2;  // P:carry=1(z=0) Q:out=1(z=1) R:out=0(z=0)
    reg [1:0] state;
    always @(posedge clk or posedge areset) begin
        if (areset) state <= P;
        else case (state)
            P: state <= x ? Q : P;
            Q: state <= x ? R : Q;
            R: state <= x ? R : Q;
            default: state <= P;
        endcase
    end
    assign z = (state == Q);
endmodule
