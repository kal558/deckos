import pytest

from deckos import board, clock, power


def test_estimate():
    e = power.estimate(capacity_wh=74, used_wh=0, draw_w=6.0)
    assert e.remaining_wh == pytest.approx(62.9)
    assert e.hours_left == pytest.approx(10.48, abs=0.01)
    assert e.percent == 100
    assert power.estimate(74, 100, 6.0).hours_left == 0  # never negative
    assert power.estimate(None, 0, 6.0) is None
    assert power.estimate(74, 0, 0) is None


def test_accumulate_caps_gaps():
    st = power.accumulate({"used_wh": 0.0, "last_tick": None}, 6.0, now=1000.0)
    assert st["used_wh"] == 0.0 and st["last_tick"] == 1000.0
    st = power.accumulate(st, 6.0, now=1000.0 + 3600)  # an hour-long gap only counts 10 min
    assert st["used_wh"] == pytest.approx(1.0)
    st = power.accumulate(st, 6.0, now=st["last_tick"] + 30)
    assert st["used_wh"] == pytest.approx(1.05)


def test_thermal_action():
    assert power.thermal_action(60000, 75000, 80000, "normal") is None
    assert power.thermal_action(76000, 75000, 80000, "normal") == "warn"
    assert power.thermal_action(81000, 75000, 80000, "normal") == "field"
    assert power.thermal_action(81000, 75000, 80000, "field") == "warn"


def test_draw_for_uses_board_profile():
    b = board.Board({"DRAW_W_FIELD": "3.5"})
    assert power.draw_for(b, "field") == 3.5
    assert power.draw_for(b, "normal") == 6.0  # default


def test_cpu_temp_takes_hottest_zone(root):
    for i, t in enumerate(("45000", "61000", "bad")):
        z = root / f"sys/class/thermal/thermal_zone{i}"
        z.mkdir(parents=True)
        (z / "temp").write_text(t)
    assert power.cpu_temp_mc() == 61000


def test_clock_never_goes_backwards(tmp_path):
    a = tmp_path / "a"
    a.write_text("2000000000")
    b = tmp_path / "b"
    b.write_text("junk")
    saved = clock.newest_saved([a, b, tmp_path / "missing"])
    assert saved == 2000000000
    assert clock.restore_target(now=100, saved=saved) == saved
    assert clock.restore_target(now=3000000000, saved=saved) is None
