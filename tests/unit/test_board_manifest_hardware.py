from pathlib import Path

import pytest

from deckos import board, hardware, manifest

REPO = Path(__file__).resolve().parents[2]


def test_parse_shell_conf_handles_quotes_comments_and_junk():
    conf = board.parse_shell_conf(
        '# comment\nA="x y"\nB=1200000 # trailing\n\nC=\nbad line\n1X=nope\nD=\'q\'\n'
    )
    assert conf == {"A": "x y", "B": "1200000", "C": "", "D": "q"}


@pytest.mark.parametrize("name", ["radxa-zero3w.conf", "rpi4-5.conf"])
def test_real_board_profiles_have_required_keys(name):
    b = board.load(REPO / "boards" / name)
    for key in ("DECK_BOARD_ID", "ARMBIAN_BOARD", "ARMBIAN_BRANCH", "THERMAL_WARN", "THERMAL_FIELD",
                "DRAW_W_FIELD", "DRAW_W_NORMAL", "DRAW_W_PERFORMANCE", "BROWNOUT_METHOD"):
        assert b.get(key), f"{name} missing {key}"
    assert b.get_int("THERMAL_FIELD") > b.get_int("THERMAL_WARN")
    assert b.get_float("DRAW_W_FIELD", 0) < b.get_float("DRAW_W_PERFORMANCE", 0)


def test_low_memory_detection(tmp_path):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal:        2014208 kB\nMemFree: 1 kB\n")
    assert board.is_low_memory(mi)
    mi.write_text("MemTotal:        3884000 kB\n")
    assert not board.is_low_memory(mi)
    assert board.is_low_memory(tmp_path / "missing")  # unknown -> be conservative


def test_manifest_parse_and_validation():
    apps = manifest.parse('[[app]]\nid="a"\nname="A"\ncommand=["x","--y"]\nheavy=true\nrequires=["ssd"]\norder=5\n', "m")
    assert apps[0].command == ("x", "--y") and apps[0].heavy and apps[0].requires == ("ssd",)
    with pytest.raises(manifest.ManifestError):
        manifest.parse('[[app]]\nid="a"\nname="A"\ncommand="x"\n', "m")
    with pytest.raises(manifest.ManifestError):
        manifest.parse('[[app]]\nid="a"\ncommand=["x"]\n', "m")


def test_every_module_manifest_is_valid_and_ids_unique():
    ids = []
    for f in sorted((REPO / "modules").glob("*/manifest.toml")):
        for app in manifest.parse(f.read_text(), f.parent.name):
            ids.append(app.id)
            for r in app.requires:
                assert r in hardware.LABELS, f"{app.id}: unknown hardware {r}"
    assert len(ids) == len(set(ids)), "duplicate app ids across modules"
    for needed in ("wikipedia", "maps", "radio", "mesh", "tv", "media", "games", "office", "browser", "settings",
                   "library", "emcon"):
        assert needed in ids


def test_load_all_skips_broken_manifest(tmp_path):
    (tmp_path / "good.toml").write_text('[[app]]\nid="g"\nname="G"\ncommand=["g"]\norder=2\n')
    (tmp_path / "bad.toml").write_text("not toml [[[")
    (tmp_path / "early.toml").write_text('[[app]]\nid="e"\nname="E"\ncommand=["e"]\norder=1\n')
    assert [a.id for a in manifest.load_all(tmp_path)] == ["e", "g"]


def _usb(root: Path, name: str, vid: str, pid: str) -> None:
    d = root / "sys/bus/usb/devices" / name
    d.mkdir(parents=True)
    (d / "idVendor").write_text(vid + "\n")
    (d / "idProduct").write_text(pid + "\n")


def test_hardware_detect(root):
    _usb(root, "1-1", "0bda", "2838")   # RTL-SDR
    _usb(root, "1-2", "303a", "1001")   # Heltec V3
    _usb(root, "1-3", "1546", "01a8")   # u-blox
    (root / "dev/dvb/adapter0").mkdir(parents=True)
    (root / "deck").mkdir()
    hw = hardware.detect()
    assert hw == {"ssd": True, "persist": False, "sdr": True, "dvb": True, "mesh": True, "gps": True}
    assert hardware.missing(("ssd", "persist"), hw) == ["persist"]


def test_hardware_detect_nothing(root):
    hw = hardware.detect()
    assert not any(hw.values())
