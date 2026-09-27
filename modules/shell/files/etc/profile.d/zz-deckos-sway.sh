# Start the deck desktop on tty1. If sway exits or crashes you land at a shell;
# type "sway" to start it again.
if [ "$(id -un)" = "deck" ] && [ "$(tty)" = "/dev/tty1" ] && [ -z "$WAYLAND_DISPLAY" ]; then
  export XDG_CURRENT_DESKTOP=sway
  export MOZ_ENABLE_WAYLAND=1
  export QT_QPA_PLATFORM="wayland;xcb"
  export _JAVA_AWT_WM_NONREPARENTING=1
  exec sway
fi
