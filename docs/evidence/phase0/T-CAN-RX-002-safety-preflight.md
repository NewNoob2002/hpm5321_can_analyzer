# T-CAN-RX-002 Safety Preflight

- Board: `Gerber_PCB1_2026-07-23`, serial `20260723`
- Adapter: `CANDBG-01`, channel `CAN0`
- Bus: Classic CAN, 500 kbit/s, standard ID
- Authorized stimulus: ID `0x321`, DLC 8, payload `48 50 4D 52 00 00 00 01`
- Firmware behavior: MCAN normal mode for hardware ACK and receive only
- Software TX: disabled (`MCAN0_ACTIVE_TX=0`); linked ELF contains no transmit function
- Auto retransmission: disabled
- Stop condition: one matching frame, controller warning/passive/bus-off, or one-hour timeout
- Physical preconditions: transceiver normal mode, measured idle CANH/CANL 2.52 V, switched termination enabled at 119 ohm when powered off

Residual safety limitation: the current PCB fixes transceiver STB low. Firmware makes
MCAN pins inputs during early board initialization and connects the peripheral pinmux
only after controller initialization, but cannot control the interval before firmware
executes.
