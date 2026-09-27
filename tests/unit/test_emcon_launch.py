from deckos import emcon, launch, manifest


def _rfkill(root, n, kind, soft, hard="0"):
    d = root / "sys/class/rfkill" / f"rfkill{n}"
    d.mkdir(parents=True)
    (d / "type").write_text(kind + "\n")
    (d / "soft").write_text(soft + "\n")
    (d / "hard").write_text(hard + "\n")


def test_summarize():
    assert emcon.summarize(emcon.State()) == ("SILENT", "silent")
    assert emcon.summarize(emcon.State(wifi=True, mesh=True)) == ("TX: WiFi, Mesh", "transmitting")
    # Tor on its own isn't a transmitter
    assert emcon.summarize(emcon.State(tor=True))[0] == "SILENT"


def test_rfkill_state(root):
    assert emcon.rfkill_state("wlan") is None
    _rfkill(root, 0, "wlan", "1")
    _rfkill(root, 1, "bluetooth", "0")
    _rfkill(root, 2, "bluetooth", "0", hard="1")
    assert emcon.rfkill_state("wlan") is False
    assert emcon.rfkill_state("bluetooth") is True  # one unblocked device is enough


def test_read_state_without_meshd(root):
    _rfkill(root, 0, "wlan", "0")
    st = emcon.read_state()
    assert st.wifi and not st.bluetooth and not st.mesh and not st.mesh_connected


def _app(i, heavy):
    return manifest.App(id=i, name=i.title(), command=(i,), heavy=heavy)


def test_heavy_rule():
    heavy_ids = {"firefox", "office", "kodi"}
    running = {"firefox": 100, "radio": 200}
    assert launch.must_close(_app("office", True), running, heavy_ids, low_memory=True) == ["firefox"]
    assert launch.must_close(_app("office", True), running, heavy_ids, low_memory=False) == []
    assert launch.must_close(_app("notes", False), running, heavy_ids, low_memory=True) == []
    assert launch.must_close(_app("firefox", True), running, heavy_ids, low_memory=True) == []


def test_pgid_alive_reads_proc(tmp_path):
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    # field 5 (pgrp) = 40; comm contains spaces and a paren
    (proc / "42/stat").write_text("42 (my app) x) S 1 40 40 0 -1")
    (proc / "43").mkdir()
    (proc / "43/stat").write_text("43 (zombie) Z 1 50 50 0 -1")
    assert launch.pgid_alive(40, proc)
    assert not launch.pgid_alive(50, proc)  # zombies don't count
    assert not launch.pgid_alive(99, proc)


def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    launch.save_registry({"a": 10, "b": 20})
    assert launch.load_registry(alive=lambda pg: pg == 20) == {"b": 20}
