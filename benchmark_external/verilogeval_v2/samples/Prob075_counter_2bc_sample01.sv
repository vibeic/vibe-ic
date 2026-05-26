module TopModule (
    input        clk,
    input        areset,
    input        train_valid,
    input        train_taken,
    output [1:0] state
);

    reg [1:0] s;

    always @(posedge clk or posedge areset) begin
        if (areset)
            s <= 2'b01;
        else if (train_valid) begin
            if (train_taken) begin
                if (s != 2'b11)
                    s <= s + 2'b01;
            end else begin
                if (s != 2'b00)
                    s <= s - 2'b01;
            end
        end
    end

    assign state = s;

endmodule
