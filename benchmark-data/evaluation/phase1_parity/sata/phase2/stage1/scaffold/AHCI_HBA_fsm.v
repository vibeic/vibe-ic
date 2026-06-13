// Auto-generated FSM skeleton.
// 32 states — transitions are TODO; only state enum + reset path are generated.
// Top module: AHCI_HBA

`timescale 1ns/1ps

module AHCI_HBA_fsm (
    input  clk,
    input  rst_n,
    output reg [4:0] state
);

    // State encoding
    localparam [4:0] S_ATTACHED = 5'd0;
    localparam [4:0] S_STATE = 5'd1;
    localparam [4:0] S_ANOTHER = 5'd2;
    localparam [4:0] S_RESPONSE = 5'd3;
    localparam [4:0] S_FRAME = 5'd4;
    localparam [4:0] S_PXCI = 5'd5;
    localparam [4:0] S_DETERMINE = 5'd6;
    localparam [4:0] S_COMMANDS = 5'd7;
    localparam [4:0] S_TRANSMIT = 5'd8;
    localparam [4:0] S_REFER = 5'd9;
    localparam [4:0] S_SECTION = 5'd10;
    localparam [4:0] S_VARIABLES = 5'd11;
    localparam [4:0] S_THEIR = 5'd12;
    localparam [4:0] S_REGISTER = 5'd13;
    localparam [4:0] S_TRANSMITTED = 5'd14;
    localparam [4:0] S_MACHINE = 5'd15;
    localparam [4:0] S_ENSURE = 5'd16;
    localparam [4:0] S_INITIALIZATION = 5'd17;
    localparam [4:0] S_COMPLETE = 5'd18;
    localparam [4:0] S_CONDITIONS = 5'd19;
    localparam [4:0] S_COMRESET = 5'd20;
    localparam [4:0] S_POWER = 5'd21;
    localparam [4:0] S_WRITTEN = 5'd22;
    localparam [4:0] S_FIELD = 5'd23;
    localparam [4:0] S_IDLE = 5'd24;
    localparam [4:0] S_CFIS = 5'd25;
    localparam [4:0] S_XMIT = 5'd26;
    localparam [4:0] S_ENTRY = 5'd27;
    localparam [4:0] S_AGAIN = 5'd28;
    localparam [4:0] S_SEND = 5'd29;
    localparam [4:0] S_CLEAR = 5'd30;
    localparam [4:0] S_INDICATE = 5'd31;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_ATTACHED;
        end else begin
            // TODO — transition logic per L6.fsm_transitions
        end
    end

endmodule
