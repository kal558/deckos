# Helpers shared by customize-image.sh and module install.sh scripts.
# Sourced, not executed. Runs inside the image chroot.

log()  { echo "[deckos] $*"; }
warn() { echo "[deckos] WARNING: $*" >&2; echo "$*" >> /etc/deckos/build-warnings.txt; }

apt_install() {
  apt-get install -y --no-install-recommends "$@"
}

# Install packages one by one, warning (not failing) on any that don't exist in
# this release. Used for optional extras.
apt_install_optional() {
  local p
  for p in "$@"; do
    apt-get install -y --no-install-recommends "$p" || warn "optional package '$p' not installed"
  done
}

# fetch URL DEST [SHA256]
fetch() {
  local url="$1" dest="$2" sha="${3:-}"
  curl -fL --retry 3 --retry-delay 5 -o "$dest" "$url"
  if [[ -n "$sha" ]]; then
    echo "$sha  $dest" | sha256sum -c - >/dev/null || { rm -f "$dest"; echo "checksum mismatch: $url" >&2; return 1; }
  fi
}

# Like fetch but a failure is recorded as a build warning instead of aborting.
fetch_optional() {
  fetch "$@" || { warn "optional download failed: $1"; return 1; }
}

# Installing systemd-resolved re-points /etc/resolv.conf at a stub that doesn't
# exist inside the build chroot. Put the build's resolver back when that happens.
ensure_dns() {
  if [[ -f /tmp/resolv.conf.build ]] && ! getent hosts deb.debian.org >/dev/null 2>&1; then
    rm -f /etc/resolv.conf
    cp /tmp/resolv.conf.build /etc/resolv.conf
  fi
}

# run_module DIR: packages.list -> files/ -> install.sh -> manifest
run_module() {
  local dir="$1" name
  name="$(basename "$dir")"
  export DECK_CURRENT_MODULE="$name"
  log "module: $name"
  ensure_dns
  if [[ -f "$dir/packages.list" ]]; then
    mapfile -t pkgs < <(grep -Ev '^\s*(#|$)' "$dir/packages.list")
    if [[ ${#pkgs[@]} -gt 0 ]]; then apt_install "${pkgs[@]}"; fi
  fi
  if [[ -f "$dir/packages-optional.list" ]]; then
    mapfile -t opt < <(grep -Ev '^\s*(#|$)' "$dir/packages-optional.list")
    if [[ ${#opt[@]} -gt 0 ]]; then apt_install_optional "${opt[@]}"; fi
  fi
  ensure_dns
  if [[ -d "$dir/files" ]]; then
    cp -a --no-preserve=ownership "$dir/files/." /
    # Executable bits don't survive a Windows checkout; set them by location.
    local f
    while IFS= read -r -d '' f; do
      chmod 0755 "/${f#"$dir/files/"}"
    done < <(find "$dir/files" -type f \( -path '*/usr/bin/*' -o -path '*/usr/sbin/*' \
      -o -path '*/usr/lib/deckos/*' -o -path '*/initramfs-tools/scripts/*' -o -path '*/dispatcher.d/*' \
      -o -path '*/profile.d/*' \) -print0)
  fi
  if [[ -f "$dir/install.sh" ]]; then
    MODULE_DIR="$dir" bash "$dir/install.sh"
  fi
  if [[ -f "$dir/manifest.toml" ]]; then
    install -m 0644 "$dir/manifest.toml" "/usr/share/deckos/apps/$name.toml"
  fi
}

# Source the board profile so install scripts can branch on it.
# (An if-block, not `[[ ]] && source`: as the last line of a sourced file, a false
# test would make `source` itself fail and stop a `set -e` caller.)
if [[ -f /etc/deckos/board.conf ]]; then
  # shellcheck disable=SC1091
  source /etc/deckos/board.conf
fi
true
