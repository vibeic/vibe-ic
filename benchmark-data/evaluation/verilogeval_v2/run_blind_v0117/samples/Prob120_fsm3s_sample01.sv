module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);
    localparam A = 2'b00, B = 2'b01, C = 2'b10, D = 2'b11;
    reg [1:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;          // synchronous active-high reset to A
        else begin
            case (state)
                A:       state <= in ? B : A;
                B:       state <= in ? B : C;
                C:       state <= in ? D : A;
                D:       state <= in ? B : C;
                default: state <= A;
            endcase
        end
    end

    // Moore output: function of state only (out=1 only in state D)
    assign out = (state == D);
endmodule
