module TopModule (
    input  clk,
    input  reset,
    input  in,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state;

    always @(posedge clk) begin
        if (reset)
            state <= B;
        else begin
            case (state)
                A: state <= in ? A : B;
                B: state <= in ? B : A;
                default: state <= B;
            endcase
        end
    end

    // Moore output: depends on state only
    assign out = (state == B);
endmodule
