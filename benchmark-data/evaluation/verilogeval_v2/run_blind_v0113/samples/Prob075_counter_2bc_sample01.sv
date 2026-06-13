module TopModule (
    input        clk,
    input        areset,
    input        train_valid,
    input        train_taken,
    output [1:0] state
);
    reg [1:0] st;
    always @(posedge clk or posedge areset) begin
        if (areset)
            st <= 2'b01;
        else if (train_valid) begin
            if (train_taken) begin
                if (st != 2'b11) st <= st + 2'b01;
            end else begin
                if (st != 2'b00) st <= st - 2'b01;
            end
        end
    end
    assign state = st;
endmodule
