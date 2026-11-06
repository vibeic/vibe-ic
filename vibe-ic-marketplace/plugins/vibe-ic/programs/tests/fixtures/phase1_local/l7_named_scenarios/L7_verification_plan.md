# Verification Plan

1. **reset_count** — drive rst_n low;
   check count_o == 0.
2. **read_back** — write write_data to the data register;
   check read_data == write_data.
3. **probe_override** — force supplied_count through the probe bus;
   check observed_count mirrors supplied_count.
4. **masking** — exercise simultaneous masked writes and arbitration.

## Coverage targets
- Every named scenario must run.
