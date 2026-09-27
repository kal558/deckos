import base64

import pytest

from deckos.mesh import policy
from deckos.mesh.meshd import Mesh
from deckos.mesh.store import BROADCAST, Store


def test_policy_defaults_are_silent_and_private(tmp_path):
    p = policy.load(tmp_path / "pol.json")
    assert p.tx_enabled is False
    assert p.share_position is False
    assert p.effective_precision == 0
    assert len(p.psk) == 32
    assert p.long_name and p.short_name
    # persisted and stable
    assert policy.load(tmp_path / "pol.json").psk_b64 == p.psk_b64
    assert oct((tmp_path / "pol.json").stat().st_mode)[-3:] == "600"


def test_policy_random_names_differ():
    names = {policy.random_node_name()[0] for _ in range(20)}
    assert len(names) > 1


def _dev(pol, **over):
    base = dict(tx_enabled=pol.tx_enabled, role=pol.role, channel_name=pol.channel_name, psk=pol.psk,
                position_precision=pol.effective_precision, smart_position=False,
                long_name=pol.long_name, short_name=pol.short_name, secondary_channels=())
    base.update(over)
    return policy.DeviceConfig(**base)


def test_diff_nothing_to_do():
    pol = policy.Policy()
    assert policy.diff(pol, _dev(pol)) == []


def test_diff_factory_fresh_node_disables_tx_first():
    pol = policy.Policy()
    fresh = _dev(pol, tx_enabled=True, channel_name="", psk=b"\x01", position_precision=32,
                 smart_position=True, long_name="Meshtastic 1234", short_name="1234", secondary_channels=(1, 2),
                 role="ROUTER")
    acts = policy.diff(pol, fresh)
    assert acts[0] == ("lora_tx", False)
    kinds = [a[0] for a in acts]
    assert kinds.count("delete_channel") == 2
    assert ("primary_channel", pol.channel_name, pol.psk, 0) in acts
    assert ("role", "CLIENT") in acts and ("smart_position", False) in acts
    assert ("owner", pol.long_name, pol.short_name) in acts


def test_diff_enabling_tx_happens_last():
    pol = policy.Policy(tx_enabled=True, share_position=True, precision_bits=15)
    acts = policy.diff(pol, _dev(pol, tx_enabled=False, position_precision=0))
    assert acts[-1] == ("lora_tx", True)
    assert ("primary_channel", pol.channel_name, pol.psk, 15) in acts


def test_store_conversations_and_unread():
    s = Store(":memory:")
    me = "!0000aaaa"
    assert s.add_message(from_id="!b", to_id=BROADCAST, text="hello all", packet_id=1)
    assert not s.add_message(from_id="!b", to_id=BROADCAST, text="hello all", packet_id=1)  # duplicate
    s.add_message(from_id="!c", to_id=me, text="just you", packet_id=2, ts=1000.0)
    s.add_message(from_id=me, to_id="!c", text="reply", direction="out", ts=1001.0)
    convs = {c["peer"]: c for c in s.conversations(me)}
    assert set(convs) == {"#0", "!c"}
    assert convs["#0"]["unread"] == 1 and convs["!c"]["unread"] == 1
    assert [m["text"] for m in s.messages("!c", me)] == ["just you", "reply"]
    s.mark_read("!c", me)
    assert s.unread_count() == 1
    assert s.search("reply")[0]["text"] == "reply"


def test_store_nodes_and_waypoints():
    s = Store(":memory:")
    s.upsert_node("!b", long_name="Bob", lat=51.5, lon=-0.1)
    s.upsert_node("!b", snr=4.5)  # partial update keeps name/position
    n = s.nodes()[0]
    assert (n["long_name"], n["lat"], n["snr"]) == ("Bob", 51.5, 4.5)
    wid = s.add_waypoint("Water", 51.0, -1.0, "spring")
    assert s.waypoints()[0]["name"] == "Water"
    s.delete_waypoint(wid)
    assert s.waypoints() == []


@pytest.fixture
def mesh(tmp_path, root):
    return Mesh(Store(":memory:"), tmp_path / "policy.json")


def test_meshd_refuses_to_send_when_receive_only(mesh):
    mesh.iface = object()  # pretend a node is connected
    with pytest.raises(RuntimeError, match="receive-only"):
        mesh.handle({"cmd": "send", "text": "hi"})


def test_meshd_status_offline(mesh):
    st = mesh.handle({"cmd": "status"})
    assert st["connected"] is False and st["tx_enabled"] is False


def test_meshd_channel_key_validation(mesh):
    with pytest.raises(ValueError, match="base64"):
        mesh.handle({"cmd": "set_channel", "name": "x", "psk_b64": "not base64!!"})
    with pytest.raises(ValueError, match="16 or 32"):
        mesh.handle({"cmd": "set_channel", "name": "x", "psk_b64": base64.b64encode(b"short").decode()})
    key = base64.b64encode(bytes(16)).decode()
    mesh.handle({"cmd": "set_channel", "name": "group-channel-too-long", "psk_b64": key})
    assert mesh.policy.channel_name == "group-chann"  # Meshtastic's 11-char limit


def test_meshd_receive_text_and_waypoint(mesh):
    mesh.me = "!00000001"
    mesh._on_receive({"from": 2, "to": 0xFFFFFFFF, "id": 7, "rxSnr": 3.0,
                      "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hi"}})
    mesh._on_receive({"from": 2, "to": 0xFFFFFFFF, "id": 8,
                      "decoded": {"portnum": "WAYPOINT_APP",
                                  "waypoint": {"name": "Cache", "latitudeI": 515000000, "longitudeI": -1000000}}})
    assert mesh.store.messages("#0", mesh.me)[0]["from_id"] == "!00000002"
    wp = mesh.store.waypoints()[0]
    assert (wp["name"], wp["lat"], wp["lon"]) == ("Cache", 51.5, -0.1)
