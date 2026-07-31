# RP2350 Pico Sensor Testing

The board appeared in UF2 bootloader mode with:

```text
UF2 Bootloader v1.0
Model: Raspberry Pi RP2350
Board-ID: RP2350
```

This means the board is in firmware-loading mode and is waiting for a compatible `.uf2` firmware file.

## Firmware Target

The inspected firmware repo is `Msiebers/encoder_imu_c` at commit `8ca90c765a493275c007ee4e49d15ef846fc8787`.

The firmware build is configured for Pico 2 / RP2350:

- `encoder_imu_c/CMakeLists.txt:5` sets `PICO_BOARD pico2`.
- `encoder_imu_c/handy bash build encoder_imu_c:4` also shows `cmake .. -DPICO_BOARD=pico2`.
- `encoder_imu_c/CMakeLists.txt:49` calls `pico_add_extra_outputs(encoder_imu_c)`, so the expected firmware artifact is `encoder_imu_c.uf2` from the CMake build output directory.

Practical loading step: copy the built `encoder_imu_c.uf2` file onto the RP2350 bootloader drive. The board should reboot after the copy.

## Sensor Interfaces

The firmware reads:

- BNO085 IMU in UART-RVC mode: `src/main.cpp:23-25` sets `uart0`, GPIO1 RX, and 115200 baud.
- Quadrature encoder through PIO: `src/main.cpp:33-34` sets encoder pin base GPIO18 and a 1 kHz sample interval; `src/main.cpp:223-234` initializes encoder GPIO and `QuadratureDecoder`.
- PPS through GPIO9 and PIO1: `src/main.cpp:37-38` defines `PPS_PIN 9` and `PPS_PIO pio1`; `src/main.cpp:292-303` initializes PPS capture.
- USB serial output: `CMakeLists.txt:46-47` enables USB stdio and disables UART stdio.

The build links `hardware_i2c`, but the inspected active IMU path is UART-RVC, not I2C: `src/main.cpp:15-25` and `src/main.cpp:104-112`.

## Timing and Output

The firmware uses `time_us_64()` for microsecond timestamps. Sync reset stores `time_offset_us` and resets encoder offset, PPS counter, IMU timestamp, and the ring buffer in `src/main.cpp:194-218`.

Core 1 snapshots motion rows into `Event`:

- timestamp: `src/main.cpp:72`
- encoder count: `src/main.cpp:73`
- roll/pitch/yaw: `src/main.cpp:74-76`
- IMU timestamp: `src/main.cpp:77`
- PPS count: `src/main.cpp:78`

Rows are populated in `src/main.cpp:253-278`.

The serial header is printed in `src/main.cpp:314`:

```text
TS_US,ENC,ROLL_DEG,PITCH_DEG,YAW_DEG,IMU_TS_US,PPS
```

Data rows are printed in `src/main.cpp:340-351` with prefix `l,` and values:

```text
l,<timestamp_us>,<encoder_count>,<roll_deg>,<pitch_deg>,<yaw_deg>,<imu_ts_us>,<pps>
```

## Serial Commands

The inspected firmware recognizes `s` as the sync/reset command in `src/main.cpp:317-331`.

I found no firmware handling for a `b` command. Treat “press b” as not verified for this firmware until a separate SLIM-side test script is inspected.

## Match to `lidar_analysis`

`lidar_analysis` expects Pico CSV columns in `lidar_analysis/pipeline_core.py:411-419`:

```text
time_s,count,roll_deg,pitch_deg,yaw_deg,pps
```

Optional:

```text
imu_time_s
```

The firmware emits the same data conceptually, but in firmware-native names and microseconds:

| Firmware serial | Analysis CSV |
|---|---|
| `TS_US` | `time_s` after conversion to seconds |
| `ENC` | `count` |
| `ROLL_DEG` | `roll_deg` |
| `PITCH_DEG` | `pitch_deg` |
| `YAW_DEG` | `yaw_deg` |
| `IMU_TS_US` | `imu_time_s` after conversion to seconds |
| `PPS` | `pps` |

## Current Observed Workflow

1. Connect Pico/RP2350 board to SLIM through micro USB.
2. If needed, hold BOOTSEL while plugging it in.
3. Board appears as an RP2350 storage device.
4. Copy the correct `encoder_imu_c.uf2` firmware file onto it.
5. Board reboots and runs the firmware.
6. On SLIM, go to the Pico folder / Pico test folder.
7. Use the test command. Pressing `b` remains needs verification; this firmware only confirms `s` for sync/reset.
8. Confirm the output includes time, encoder count, roll, pitch, yaw, IMU timestamp, PPS, and related fields.

## `cart_config.yaml` Placement

`central_runner` requires `cart_config.yaml` directly inside the input folder: `lidar_analysis/central_runner.py:556-563`.

Safe copy pattern on SLIM:

```bash
INPUT="/PATH/TO/FIELD_INPUT"
SOURCE_CART_CONFIG="/path/to/known/cart_config.yaml"

if [ -e "$INPUT/cart_config.yaml" ]; then
  echo "cart_config.yaml already exists; not overwriting: $INPUT/cart_config.yaml"
else
  cp "$SOURCE_CART_CONFIG" "$INPUT/cart_config.yaml"
fi
```
