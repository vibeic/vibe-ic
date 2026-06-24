// RAM — dual-port (independent read + write), depth 8, 6-bit width.
// Registered read: when read_en=1, read_data <= mem[read_addr]; else read_data<=0.
// Write: when write_en=1, mem[write_addr] <= write_data.
module RAM (
    input  wire        clk,
    input  wire        rst_n,        // active-low reset
    input  wire        write_en,
    input  wire [2:0]  write_addr,
    input  wire [5:0]  write_data,
    input  wire        read_en,
    input  wire [2:0]  read_addr,
    output reg  [5:0]  read_data
);

    parameter WIDTH = 6;
    parameter DEPTH = 8;

    // DEPTH locations, each WIDTH bits, all initialised to 0 on reset.
    reg [WIDTH-1:0] RAM [0:DEPTH-1];

    integer i;

    // write port
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < DEPTH; i = i + 1)
                RAM[i] <= {WIDTH{1'b0}};
        end else if (write_en) begin
            RAM[write_addr] <= write_data;
        end
    end

    // read port (registered)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_data <= {WIDTH{1'b0}};
        end else if (read_en) begin
            read_data <= RAM[read_addr];
        end else begin
            read_data <= {WIDTH{1'b0}};
        end
    end

endmodule
