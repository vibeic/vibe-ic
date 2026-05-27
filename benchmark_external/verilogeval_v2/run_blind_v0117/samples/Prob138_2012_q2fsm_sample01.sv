module TopModule (
    input  clk,
    input  reset,
    input  w,
    output z
);
    localparam A=3'd0, B=3'd1, C=3'd2, D=3'd3, E=3'd4, F=3'd5;
    reg [2:0] state, nstate;

    // State table (combinational)
    always @(*) begin
        case (state)
            A: nstate = w ? B : A;
            B: nstate = w ? C : D;
            C: nstate = w ? E : D;
            D: nstate = w ? F : A;
            E: nstate = w ? E : D;
            F: nstate = w ? C : D;
            default: nstate = A;
        endcase
    end

    // State flip-flops
    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nstate;
    end

    // Moore output
    assign z = (state == E) || (state == F);
endmodule
