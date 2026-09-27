# Building deckOS

The build runs the [Armbian build framework](https://github.com/armbian/build) on Linux. On
Windows that means **WSL2**. Alternatively, let **GitHub Actions** build it in the cloud.

## Option A: build on your Windows PC (WSL2)

You need about 60 GB of free disk space and 2–4 hours for the first build (later builds are faster).

1. **Install WSL2 with Ubuntu 24.04.** In PowerShell *as Administrator*:
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
   Reboot when asked, then open "Ubuntu" from the Start menu and create a Linux user.

2. **Put the project inside Linux** (building from `/mnt/c/...` is slow and breaks permissions):
   ```bash
   sudo apt update && sudo apt install -y git
   git clone /mnt/c/Users/<you>/Claude/deckos ~/deckos
   cd ~/deckos
   ```

3. **Build:**
   ```bash
   ./build.sh --board zero3w        # or: --board rpi
   ```
   Armbian installs what it needs (it asks for your sudo password). The image lands in
   `output/deckos-zero3w-<version>.img.xz`, with a `BUILDINFO` file recording exactly what was built.

4. **Flash** the `.img.xz` to a microSD card with [balenaEtcher](https://etcher.balena.io/) or
   Raspberry Pi Imager. The image is visible from Windows at `\\wsl$\Ubuntu-24.04\home\<you>\deckos\output\`.

## Option B: build on GitHub (no Linux needed)

1. Create a **private** GitHub repository and push this project to it.
2. Open **Actions → Build deckOS image → Run workflow**, then choose the board.
3. After 1–3 hours, download the image from the run's **Artifacts**.

The workflow also runs the unit tests and the image smoke test.

## Tests

```bash
python3 -m pip install pytest
python3 -m pytest                               # unit tests (any Linux or WSL)
sudo tests/image/smoke.sh output/deckos-*.img.xz      # boots the image in a container
sudo tests/image/privacy.sh output/deckos-*.img.xz 60 # 60 min idle capture: must send nothing
```
The image tests need `systemd-container`, `qemu-user-static` (on x86 hosts), `tcpdump` and
`dnsmasq`.

## Customising

- **Leave features out:** delete lines from `MODULES` in `deckos.conf`.
- **Reproducible builds:** set `ARMBIAN_REF` in `deckos.conf` to an Armbian release tag.
- **Library content:** edit `src/deckos/library/catalog.toml`, or put an override at `/etc/deckos/catalog.toml`.
- **Radio presets:** `src/deckos/radio/bands/*.toml`. Adding a band is a one-file change.
- **Keyboard layout:** `xkb_layout` in `modules/shell/files/etc/sway/config` (default `gb`).

## Kernel fallback (video decoding)

The Zero 3W uses the mainline kernel by default. If `deck-selftest` reports that HEVC (H.265) video
isn't hardware-decoded and you need it, rebuild with Radxa's vendor kernel:
```bash
./build.sh --board zero3w --kernel vendor
```
Nothing else changes.

## First-build checklist

Nobody has built this image yet. These parts depend on outside sources, so watch them on the first build:

| Item | Where | If it fails |
|---|---|---|
| Debian package names on trixie | `modules/*/packages.list` | The build stops and names the package. Fix the name or move it to `packages-optional.list`. |
| tvheadend repository | `modules/tv/install.sh` | Recorded in `/etc/deckos/build-warnings.txt`; TV won't work. Check the tvheadend site for the current apt repo. |
| SDR++, SatDump, ES-DE, pmtiles | GitHub/GitLab release downloads | Optional: a warning is logged. The radio falls back to gqrx and games fall back to RetroArch. |
| libretro cores | buildbot.libretro.com | Optional per core |
| DVB firmware | LibreELEC dvb-firmware | Optional per file |
| Map web libraries | jsDelivr (`maplibre-gl@5`, `pmtiles@4`, `@protomaps/basemaps@5`) | The build stops. Check the versions and paths in `modules/maps/install.sh`. |

After the first boot on real hardware, run **Self-test** from the home screen.

## Recovery / maintenance mode

The system root is read-only. To boot it writable (for example to fix a config file by hand):
- **Zero 3W (Armbian):** put the SD card in another computer and add `extraargs=deckos.rw=1` to
  `/boot/armbianEnv.txt`. Remove the line again afterwards.
- **Raspberry Pi:** add ` deckos.rw=1` to the end of the single line in `cmdline.txt` on the boot partition.
