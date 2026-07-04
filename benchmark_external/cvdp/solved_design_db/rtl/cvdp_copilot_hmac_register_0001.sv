module hmac_reg_interface #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  write_en,
    input  logic                  read_en,
    input  logic [ADDR_WIDTH-1:0] addr,
    input  logic [DATA_WIDTH-1:0] wdata,
    input  logic                  i_wait_en,
    output logic [DATA_WIDTH-1:0] rdata,
    output logic                  hmac_valid,
    output logic                  hmac_key_error
);

    // Number of registers
    localparam NUM_REGS = 1 << ADDR_WIDTH;
    localparam [DATA_WIDTH-1:0] XOR = {(DATA_WIDTH/2){2'b01}};

    // FSM States (encoding matches the reference model integer values:
    // IDLE=0, ANALYZE/CHECK=1, XOR_DATA/PROCESS=2, WRITE=3, LOST=4,
    // CHECK_KEY=5, TRIG_WAIT=6)
    typedef enum logic [2:0] {
        IDLE     = 3'b000,
        ANALYZE  = 3'b001,
        XOR_DATA = 3'b010,
        WRITE    = 3'b011,
        LOST     = 3'b100,
        CHECK_KEY= 3'b101,
        TRIG_WAIT= 3'b110
    } state_t;

    state_t current_state, next_state;

    // Registers
    logic [DATA_WIDTH-1:0] registers [NUM_REGS-1:0];

    // HMAC data
    logic [DATA_WIDTH-1:0] hmac_key;
    logic [DATA_WIDTH-1:0] hmac_data;

    logic [DATA_WIDTH-1:0] xor_data;

    // ----------------------------------------------------------------
    // FSM Logic
    // ----------------------------------------------------------------
    always_comb begin : next_state_logic
        next_state = current_state;
        case (current_state)
            IDLE: begin
                if (write_en)
                    next_state = ANALYZE;
            end
            ANALYZE: begin
                if (wdata[DATA_WIDTH-1])
                    next_state = XOR_DATA;
                else
                    next_state = WRITE;
            end
            XOR_DATA: begin
                next_state = WRITE;
            end
            WRITE: begin
                if (write_en)
                    next_state = IDLE;
                else
                    next_state = LOST;
            end
            LOST: begin
                if (read_en)
                    next_state = CHECK_KEY;
                else
                    next_state = LOST;
            end
            CHECK_KEY: begin
                if (hmac_key_error)
                    next_state = WRITE;
                else
                    next_state = TRIG_WAIT;
            end
            TRIG_WAIT: begin
                if (!i_wait_en) begin
                    if ((hmac_data != '0) && (hmac_key != '0))
                        next_state = IDLE;
                    else
                        next_state = WRITE;
                end else begin
                    next_state = TRIG_WAIT;
                end
            end
            default: next_state = IDLE;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin : state_reg
        if (!rst_n)
            current_state <= IDLE;
        else
            current_state <= next_state;
    end

    // ----------------------------------------------------------------
    // XOR logic and Key analysis (combinational)
    // ----------------------------------------------------------------
    always_comb begin : xor_logic
        if (current_state == XOR_DATA)
            xor_data = wdata ^ XOR;
        else
            xor_data = wdata;
    end

    // Key valid when both the top two and bottom two bits are zero.
    always_comb begin : key_check
        if ((hmac_key[DATA_WIDTH-1:DATA_WIDTH-2] == 2'b00) && (hmac_key[1:0] == 2'b00))
            hmac_key_error = 1'b0;
        else
            hmac_key_error = 1'b1;
    end

    // ----------------------------------------------------------------
    // Write Logic Operation (sequential)
    // ----------------------------------------------------------------
    integer ri;
    always_ff @(posedge clk or negedge rst_n) begin : write_logic
        if (!rst_n) begin
            hmac_key   <= '0;
            hmac_data  <= '0;
            hmac_valid <= 1'b0;
            for (ri = 0; ri < NUM_REGS; ri = ri + 1)
                registers[ri] <= '0;
        end else begin
            if (current_state == WRITE) begin
                if (addr == 0) begin
                    hmac_key <= xor_data;
                end else if (addr == 1) begin
                    hmac_data  <= xor_data;
                    hmac_valid <= 1'b1;
                end else begin
                    registers[addr] <= xor_data;
                end
            end else begin
                hmac_valid <= 1'b0;
            end
        end
    end

    // ----------------------------------------------------------------
    // Read Logic Operation (sequential, one-cycle latency, only when
    // not writing)
    // ----------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin : read_logic
        if (!rst_n) begin
            rdata <= '0;
        end else if (current_state != WRITE) begin
            if (read_en) begin
                if (addr == 0)
                    rdata <= hmac_key;
                else if (addr == 1)
                    rdata <= hmac_data;
                else
                    rdata <= registers[addr];
            end
        end
    end

endmodule
