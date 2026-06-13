module RAM #(
    parameter WIDTH = 6,
    parameter DEPTH = 8
)(
    input                          clk,
    input                          rst_n,
    input                          write_en,
    input  [WIDTH-1:0]             write_addr,
    input  [DEPTH-1:0]             write_data,
    input                          read_en,
    input  [WIDTH-1:0]             read_addr,
    output reg [DEPTH-1:0]         read_data
);

    integer i;
    reg [DEPTH-1:0] mem [2**WIDTH-1:0];

    // Write operation
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 2**WIDTH; i = i + 1)
                mem[i] <= {DEPTH{1'b0}};
        end else if (write_en) begin
            mem[write_addr] <= write_data;
        end
    end

    // Read operation
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_data <= {DEPTH{1'b0}};
        end else if (read_en) begin
            read_data <= mem[read_addr];
        end else begin
            read_data <= {DEPTH{1'b0}};
        end
    end

endmodule
