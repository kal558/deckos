# deckOS — Design Spec

**Date:** 2026-09-27
**Status:** Draft for review
**Target hardware:** Radxa Zero 3W (RK3566, 2 GB RAM) — primary; Raspberry Pi 4 / Pi 5 — secondary

## 1. Purpose

deckOS is a custom Linux OS image for a survival cyberdeck: a keyboard-driven computer in a
waterproof Pelican case that remains fully useful with no internet, no mobile network and an
unreliable power supply, while still being a pleasant everyday machine (video, games, browsing,
office work).

### Goals

1. Offline access to a large knowledge library (Wikipedia, medical, practical, reference) and offline maps with search and routing.
2. Passive radio and TV reception (UK/EU): FM, DAB+, shortwave, long-range HF modes, Freeview HD.
3. Licence-free off-grid text messaging via Meshtastic.
4. Everyday usability: hardware-accelerated video, retro gaming, web browsing, LibreOffice.
5. **Untrackable by default:** no radio or network emission unless the user deliberately enables it.
6. Robust in the field: survives sudden power loss, runs within 2 GB RAM, handles missing peripherals gracefully.
7. Solderless build: every peripheral connects over USB or HDMI.
8. Reproducible: one command on a PC builds a flashable image for the chosen board.

### Non-goals (this version)

- Radio transmission other than Meshtastic (no amateur TX).
- Reception of non-broadcast services (airband, marine VHF, PMR446) and ADS-B. The band-preset design allows adding them later.
- Accurate battery percentage (requires a soldered fuel gauge — future optional module).
- GPIO-dependent hardware.
- Automatic updates of any kind.

## 2. Hardware assumptions

| Item | Choice | Notes |
|---|---|---|
| SBC | Radxa Zero 3W, 2 GB | Pi 4 / Pi 5 supported via board profile |
| Boot/OS storage | microSD or eMMC, ≥ 32 GB | Read-only root |
| Data storage | USB 3 SSD, 256 GB, ext4, label `DECKDATA` | Pi 5: NVMe HAT optional |
| Hub | Powered USB 3.0 hub | Zero 3W only; Pi 4/5 have 4× USB-A |
| Display | Any HDMI screen, 1024×600 to 1920×1080 | |
| Input | **Wired** USB keyboard (clamshell/laptop style); optional USB gamepad | Wired avoids 2.4 GHz emissions |
| Power | USB-C PD power bank | Pi 5 needs 5V/5A for full USB current |
| Radio | RTL-SDR Blog V4 | + random-wire antenna with 9:1 unun for HF |
| TV | DVB-T2 USB tuner with mainline Linux support (e.g. Hauppauge WinTV-dualHD) | Freeview HD is DVB-T2 |
| Mesh | USB Meshtastic node, EU 868 MHz (e.g. Heltec V3, RAK WisBlock) | |
| GPS | USB GPS receiver (u-blox 7/8) | Passive; alternatively a GPS-equipped mesh node |

## 3. Architecture

### 3.1 Build system

Based on the **Armbian build framework** (pinned version), run inside Docker or WSL2 on the
user's Windows PC. Armbian provides Debian userland, mainline kernel and Mesa Panfrost for the
Zero 3W, and supports Pi 4/5 via its `rpi4b` target.

```
deckos/
├── build.sh              # ./build.sh --board zero3w|rpi  → output/deckos-<board>-<date>.img
├── deckos.conf           # list of enabled modules, image options
├── armbian/              # pinned upstream build framework (submodule)
├── userpatches/          # Armbian hooks: customize-image.sh, rootfs overlay
├── boards/
│   ├── radxa-zero3w.conf
│   └── rpi4-5.conf
├── modules/
│   ├── base/  shell/  emcon/  knowledge/  maps/
│   ├── radio/  tv/  mesh/  media/  games/  office/  tools/  survival/
├── tests/
└── docs/
```

**Kernel fallback:** if mainline hardware video decoding on RK3566 proves inadequate during
phase 1 (especially HEVC), `radxa-zero3w.conf` switches to Radxa's vendor kernel. No module
changes are required.

### 3.2 Board profiles

