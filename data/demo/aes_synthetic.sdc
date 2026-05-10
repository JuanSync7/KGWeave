# Synthetic AES timing constraints — for KGWeave SDC extractor demo.
# Anchored to AES top-level port names so fusion exercises both the
# direct-name path (clk_i, rst_ni) and the namespaced path (aes.clk_i).

# Primary clock
create_clock -name main_clk -period 10.000 [get_ports clk_i]

# Generated clock for an internal divider
create_generated_clock -name aes_div2 -source [get_ports clk_i] \
    -divide_by 2 [get_pins divider/clk_div_q]

# Input/output delays
set_input_delay  -clock main_clk 2.0 [get_ports data_in]
set_input_delay  -clock main_clk 2.5 [get_ports key_init]
set_output_delay -clock main_clk 1.5 [get_ports data_out]

# False paths between async resets and core data
set_false_path -from [get_ports rst_ni] -to [get_ports data_out]
set_false_path -from [get_ports lc_escalate_en_i] -to [get_ports data_out]

# Multicycle paths inside the round-key expansion logic
set_multicycle_path -setup 2 -from [get_clocks main_clk] -to [get_clocks main_clk]
set_multicycle_path -hold 1 -from [get_clocks main_clk] -to [get_clocks main_clk]

# Async clock domains
set_clock_groups -asynchronous \
    -group {main_clk} \
    -group {aes_div2}
