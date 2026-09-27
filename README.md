# deckOS

A custom Linux OS for a **survival cyberdeck**: a keyboard-driven computer in a waterproof
case that stays useful with no internet, no mobile network and an unreliable power supply,
and is still a pleasant everyday machine.

**Primary board:** Radxa Zero 3W (2 GB). **Also:** Raspberry Pi 4 / Pi 5, from the same source.
Everything plugs in over USB or HDMI, with no soldering.

## What's on it

| | |
|---|---|
| **Offline knowledge** | Wikipedia (English, all articles), medical (WikiMed, MDWiki, field medicine), practical (iFixit, Appropedia, water, food, knots, outdoors), reference (Wiktionary, Stack Exchange). One search box covers all of it. |
| **Offline maps** | UK & Western Europe vector maps, place/postcode search, walk/cycle/drive routing, your GPS position, mesh contacts, "Wikipedia nearby", waypoints |
| **Radio** (RTL-SDR V4) | FM, DAB+, shortwave, amateur 2 m/70 cm, MW night-time DX, HF SSB, FT8 (plotted on the map), JS8Call, HF weather fax, Meteor-M weather-satellite images, SDR++ |
| **TV** (DVB-T2 stick) | Freeview HD live TV, guide, recording (tvheadend + Kodi) |
| **Mesh** (Meshtastic) | Licence-free encrypted off-grid text messaging, receive-only by default |
| **Everyday** | Kodi media centre, retro games (ES-DE + RetroArch, up to PS1 and many N64/PSP titles), Firefox (hardened), full LibreOffice, notes, files, calculator |
| **Untrackable by default** | Wi-Fi and Bluetooth off at every boot, mesh receive-only, no telemetry, no automatic updates, nothing listens on the network, encrypted personal data, optional Tor mode |
| **Robust** | Read-only system (pull the power any time), runs within 2 GB RAM, every feature degrades gracefully when its hardware is unplugged |

## Quick start

1. Buy the hardware: [docs/HARDWARE.md](docs/HARDWARE.md)
2. Build the image: [docs/BUILDING.md](docs/BUILDING.md), then run `./build.sh --board zero3w`
3. Flash it, boot, and follow the first-boot setup: [docs/USER-GUIDE.md](docs/USER-GUIDE.md)

## Layout

```
build.sh              one command → flashable image (runs the Armbian build framework)
deckos.conf           which modules go into the image
boards/               per-board settings (Zero 3W, Pi 4/5)
modules/<name>/       packages.list · install.sh · files/ · manifest.toml (home-screen tiles)
src/deckos/           the deckOS tools and apps (Python + GTK4)
userpatches/          Armbian hook that installs the modules
tests/unit/           pytest suite for everything in src/
tests/image/          boot the built image in a container: smoke + privacy tests
tools/                PC-side helpers (map search index + routing tiles)
docs/                 guides and the design spec
```

Design: [docs/superpowers/specs/2026-09-27-deckos-design.md](docs/superpowers/specs/2026-09-27-deckos-design.md).
Non-free firmware included and why: [BLOBS.md](BLOBS.md).

## Status

Version 0.1. **Never yet built or booted on hardware.** The unit tests cover the deckOS
logic. Board bring-up (kernel, video decoding, the exact package set on Debian trixie) is
checked by the first real build and `deck-selftest`. [docs/BUILDING.md](docs/BUILDING.md#first-build-checklist)
lists what to watch for on that first build.

Licence: GPL-3.0-or-later.