Each `boards/*.conf` defines: Armbian board target, kernel branch, video-decode method
(V4L2 stateless / stateful / vendor MPP), Wi-Fi/BT firmware packages, GPU driver, whether a USB hub
is expected, RTC availability, and default power/thermal thresholds. Modules never contain
board-specific logic; they query the profile via `/etc/deckos/board.conf`.

### 3.3 Module contract

Every module directory contains:

| File | Purpose |
|---|---|
| `packages.list` | Debian packages to install |
| `install.sh` | Build-time setup (runs in image chroot); must be idempotent |
| `files/` | Config files and systemd units copied into the rootfs |
| `manifest.toml` | Launcher entry: id, name, icon, command, `heavy` flag, required hardware (udev match), status command |
| `tests/` | Unit tests for any code the module contains |

Enabling/disabling a module is one line in `deckos.conf`.

### 3.4 Runtime storage layout

| Location | Filesystem | Contents | Encryption |
|---|---|---|---|
| SD/eMMC: boot + root | ext4, **read-only** via overlayroot (tmpfs upper) | OS | No |
| SD/eMMC: `/persist` (~2 GB) | ext4 | Settings, Wi-Fi profiles, bookmarks, notes, mesh keys + messages, waypoints | **LUKS** |
| SSD: `/deck/library` | ext4 | ZIM files, PMTiles, search index, Valhalla tiles | No |
| SSD: `/deck/media` | ext4 | Video, music, TV recordings, satellite images | No |
| SSD: `/deck/games` | ext4 | ROMs, BIOS, saves | No |
| SSD: `/deck/personal` | LUKS container | Documents, backups of `/persist` | **LUKS** |
| SSD: `/deck/swap` | swap file | Last-resort swap | Encrypted (random key per boot) |

- Power can be cut at any time without corrupting the OS.
- **Factory reset** = boot once with the overlay discarded and `/persist` re-initialised (confirmed twice).
- The SSD is mounted by label. If absent, the OS still boots; dependent tiles show "SSD not connected".
- LUKS passphrase is requested at boot. Wrong or skipped passphrase → deck boots with library, maps, radio and media usable, but no personal data mounted.

### 3.5 Hardware-triggered services

udev rules start/stop services when their device appears/disappears: tvheadend (DVB tuner),
meshd (Meshtastic node), gpsd (GPS receiver), SDR lock service (RTL-SDR). Nothing hardware-specific
runs without its hardware.

## 4. Deck shell

- **Compositor:** Sway, configured so every app is fullscreen; no floating windows.
- **Home screen** (`deck-home`, Python + GTK4): full-screen tile grid generated from module manifests. Tiles show live status (e.g. "Mesh: 2 unread", "TV: tuner not connected", "Library: 104 GB").
- **Status bar:** time, EMCON TX indicator, Wi-Fi, Bluetooth, GPS fix, mesh unread count, SSD status, CPU temperature, power profile, estimated runtime.
- **Global search** (`deck-search`): single query across ZIM full-text search, map places, apps, media filenames, notes, mesh messages and contacts; results grouped by source.
- **Themes:** dark amber-on-black (default) and high-contrast daylight mode, toggled by one key.
- **Scaling:** 1024×600 to 1920×1080.
- **Fallback:** if the shell crashes, Sway remains and ⊞+Enter opens a terminal.

### Keybindings

| Key | Fallback | Action |
|---|---|---|
| ⊞ | Ctrl+Alt+Space | Home |
| ⊞+Space | Ctrl+Alt+S | Global search |
| ⊞+Tab | Alt+Tab | Switch app |
| ⊞+Q | Ctrl+Alt+Q | Close app |
| ⊞+Esc | Ctrl+Alt+Del | Power menu |
| ⊞+E | Ctrl+Alt+E | EMCON panel |
| ⊞+Shift+E | Ctrl+Alt+Shift+E | Go silent (all TX off) |
| ⊞+D | Ctrl+Alt+D | Toggle daylight theme |
| ⊞+Enter | Ctrl+Alt+T | Terminal |
| ⊞+F1 / F1 | — | Cheat sheet |

## 5. Privacy and emissions control (EMCON)

**Principle: the deck makes no radio or network transmission unless the user deliberately enables it.**

### 5.1 Transmitter defaults

