module sdram_controller (clk,reset,addr,data_in,data_out,read,write,sdram_clk,sdram_cke,sdram_cs,sdram_ras,sdram_cas,sdram_we,sdram_addr,sdram_ba,sdram_dq,dq_out);

    input         clk;
    input         reset;          // asynchronous active-high reset
    input  [23:0] addr;           // 24-bit address for SDRAM access
    input  [15:0] data_in;        // 16-bit write data
    input         read;
    input         write;
    input  [15:0] sdram_dq;       // 16-bit data bus from SDRAM

    output reg [15:0] data_out;   // 16-bit read data
    output            sdram_clk;
    output reg        sdram_cke;
    output reg        sdram_cs;
    output reg        sdram_ras;
    output reg        sdram_cas;
    output reg        sdram_we;
    output reg [12:0] sdram_addr;
    output reg [1:0]  sdram_ba;
    output reg [15:0] dq_out;     // 16-bit write data bus to SDRAM

    // FSM states
    localparam INIT     = 3'd0;
    localparam IDLE     = 3'd1;
    localparam ACTIVATE = 3'd2;
    localparam READ     = 3'd3;
    localparam WRITE    = 3'd4;
    localparam REFRESH  = 3'd5;

    localparam INIT_CYCLES    = 10;
    localparam REFRESH_PERIOD = 1024;

    reg [2:0]  state;
    reg [3:0]  init_cnt;       // counts up to INIT_CYCLES
    reg [9:0]  refresh_cnt;    // counts up to REFRESH_PERIOD
    reg        pend_read;      // latched request type
    reg        pend_write;

    // SDRAM clock is simply the system clock forwarded to the device.
    assign sdram_clk = clk;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state       <= INIT;
            init_cnt    <= 4'd0;
            refresh_cnt <= 10'd0;
            pend_read   <= 1'b0;
            pend_write  <= 1'b0;
            data_out    <= 16'd0;
            dq_out      <= 16'd0;
            sdram_addr  <= 13'd0;
            sdram_ba    <= 2'd0;
            // idle command (CKE high, chip deselected)
            sdram_cke   <= 1'b1;
            sdram_cs    <= 1'b0;
            sdram_ras   <= 1'b0;
            sdram_cas   <= 1'b0;
            sdram_we    <= 1'b0;
        end else begin
            // default: deassert command strobes each cycle unless a state drives them
            sdram_cke <= 1'b1;
            sdram_cs  <= 1'b0;
            sdram_ras <= 1'b0;
            sdram_cas <= 1'b0;
            sdram_we  <= 1'b0;

            case (state)
                // -------- Initialization: 10 clock cycles --------
                INIT: begin
                    if (init_cnt == INIT_CYCLES-1) begin
                        init_cnt <= 4'd0;
                        state    <= IDLE;
                    end else begin
                        init_cnt <= init_cnt + 4'd1;
                    end
                end

                // -------- Idle: wait for read/write or trigger refresh --------
                IDLE: begin
                    if (read || write) begin
                        // capture request and latch the row/bank/column address
                        pend_read   <= read;
                        pend_write  <= write;
                        sdram_addr  <= addr[12:0];
                        sdram_ba    <= addr[23:22];
                        refresh_cnt <= 10'd0;
                        // Activate command: CS=1, RAS=1, CAS=1
                        sdram_cs    <= 1'b1;
                        sdram_ras   <= 1'b1;
                        sdram_cas   <= 1'b1;
                        state       <= ACTIVATE;
                    end else if (refresh_cnt == REFRESH_PERIOD-1) begin
                        refresh_cnt <= 10'd0;
                        // Auto Refresh command: CS=1, RAS=1, CAS=1, WE=0
                        sdram_cs    <= 1'b1;
                        sdram_ras   <= 1'b1;
                        sdram_cas   <= 1'b1;
                        sdram_we    <= 1'b0;
                        state       <= REFRESH;
                    end else begin
                        refresh_cnt <= refresh_cnt + 10'd1;
                    end
                end

                // -------- Activate: next cycle go to READ or WRITE --------
                ACTIVATE: begin
                    if (pend_read)
                        state <= READ;
                    else if (pend_write)
                        state <= WRITE;
                    else
                        state <= IDLE;
                end

                // -------- Read: CS=1, CKE=1, RAS=0, CAS=1, WE=0 --------
                READ: begin
                    sdram_cs   <= 1'b1;
                    sdram_cke  <= 1'b1;
                    sdram_ras  <= 1'b0;
                    sdram_cas  <= 1'b1;
                    sdram_we   <= 1'b0;
                    data_out   <= sdram_dq;     // capture read data
                    pend_read  <= 1'b0;
                    state      <= IDLE;
                end

                // -------- Write: CS=1, CKE=1, RAS=0, CAS=1, WE=1 --------
                WRITE: begin
                    sdram_cs   <= 1'b1;
                    sdram_cke  <= 1'b1;
                    sdram_ras  <= 1'b0;
                    sdram_cas  <= 1'b1;
                    sdram_we   <= 1'b1;
                    dq_out     <= data_in;      // drive write data
                    pend_write <= 1'b0;
                    state      <= IDLE;
                end

                // -------- Refresh: hold the refresh command then return --------
                REFRESH: begin
                    sdram_cs   <= 1'b1;
                    sdram_ras  <= 1'b1;
                    sdram_cas  <= 1'b1;
                    sdram_we   <= 1'b0;
                    state      <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
