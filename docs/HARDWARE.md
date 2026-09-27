# Hardware (solderless build, UK/EU)

Everything connects by USB or HDMI. Prices are rough 2026 UK figures.

## Core

| Part | Recommendation | Notes |
|---|---|---|
| Board | **Radxa Zero 3W, 2 GB** (4/8 GB better if you buy again) | Add a stick-on heatsink |
| Boot storage | 32–64 GB A2 microSD (or a Zero 3W with eMMC) | The OS takes ~12 GB; the rest becomes encrypted personal storage |
| Data storage | **256 GB USB 3 SSD** (e.g. Samsung T7) | Formatted by the deck as `DECKDATA` |
| Hub | **Powered USB 3 hub**, USB-C upstream | The Zero 3W has only two USB-C ports |
| Display | 7–10″ HDMI screen, USB-powered | Zero 3W has **micro**-HDMI, so get a micro-HDMI → HDMI cable |
| Keyboard | **Wired** compact USB keyboard with touchpad | Wireless (2.4 GHz/Bluetooth) keyboards transmit all the time |
| Power | USB-C PD power bank, 20,000 mAh (≈74 Wh), **two outputs** | One output for the board, one for the hub/screen. Keep it at 100 Wh or under if you'll fly with it. |
| Case | Pelican 1300/1450-size with pick-and-pluck foam | Sealed cases trap heat. See "Heat" below. |

## Radio, TV, mesh, GPS

| Part | Recommendation | Why |
|---|---|---|
| SDR | **RTL-SDR Blog V4** kit (with dipole antennas) | FM, DAB+, shortwave, amateur, satellites. Tunes 0.5–1766 MHz. |
| HF antenna | Random-wire antenna + **9:1 unun** (screw terminals, SMA) | Makes shortwave/HF usable. The kit's telescopic antennas are poor below 30 MHz. |
| Satellite antenna | V-dipole (in the V4 kit) or a QFH | For Meteor-M images |
| TV tuner | **Hauppauge WinTV-dualHD** (DVB-T2) | Mainline Linux driver. Freeview HD needs DVB-T2, which the RTL-SDR can't decode. |
| TV aerial | Small DVB-T aerial with a coax (IEC/MCX) adapter | |
| Mesh | **Heltec WiFi LoRa 32 V3, 868 MHz** or **RAK WisBlock 4631 starter kit, 868 MHz** | Licence-free in the UK/EU. Buy the 868 MHz version, not 915. |
| GPS | **u-blox 7 or 8 USB receiver** (VK-172/VK-162 style) | Passive (receive-only). Also sets the clock with no internet. |
| Adapters | SMA bulkhead pass-throughs, short right-angle USB-C/USB-A cables | Lets antennas connect with the lid shut |

## Power budget (approximate)

| Item | Watts |
|---|---|
| Zero 3W (busy) | 2–4 |
| 7″ screen | 2–4 |
| SSD (active) | 1–2 |
| RTL-SDR | ~1.5 |
| DVB-T2 stick | ~1.5 |
| Meshtastic node | ~0.5 |
| GPS | ~0.3 |

A typical session draws 5–8 W, so a 74 Wh bank gives roughly 8–12 hours (and more in the
Field power profile). The deck can't read a power bank's charge, so it shows an **estimate**
from the capacity you enter.

## Heat

A waterproof case has no airflow. The Zero 3W is low-power and is fine with a heatsink. deckOS
warns at 75 °C and drops to the Field profile at 80 °C. On a **Pi 5**, fit the official Active
Cooler and open the lid for long sessions.

## Raspberry Pi instead

Build with `./build.sh --board rpi` (one image boots both the Pi 4 and the Pi 5).
- Pi 4/5 have four USB-A ports, so **no hub is needed**.
- Pi 5 is 2–3× faster (N64/PSP/Dreamcast play properly, Firefox feels normal). It can use an
  **NVMe SSD HAT**, and has an **RTC** (the battery plugs in; no soldering).
- Pi 5 wants **5 V / 5 A**. Most power banks give 3 A, which limits USB peripherals to 600 mA
  in total. Use a 5 A-capable bank or put the SSD/SDR on a powered hub.
