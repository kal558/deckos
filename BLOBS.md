# Non-free firmware in deckOS

All deckOS software is free/open source. The hardware needs a few closed firmware files
that no open replacement exists for. This is the complete list.

| Firmware | Board / device | Why it's needed | Source |
|---|---|---|---|
| Rockchip DDR init (TPL) | Radxa Zero 3W | Trains the RAM at power-on, before Linux runs. Every RK3566 board needs it. | Rockchip `rkbin`, via Armbian's U-Boot |
| Wi-Fi/Bluetooth firmware (AIC8800) | Radxa Zero 3W | Runs inside the wireless chip | `armbian-firmware` |
| Raspberry Pi boot/GPU firmware (`start*.elf`, EEPROM) | Pi 4 / Pi 5 | The Pi's boot loader runs on the GPU | Raspberry Pi, via Armbian |
| Broadcom/Cypress Wi-Fi/BT firmware | Pi 4 / Pi 5 | Runs inside the wireless chip | `armbian-firmware` |
| `dvb-demod-si2168-*.fw`, `dvb-tuner-si2158-*.fw`, `dvb-usb-dib0700-*.fw` | DVB-T2 USB tuners | Demodulator/tuner microcode | [LibreELEC dvb-firmware](https://github.com/LibreELEC/dvb-firmware) |
| Meshtastic node firmware | Your LoRa node | Open source (GPL), but runs on the node, not in this image | meshtastic.org |

**Not included, user-supplied:** console BIOS files (for example PS1) and game ROMs. Put your own
legally obtained files in `/deck/games/bios` and `/deck/games/roms`.

**Fully open, worth noting:** the GPU driver (Mesa Panfrost on the Zero 3W, V3D on the Pi) and
the video decoders (V4L2) are open source.
