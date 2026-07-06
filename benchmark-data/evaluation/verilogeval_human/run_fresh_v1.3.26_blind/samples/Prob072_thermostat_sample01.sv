module TopModule (
  input mode,
  input too_cold,
  input too_hot,
  input fan_on,
  output heater,
  output aircon,
  output fan
);

  // Heating mode (mode=1): heater on when too cold; aircon off.
  // Cooling mode (mode=0): aircon on when too hot; heater off.
  assign heater = mode & too_cold;
  assign aircon = ~mode & too_hot;
  // Fan runs whenever heater or aircon is on, or when user requests it.
  assign fan = heater | aircon | fan_on;

endmodule