| Transmitter | Boot default | How to enable |
|---|---|---|
| Wi-Fi | Off (soft-off on every boot, not blocked or disabled) | Settings → Radios, or EMCON panel |
| Bluetooth | Off (soft-off on every boot, not blocked or disabled) | Settings → Radios, or EMCON panel |
| Meshtastic | Receive-only (`lora.tx_enabled = false`) | EMCON panel |
| SDR, DVB-T2, GPS | Passive receivers — always allowed | n/a |

- Status bar shows **SILENT** (green) or **TX: WiFi, Mesh…** (red).
- ⊞+Shift+E returns every transmitter to its off/receive-only state immediately.
- The EMCON panel states plainly that encryption hides content but not the fact of transmitting; an active transmitter can be located by direction-finding.

### 5.2 Per-transmitter hardening

- **Wi-Fi:** random MAC per connection; no background probing for saved networks; generic hostname; never auto-join open networks.
- **Bluetooth:** non-discoverable; pairing only during a user-opened 60-second window; LE privacy (random resolvable address); only required profiles loaded.
- **Meshtastic:** private channel with user-generated PSK (default public channel removed); position broadcast off by default; when on, precision reduced to ~1 km unless changed; randomly generated node name; `CLIENT` role by default.

### 5.3 System hardening

- Firewall (nftables): default-deny inbound; outbound only while a network is up.
- No service listens on a non-loopback interface. kiwix-serve, tvheadend, Valhalla etc. bind to 127.0.0.1. Samba share (library import) is off by default and, when enabled, binds only to the active interface with a user password and auto-disables on reboot.
- No telemetry anywhere; no automatic update checks (apt, Kodi, LibreOffice, Firefox, RetroArch).
- DNS over TLS when online; optional **Tor mode** routes all traffic through Tor.
- Time from GPS; no NTP. Last-known time saved at shutdown (fake-hwclock).
- journald volatile (logs in RAM only).
- `BLOBS.md` lists every non-free firmware file included and why.

## 6. Modules

### 6.1 knowledge

- `kiwix-serve` on 127.0.0.1 serving all ZIMs in `/deck/library/zim`, catalogue regenerated by Library Manager.
- **Reader** (`deck-reader`): single WebKitGTK process with tabs, themed; back/forward, find, bookmarks and reading list (in `/persist`). Shared with maps.
- Tiles deep-link: Wikipedia, Medical, Practical (combined index), Reference.
- **Initial library (~105 GB):**
  - Wikipedia EN, no images (~55 GB)
  - Medical: WikiMed and first-aid/drug references (~4 GB)
  - Practical: iFixit, Wikivoyage, Wikibooks, Appropedia, survival manuals (~15 GB)
  - Reference (light): Wiktionary, curated Gutenberg selection, selected Stack Exchange sites (~15 GB)
- **Library Manager:** shows installed content, sizes, age, free space; when online, downloads/updates from official Kiwix and map mirrors with checksum verification; import from a PC over the optional Samba share.

### 6.2 maps

- UK + Western Europe vector tiles as PMTiles (~15 GB incl. routing and search), rendered by MapLibre GL in `deck-reader`.
- Offline place/address/postcode search: SQLite FTS index built from OSM.
- Offline routing: Valhalla (walk, cycle, drive) on 127.0.0.1.
- Position from gpsd (USB GPS; mesh node GPS as fallback).
- Layers: own position, mesh contacts, "Wikipedia nearby" (geotagged articles), waypoints (in `/persist`, shareable over mesh), FT8 spots (from radio module).

### 6.3 radio

- **SDR lock:** only one app uses the RTL-SDR at a time; the lock reports the current owner.
- **Radio app** (`deck-radio`, preset-based): tabs for FM, DAB+ (`welle-cli`), Shortwave broadcast, Amateur 2 m / 70 cm, and **DX / Long range**:
  - MW/LW night-time DX
  - Amateur HF SSB (80/40/20 m)
  - FT8 decoding, spots plotted on map, propagation view
  - JS8Call (receive-only)
  - HF weather fax (Met Office Northwood, DWD Pinneberg) via fldigi, images saved to media
