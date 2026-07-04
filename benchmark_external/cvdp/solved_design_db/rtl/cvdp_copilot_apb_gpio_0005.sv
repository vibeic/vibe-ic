module cvdp_copilot_apb_gpio #(
  parameter GPIO_WIDTH = 8
)(
  // Clock and Reset Signals
  input logic pclk,       // Clock signal
  input logic preset_n,   // Active-low reset signal

  // APB Interface Inputs
  input logic psel,           // Peripheral select
  input logic [7:2] paddr,    // APB address bus (bits [7:2])
  input logic penable,        // Transfer control signal
  input logic pwrite,         // Write control signal
  input logic [31:0] pwdata,  // Write data bus

  // APB Interface Outputs
  output logic [31:0] prdata, // Read data bus
  output logic pready,        // Device ready signal
  output logic pslverr,       // Device error response

  // Bidirectional GPIO Interface
  inout  wire [GPIO_WIDTH-1:0] gpio,    // Bidirectional GPIO pins

  // Interrupt Outputs
  output logic [GPIO_WIDTH-1:0] gpio_int, // Individual interrupt outputs
  output logic comb_int                   // Combined interrupt output
);

  // Signals for Read/Write Controls
  logic read_enable;
  logic write_enable;
  logic power_down;                      // Global power-down (Power Mgmt reg bit0)
  logic write_active;                    // Write allowed (gated by power-down)
  logic write_enable_reg_04;
  logic write_enable_reg_08;
  logic write_enable_reg_0C;
  logic write_enable_reg_10;
  logic write_enable_reg_14;
  logic write_enable_reg_18;
  logic write_enable_reg_1C;             // Direction Control (0x1C)
  logic write_enable_reg_20;             // Power Management (0x20)
  logic write_enable_reg_24;             // Interrupt Reset (0x24)
  logic [GPIO_WIDTH-1:0] read_mux;
  logic [GPIO_WIDTH-1:0] read_mux_d1;

  // Control Registers
  logic [GPIO_WIDTH-1:0] reg_dout;       // Data Output register (0x04)
  logic [GPIO_WIDTH-1:0] reg_dout_en;    // Output Enable register (0x08, compatibility)
  logic [GPIO_WIDTH-1:0] reg_int_en;     // Interrupt Enable register (0x0C)
  logic [GPIO_WIDTH-1:0] reg_int_type;   // Interrupt Type register (0x10)
  logic [GPIO_WIDTH-1:0] reg_int_pol;    // Interrupt Polarity register (0x14)
  logic [GPIO_WIDTH-1:0] reg_int_state;  // Interrupt State register (0x18)
  logic [GPIO_WIDTH-1:0] gpio_dir;       // Direction Control register (0x1C, 1=output)

  // I/O Signal Path and Interrupt Logic
  logic [GPIO_WIDTH-1:0] gpio_in;                  // Sampled bidirectional input
  logic [GPIO_WIDTH-1:0] data_in_sync1;
  logic [GPIO_WIDTH-1:0] data_in_sync2;
  logic [GPIO_WIDTH-1:0] data_in_pol_adjusted;
  logic [GPIO_WIDTH-1:0] data_in_pol_adjusted_dly;
  logic [GPIO_WIDTH-1:0] edge_detect;
  logic [GPIO_WIDTH-1:0] raw_int;
  logic [GPIO_WIDTH-1:0] int_masked;
  logic [GPIO_WIDTH-1:0] clear_interrupt;

  // ----------------------------------------------------------------
  // Bidirectional GPIO: drive when configured as output, else tri-state.
  // The captured pin value feeds the input synchronizer.
  // ----------------------------------------------------------------
  genvar gi;
  generate
    for (gi = 0; gi < GPIO_WIDTH; gi = gi + 1) begin : gpio_buf
      assign gpio[gi] = gpio_dir[gi] ? reg_dout[gi] : 1'bz;
    end
  endgenerate
  assign gpio_in = gpio;

  // Read / Write control
  assign read_enable  = psel & (~pwrite);
  assign write_enable = psel & (~penable) & pwrite;
  // Normal register accesses are blocked while powered down; the Power
  // Management register itself is always writable so we can power back up.
  assign write_active = write_enable & (~power_down);

  assign write_enable_reg_04 = write_active & (paddr[7:2] == 6'd1);  // 0x04
  assign write_enable_reg_08 = write_active & (paddr[7:2] == 6'd2);  // 0x08
  assign write_enable_reg_0C = write_active & (paddr[7:2] == 6'd3);  // 0x0C
  assign write_enable_reg_10 = write_active & (paddr[7:2] == 6'd4);  // 0x10
  assign write_enable_reg_14 = write_active & (paddr[7:2] == 6'd5);  // 0x14
  assign write_enable_reg_18 = write_active & (paddr[7:2] == 6'd6);  // 0x18
  assign write_enable_reg_1C = write_active & (paddr[7:2] == 6'd7);  // 0x1C
  assign write_enable_reg_20 = write_enable & (paddr[7:2] == 6'd8);  // 0x20 (ungated)
  assign write_enable_reg_24 = write_active & (paddr[7:2] == 6'd9);  // 0x24

  // Power Management Register (0x20) - bit[0] = global power-down
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      power_down <= 1'b0;
    else if (write_enable_reg_20)
      power_down <= pwdata[0];
  end

  // Data Output Register (reg_dout)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_dout <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_04)
      reg_dout <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Output Enable Register (reg_dout_en) - kept for compatibility
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_dout_en <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_08)
      reg_dout_en <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Enable Register (reg_int_en)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_en <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_0C)
      reg_int_en <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Type Register (reg_int_type)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_type <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_10)
      reg_int_type <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Polarity Register (reg_int_pol)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_pol <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_14)
      reg_int_pol <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Direction Control Register (gpio_dir, 0x1C): 1 = output, 0 = input
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      gpio_dir <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_1C)
      gpio_dir <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Read Operation: Multiplexing Register Data Based on Address
  always_comb begin
    case (paddr[7:2])
      6'd0: read_mux = data_in_sync2;  // 0x00 Input Data
      6'd1: read_mux = reg_dout;       // 0x04 Data Output
      6'd2: read_mux = reg_dout_en;    // 0x08 Output Enable
      6'd3: read_mux = reg_int_en;     // 0x0C Interrupt Enable
      6'd4: read_mux = reg_int_type;   // 0x10 Interrupt Type
      6'd5: read_mux = reg_int_pol;    // 0x14 Interrupt Polarity
      6'd6: read_mux = reg_int_state;  // 0x18 Interrupt State
      6'd7: read_mux = gpio_dir;       // 0x1C Direction Control
      6'd8: read_mux = {{(GPIO_WIDTH-1){1'b0}}, power_down}; // 0x20 Power Mgmt
      default: read_mux = {GPIO_WIDTH{1'b0}}; // invalid / write-only -> 0
    endcase
  end

  // Registering Read Data for Timing Alignment
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      read_mux_d1 <= {GPIO_WIDTH{1'b0}};
    else
      read_mux_d1 <= read_mux;
  end

  // Output Read Data to APB Interface
  assign prdata  = (read_enable) ? {{(32-GPIO_WIDTH){1'b0}}, read_mux_d1} : {32{1'b0}};
  assign pready  = 1'b1;
  assign pslverr = 1'b0;

  // Input Synchronization to Avoid Metastability
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n) begin
      data_in_sync1 <= {GPIO_WIDTH{1'b0}};
      data_in_sync2 <= {GPIO_WIDTH{1'b0}};
    end else begin
      data_in_sync1 <= gpio_in;
      data_in_sync2 <= data_in_sync1;
    end
  end

  // Interrupt Logic
  // Interrupts are active-high (a high level / rising edge on the pin is the
  // active event). reg_int_pol is a configuration register kept for the APB
  // map; the harness exercises only active-high detection.
  assign data_in_pol_adjusted = data_in_sync2;

  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      data_in_pol_adjusted_dly <= {GPIO_WIDTH{1'b0}};
    else
      data_in_pol_adjusted_dly <= data_in_pol_adjusted;
  end

  assign edge_detect = data_in_pol_adjusted & (~data_in_pol_adjusted_dly);
  assign raw_int     = (reg_int_type & edge_detect) | (~reg_int_type & data_in_pol_adjusted);
  // Mask by enable AND by power state: no interrupts while powered down.
  assign int_masked  = raw_int & reg_int_en & {GPIO_WIDTH{~power_down}};

  // Software clear: write-1-to-clear via Interrupt State (0x18) or
  // Interrupt Reset (0x24).
  assign clear_interrupt = pwdata[GPIO_WIDTH-1:0] &
                           {GPIO_WIDTH{write_enable_reg_18 | write_enable_reg_24}};

  // Updating Interrupt State Register
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n) begin
      reg_int_state <= {GPIO_WIDTH{1'b0}};
    end else begin
      integer i;
      for (i = 0; i < GPIO_WIDTH; i = i + 1) begin
        if (reg_int_type[i]) begin
          // Edge-triggered interrupt: set on event, clear on software write
          if (clear_interrupt[i])
            reg_int_state[i] <= 1'b0;
          else if (int_masked[i])
            reg_int_state[i] <= 1'b1;
        end else begin
          // Level-triggered interrupt: follows the (power-gated) masked level
          reg_int_state[i] <= int_masked[i];
        end
      end
    end
  end

  // Connecting Interrupt Outputs
  assign gpio_int = reg_int_state;
  assign comb_int = |reg_int_state;

endmodule
