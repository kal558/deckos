# deckOS user guide

## First boot

1. Plug in the screen, keyboard, hub and **the SSD** (optional but recommended), then power on.
2. First-boot setup asks for:
   - a **password** (for admin tasks and the screen lock)
   - a **passphrase** for encrypted personal storage. You'll type it **at every boot**.
     If you forget it, your personal data is gone for good.
   - your power bank's capacity in Wh (optional: 20,000 mAh ≈ 74 Wh)
3. If the SSD is attached, it gets an encrypted personal folder protected by the same passphrase.
   (To set up a *new, empty* SSD, use **Settings → Storage → Erase and set up**.)
4. The deck locks the system files, reboots, asks for your passphrase, and starts.

**Skipping the passphrase at boot:** press Enter three times (or wait). The deck still starts with
the library, maps, radio and media, but messages, notes, keys and settings stay locked and
nothing personal is saved.

## Getting the library

1. **⊞+E** → turn on **Wi-Fi** → Settings → Radios → *Choose network…*
2. Open **Library** → the recommended items are pre-ticked → **Download selected**.
   Downloads resume if interrupted and are checksum-verified.
3. **Place search and routing** are built on a PC (much faster than on the deck). On the PC, run
   `tools/build-map-data.sh uk`, then copy `places.sqlite` and `routino.tar` to
   `/deck/library/staging/` and press **Import from staging folder**.
   The **PC import share** (Library app) lets you copy files over Wi-Fi: from Windows, open
   `\\<deck-ip>\deck`. It switches off at reboot.
4. **⊞+Shift+E** to go silent again.

## Keys

| Key | Fallback | |
|---|---|---|
| ⊞ (tap) | Ctrl+Alt+Space | Home |
| ⊞+Space | Ctrl+Alt+S | Search everything |
| ⊞+Tab | Alt+Tab | Next app |
| ⊞+Q | Ctrl+Alt+Q | Close app |
| ⊞+Esc | Ctrl+Alt+Del | Power menu (lock, standby, reboot, shut down) |
| ⊞+E | Ctrl+Alt+E | Emissions control |
| ⊞+Shift+E | Ctrl+Alt+Shift+E | **Go silent** |
| ⊞+D | Ctrl+Alt+D | Day/night theme |
| ⊞+Enter | Ctrl+Alt+T | Terminal |
| ⊞+L | | Lock |
| F1 / ⊞+F1 | | Key cheat sheet |

On the home screen, **just start typing** to search.

## Emissions control (EMCON)

The status bar always shows **SILENT** (green) or **TX: …** (red).
- **Wi-Fi and Bluetooth** are switched off at every boot. Turn them on in ⊞+E or Settings → Radios.
- **Mesh** starts receive-only: you read messages without transmitting. Turn on *Mesh transmit* to reply.
- Radio, TV, GPS and the SDR only ever receive.
- **Tor mode** (⊞+E) sends all internet traffic through Tor and blocks anything that can't use it.
- Encryption hides *what* you send, not *that* you're transmitting. An active transmitter can
  be located by direction-finding.

## Mesh (Meshtastic)

When a node is plugged in, the deck automatically: switches it to receive-only, replaces the public
channel with a **private channel and random key**, turns off position sharing, and gives it a
random name. It re-applies these rules every time the node connects.

To talk to your group, everyone needs the **same channel name and key**. Mesh → *Channel key…*
shows it; share it **in person**. *Share position* offers blurred precisions (~3 km, ~1.5 km, ~700 m)
or exact.

## Radio

Pick a tab on the left (FM, DAB+, Shortwave, amateur, MW DX, HF voice, FT8, JS8Call, Weather fax,
Weather satellites), then a preset. **Scan** finds stations and saves them. *SDR++ (advanced)*
opens the full receiver. Only one app can use the SDR at a time; the Radio tile shows which one has it.
- **HF (shortwave, FT8, weather fax):** attach the long-wire antenna. Evenings are best.
- **FT8** spots appear on the map (Maps → *FT8 spots*), which shows which bands are open right now.
- **Weather satellites:** *Update orbit data* (online, occasionally), then *Show passes*, then *Record next …*.
  Images land in Media → Weather satellites.

## TV

Plug in the tuner and open **TV setup** once: choose *DVB-T* → your nearest transmitter (for example
`uk-CrystalPalace`) → scan. After that, the **TV** tile opens live TV with the guide. Recordings go to
Media → TV recordings.

## Power

- **Settings → Power:** profile (Field / Normal / Performance), power-bank capacity, and
  *I just charged* (resets the estimate).
- The status bar shows the profile, an estimated runtime, and **LOW V** if the supply is too weak.
- Standby (⊞+Esc → Standby) turns the screen off and slows the CPU; **mesh messages still arrive**.
- If the deck gets hot it warns you, then switches to Field automatically.

## Memory (2 GB boards)

Firefox, LibreOffice, Kodi (TV/Media) and Games are "heavy". Only one runs at a time. Opening
another asks to close the first (your work gets the usual save prompt). Everything else runs alongside.

## Updates and backups

- Nothing updates by itself. **Settings → Updates → Check** (online), then **Apply**, then reboot.
- Personal storage is backed up (encrypted) to the SSD at **every shutdown**. After flashing a new
  image, first-boot setup offers to restore it.

## Factory reset

Settings → System → Factory reset erases personal storage for good and re-runs first-boot setup.
Library, maps, media and games on the SSD are kept.

## Troubleshooting

- **Something's wrong:** Home → **Self-test**.
- **A tile is greyed out:** its hardware isn't plugged in (the tile says which).
- **The desktop crashed:** ⊞+Enter opens a terminal. Type `sway` from a text console to restart the desktop.