- Band presets are data files; adding a band is a one-file change.
- **Advanced:** SDR++ for waterfall, manual tuning, recording.
- **Weather satellites:** Meteor-M LRPT via SatDump; offline pass prediction; TLEs refresh when online; images saved to `/deck/media/satellite`.

### 6.4 tv

- tvheadend (loopback only): Freeview HD (DVB-T2) tuning, EPG, recording to `/deck/media/recordings`.
- Frontend: Kodi Live TV (PVR add-on); TV tile opens Kodi directly in Live TV.

### 6.5 mesh

- **`meshd`** (Python, meshtastic library): sole owner of the node's serial port; enforces EMCON (tx_enabled, position precision, private channel); stores messages in SQLite in `/persist`; exposes a local UNIX socket API to other apps.
- **Mesh app:** conversations (channels + DMs), node list (SNR, last heard), send waypoint from map.
- Integrations: map layer, status bar unread count, global search.
- Fallback: `contact` TUI client.

### 6.6 media

- Kodi for video, music, photos, recordings, satellite images; V4L2 hardware decode (H.264 1080p guaranteed; HEVC/VP9 subject to phase-1 verification).
- Add-on repositories, update checks and network sharing disabled.
- mpv for single-file playback from search/file manager.

### 6.7 games

- ES-DE frontend + RetroArch cores:
  - Solid: NES, SNES, GB/GBC/GBA, Mega Drive, Master System, PC Engine, FBNeo arcade, PS1 (PCSX-ReARMed), DOSBox Pure, ScummVM.
  - Heavy (many titles playable): N64 (mupen64plus-next), PSP (PPSSPP), Dreamcast (Flycast).
- Keyboard mapping by default; USB gamepads autoconfigured. Saves in `/deck/games/saves`.
- Bundled: selected free homebrew, OpenTTD, Freeciv. User supplies ROMs and BIOS files.

### 6.8 office

- LibreOffice full suite (Writer, Calc, Impress, Draw, Base, Math), en-GB spelling, hyphenation, offline help.
- Update check, crash reporter and online features off; macros disabled.
- Default save location: `/deck/personal/documents`.

### 6.9 browser (in `tools` module)

- Firefox ESR via enterprise policies: telemetry off, uBlock Origin, no search suggestions, DNS over TLS, clear history on close (default), tab unloading, reduced content processes and cache on 2 GB boards.
- Offline banner with a shortcut to the EMCON panel.

### 6.10 tools

Terminal, file manager, text editor, notes (in `/persist`), calculator/unit converter, system monitor, Settings (radios, power profile, theme, passphrase, Samba import, update, factory reset).

### 6.11 survival

Power profiles, thermal watchdog, runtime estimate, standby, backup/restore, `deck-selftest` (see §8, §9).

## 7. Memory strategy (2 GB baseline)

- zram (zstd), sized ~ RAM; encrypted swap file on the SSD as last resort; never swap to SD.
- **Heavy-app rule:** Firefox, LibreOffice, Kodi, N64/PSP/Dreamcast emulation are `heavy = true`. Launching a heavy app while another runs prompts to close the first (saving where possible). Light apps (radio audio, meshd, reader, maps) run alongside anything.
- One shared reader process for knowledge + maps.
- Services start only with their hardware; unneeded system services removed.
- **RAM detection at boot:** ≥ 4 GB relaxes the heavy-app rule and Firefox limits automatically.

## 8. Power and resilience

- **Profiles:** Field (CPU capped, dim screen, non-essential services stopped), Normal, Performance.
- **Thermal watchdog:** warns and drops to Field above a board-specific threshold (sealed Pelican case).
- **Runtime estimate:** from user-entered power-bank capacity (Wh), per-profile typical draw per board, and time since last full charge; labelled as an estimate.
- **Brownout awareness:** Pi uses firmware throttling flags; Zero 3W infers from kernel USB/undervoltage events.
- **Standby:** display off, CPU minimum; meshd continues receiving.
- **Crash safety:** read-only root; ext4 journal on SSD; SQLite WAL for app data.
- **Backup:** encrypted copy of `/persist` to `/deck/personal/backup` on every clean shutdown; first boot of a new image offers restore.

## 9. Updates

