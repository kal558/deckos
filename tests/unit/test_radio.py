import pytest

from deckos.radio import bands, ft8, pipelines, sat, scan, sdrlock


def test_all_shipped_band_files_load(root):
    tabs = bands.load_all()
    names = {t.tab for t in tabs}
    assert {"FM", "DAB+", "Shortwave", "MW DX", "HF voice (SSB)", "FT8", "JS8Call", "Weather fax",
            "Weather satellites", "Amateur 2m/70cm"} <= names
    # agreed scope: no airband, marine or PMR446
    for t in tabs:
        for p in t.presets:
            assert not 108e6 <= p.freq <= 137e6 or t.mode == "satellite", p
            assert not 156e6 <= p.freq <= 163e6, p
            assert not 446.0e6 <= p.freq <= 446.2e6, p
    dab = next(t for t in tabs if t.mode == "dab")
    assert all(p.channel in dab.channels for p in dab.presets)
    assert len(dab.channels) == 38


def test_band_validation():
    with pytest.raises(bands.BandError):
        bands.parse('mode="wbfm"\n[[preset]]\nname="x"\nfreq=100e3\n', "t")  # below V4 range
    with pytest.raises(bands.BandError):
        bands.parse('mode="teleport"\n', "t")
    with pytest.raises(bands.BandError):
        bands.parse('mode="app"\n', "t")
    with pytest.raises(bands.BandError):
        bands.parse('mode="am"\n[scan]\nstart=1e6\nend=0.9e6\nstep=1e3\n', "t")


def test_saved_presets_roundtrip(root):
    bands.save_preset("01-fm", bands.Preset("Found 98.8", 98.8e6))
    bands.save_preset("01-fm", bands.Preset("Radio 1", 98.8e6))  # same freq replaces
    saved = bands.saved_presets("01-fm")
    assert [p.name for p in saved] == ["Radio 1"]


def test_ssb_sideband_convention():
    assert bands.ssb_sideband(7.110e6) == "lsb"
    assert bands.ssb_sideband(14.300e6) == "usb"
    assert bands.ssb_sideband(5.357e6) == "usb"


def test_pipelines():
    p = pipelines.rtl_fm("wbfm", 98.8e6)
    assert p.source[:3] == ["rtl_fm", "-f", "98800000"] and "wbfm" in p.source and p.rate == 48000
    assert p.source[-1] == "-"
    p = pipelines.rtl_fm("auto-ssb", 7.11e6, gain=40)
    assert "lsb" in p.source and "-g" in p.source and p.rate == 12000
    assert pipelines.rtl_fm("ft8", 14.074e6).source[pipelines.rtl_fm("ft8", 14.074e6).source.index("-M") + 1] == "usb"
    assert p.player()[0] == "aplay" and "12000" in p.player()
    assert "--device=deck_sdr" in p.to_sink("deck_sdr")
    with pytest.raises(ValueError):
        pipelines.rtl_fm("dab", 1e8)


def test_find_peaks():
    # two strong signals (one spread over adjacent bins) on a -40 dB floor
    powers = [-40.0] * 40
    powers[10] = -20.0
    powers[11] = -18.0
    powers[30] = -22.0
    row = "2026-01-01, 00:00:00, 88000000, 92000000, 100000, 10, " + ", ".join(map(str, powers))
    peaks = scan.find_peaks(row)
    assert peaks == pytest.approx([89_150_000, 91_050_000])
    assert scan.find_peaks("") == []


def test_ft8_parse_decode():
    s = ft8.parse_decode("123015 -12  0.3 1234 ~  CQ G4ABC IO91", 14_074_000, 1000.0)
    assert (s.call, s.grid, s.snr, s.freq) == ("G4ABC", "IO91", -12, 14_075_234)
    assert s.lat == pytest.approx(51.5)
    s = ft8.parse_decode("123015   2 -0.1  800 ~  DL1XYZ EA4ABC IN80", 7_074_000, 1.0)
    assert s.call == "EA4ABC"
    assert ft8.parse_decode("123015 -5 0.1 900 ~  G4ABC DL1XYZ RR73", 7_074_000, 1.0) is None
    assert ft8.parse_decode("123015 -5 0.1 900 ~  G4ABC DL1XYZ -12", 7_074_000, 1.0) is None
    assert ft8.parse_decode("<DecodeFinished>   0   1        0", 7_074_000, 1.0) is None


def test_ft8_merge_keeps_newest_and_expires():
    old = {"call": "OLD1", "time": 0}
    kept = {"call": "G4ABC", "time": 9000, "snr": -20}
    new = ft8.Spot("G4ABC", "IO91", 51.5, -1.0, -5, 14.075e6, 9500.0, "CQ G4ABC IO91")
    out = ft8.merge_spots([old, kept], [new], now=10_000)
    assert [s["call"] for s in out] == ["G4ABC"] and out[0]["snr"] == -5


TLE = """METEOR-M2 3
1 57166U 23091A   25250.50000000  .00000100  00000-0  60000-4 0  9990
2 57166  98.7000 300.0000 0004000 100.0000 260.0000 14.23000000100000
NOAA 99
1 99999U 00000A   25250.50000000  .00000100  00000-0  60000-4 0  9990
2 99999  98.7000 300.0000 0004000 100.0000 260.0000 14.23000000100000
"""


def test_parse_tle():
    t = sat.parse_tle(TLE)
    assert set(t) == {57166, 99999}
    assert t[57166][0] == "METEOR-M2 3"


def test_sdr_lock_is_exclusive(root):
    assert sdrlock.owner() is None
    with sdrlock.hold("Radio"):
        assert sdrlock.owner() == "Radio"
        with pytest.raises(sdrlock.Busy) as e:
            with sdrlock.hold("FT8 monitor"):
                pass
        assert e.value.owner == "Radio"
    assert sdrlock.owner() is None
    with sdrlock.hold("FT8 monitor"):
        assert sdrlock.owner() == "FT8 monitor"
