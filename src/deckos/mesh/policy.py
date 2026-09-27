"""EMCON policy for the Meshtastic node and the diff against the device's config.

The policy lives in personal storage and is re-applied every time the node
connects, so a factory-reset or reflashed node can never silently transmit on the
public channel.
"""
from __future__ import annotations

import base64
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Meshtastic channel position_precision is a number of significant bits.
# 32 = exact; 0 = never send position on this channel.
# 14 bits ~= 1.5 km, 15 ~= 730 m, 13 ~= 2.9 km.
DEFAULT_PRECISION_BITS = 14
PRECISION_CHOICES = {
    0: "Off",
    13: "~3 km",
    14: "~1.5 km",
    15: "~700 m",
    16: "~350 m",
    32: "Exact",
}

_ADJ = ["amber", "quiet", "grey", "north", "stone", "moss", "iron", "fern", "slate", "ash"]
_NOUN = ["fox", "heron", "otter", "wren", "hare", "owl", "pine", "brook", "vale", "tor"]


def random_node_name() -> tuple[str, str]:
    long = f"{secrets.choice(_ADJ)}-{secrets.choice(_NOUN)}-{secrets.randbelow(900) + 100}"
    short = secrets.token_hex(2)
    return long, short


@dataclass
class Policy:
    tx_enabled: bool = False
    share_position: bool = False
    precision_bits: int = DEFAULT_PRECISION_BITS
    channel_name: str = "deck"
    psk_b64: str = field(default_factory=lambda: base64.b64encode(secrets.token_bytes(32)).decode())
    long_name: str = ""
    short_name: str = ""
    role: str = "CLIENT"

    def __post_init__(self) -> None:
        if not self.long_name or not self.short_name:
            self.long_name, self.short_name = random_node_name()

    @property
    def psk(self) -> bytes:
        return base64.b64decode(self.psk_b64)

    @property
    def effective_precision(self) -> int:
        return self.precision_bits if self.share_position else 0


def load(path: Path) -> Policy:
    try:
        data = json.loads(path.read_text())
        known = {k: v for k, v in data.items() if k in Policy.__dataclass_fields__}
        return Policy(**known)
    except (OSError, ValueError, TypeError):
        pol = Policy()
        save(path, pol)
        return pol


def save(path: Path, pol: Policy) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(pol), indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)


@dataclass(frozen=True)
class DeviceConfig:
    """The subset of node config meshd controls, read from the device."""
    tx_enabled: bool
    role: str
    channel_name: str
    psk: bytes
    position_precision: int
    smart_position: bool
    long_name: str
    short_name: str
    secondary_channels: tuple[int, ...] = ()


def diff(pol: Policy, dev: DeviceConfig) -> list[tuple]:
    """Actions needed to bring the device in line with the policy.

    Order matters: disabling TX first means nothing is sent on a public channel
    while the rest is being fixed.
    """
    actions: list[tuple] = []
    if dev.tx_enabled != pol.tx_enabled and not pol.tx_enabled:
        actions.append(("lora_tx", False))
    for idx in dev.secondary_channels:
        actions.append(("delete_channel", idx))
    if (dev.channel_name, dev.psk, dev.position_precision) != (pol.channel_name, pol.psk, pol.effective_precision):
        actions.append(("primary_channel", pol.channel_name, pol.psk, pol.effective_precision))
    if dev.role != pol.role:
        actions.append(("role", pol.role))
    if dev.smart_position:
        actions.append(("smart_position", False))
    if (dev.long_name, dev.short_name) != (pol.long_name, pol.short_name):
        actions.append(("owner", pol.long_name, pol.short_name))
    if dev.tx_enabled != pol.tx_enabled and pol.tx_enabled:
        actions.append(("lora_tx", True))
    return actions