- Manual only. Settings → Update (when online): lists changes, reboots into maintenance mode (root writable), applies apt updates, reboots back to read-only.
- Library and maps updated via Library Manager.
- Whole-image upgrade: rebuild on PC, flash, restore from SSD backup.

## 10. Testing

| Layer | What | Where |
|---|---|---|
| Unit | deck-home, deck-search, meshd, EMCON logic, Library Manager, SDR lock, heavy-app rule | PC (pytest) |
| Image smoke | Boots; expected services active; Wi-Fi/BT off; firewall default-deny; `ss` shows no non-loopback listeners | QEMU aarch64 |
| Privacy | Idle 60 min with network attached, capture all traffic; **pass = zero outbound connections** | QEMU aarch64 + packet capture |
| Hardware | `deck-selftest`: SDR, DVB tuner, mesh node, GPS, SSD, GPU, video decode (H.264/HEVC test clips), audio | Real device |

## 11. Build phases

1. **Base:** Armbian image for Zero 3W, read-only root, `/persist` + LUKS, SSD mount, Sway shell (home, status bar, keybindings), EMCON + firewall, video-decode verification (kernel decision), QEMU tests.
2. **Knowledge + maps:** kiwix-serve, deck-reader, Library Manager, global search, PMTiles/MapLibre, place search, Valhalla, gpsd.
3. **Radio + mesh:** SDR lock, deck-radio with all tabs, SDR++, SatDump, meshd, Mesh app, map layers.
4. **TV, media, games, office:** tvheadend + Kodi, mpv, ES-DE + RetroArch, LibreOffice, Firefox policies, tools, heavy-app rule.
5. **Pi support + polish:** `rpi4-5.conf`, power profiles and runtime estimate, backup/restore, `deck-selftest`, docs, `BLOBS.md`.

Each phase ends with a bootable, usable image.

## 12. Open-source status

All software is FOSS; content is openly licensed (Wikipedia CC BY-SA, OSM ODbL). Unavoidable
non-free firmware: Rockchip DDR init (bootloader), Wi-Fi/BT firmware, DVB-T2 demodulator firmware,
Pi GPU/boot firmware on Pi boards. Console BIOS files are user-supplied and not shipped.

## 12a. Implementation notes (decisions made while building v0.1)

- **Image tests** boot the root filesystem in `systemd-nspawn` (with qemu-user on x86) rather
  than full-system QEMU, because the board images use board-specific boot firmware.
- **Mesh position precision:** the "~1 km" default is 14 precision bits (~1.5 km). Choices: off, ~3 km, ~1.5 km, ~700 m, ~350 m, exact.
- **Long wave is not available:** the RTL-SDR V4 tunes from 500 kHz. MW DX (531–1602 kHz) is included.
- **Satellites:** NOAA APT satellites are retired, so the target is Meteor-M LRPT via SatDump.
- **tvheadend** isn't packaged by Debian. It comes from the project's own apt repository.
- **Optional downloads at build time** (logged to `/etc/deckos/build-warnings.txt` if they fail):
  SDR++ (falls back to gqrx), SatDump, ES-DE (falls back to RetroArch), extra libretro cores,
  pmtiles CLI, DVB firmware.
- **Place search and routing data** are built on a PC with `tools/build-map-data.sh`, because
  Valhalla tile building needs more RAM than the deck has. Map tiles download directly on the deck.
- **App layout:** sway's tabbed layout (every app full-screen, a thin tab strip lists open apps).
  The reader is a single WebKitGTK process shared by the library and maps, and is locked to
  127.0.0.1 (external links are blocked and can be handed to Firefox).
- **Standby** locks the screen (swaylock) as well as turning it off.
- **Screen lock** also triggers one second after the screen goes idle.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Mainline RK3566 HEVC decode immature | Phase-1 verification; vendor kernel fallback via board profile |
| 2 GB RAM pressure | zram, heavy-app rule, low-memory Firefox config |
| Heat in sealed case | Thermal watchdog, Field profile; active cooler required on Pi 5 |
| Power bank current limits (Pi 5) | Documented; board profile sets USB current limits; powered hub option |
| Meshtastic firmware config drift | meshd re-applies EMCON config on every connect |
| RTL-SDR HF performance | Documented antenna recommendation (random wire + 9:1 unun) |
