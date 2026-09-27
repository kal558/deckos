from pathlib import Path

import pytest

from deckos.library import catalog, kiwix_opds, store

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "src/deckos/library/catalog.toml"


def test_shipped_catalog_is_valid_and_fits_a_256gb_ssd():
    items = catalog.parse(CATALOG.read_text())
    ids = {i.id for i in items}
    assert {"wikipedia", "wikimed", "ifixit", "map-uk", "places", "routing"} <= ids
    wiki = next(i for i in items if i.id == "wikipedia")
    assert wiki.name == "wikipedia_en_all_nopic" and wiki.default
    maxi = next(i for i in items if i.id == "wikipedia-maxi")
    assert not maxi.default and maxi.replaces == "wikipedia"
    total = catalog.total_default_gb(items)
    assert 80 < total < 140, total  # the agreed ~105 GB, leaving room on 256 GB
    for i in items:
        if i.kind == "pmtiles":
            minlon, minlat, maxlon, maxlat = i.bbox
            assert minlon < maxlon and minlat < maxlat


@pytest.mark.parametrize("bad", [
    '[[item]]\nid="x"\ntitle="X"\nkind="nope"\n',
    '[[item]]\nid="x"\ntitle="X"\nkind="zim"\n',
    '[[item]]\nid="x"\ntitle="X"\nkind="pmtiles"\nbbox=[1,2]\n',
    '[[item]]\nid="x"\ntitle="X"\nkind="zim"\nname="a"\n[[item]]\nid="x"\ntitle="Y"\nkind="zim"\nname="b"\n',
])
def test_catalog_rejects_bad_items(bad):
    with pytest.raises(ValueError):
        catalog.parse(bad)


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Wikipedia</title><name>wikipedia_en_all_nopic</name><updated>2025-06-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="55000000000"
      href="https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2025-06.zim.meta4"/>
  </entry>
  <entry>
    <title>Wikipedia</title><name>wikipedia_en_all_nopic</name><updated>2025-09-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="56000000000"
      href="https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2025-09.zim.meta4"/>
  </entry>
  <entry>
    <title>Other</title><name>wikipedia_en_all_maxi</name><updated>2026-01-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access" href="https://x/wikipedia_en_all_maxi_2026-01.zim.meta4"/>
  </entry>
</feed>"""


def test_opds_picks_newest_exact_match():
    b = kiwix_opds.parse_feed(FEED, "wikipedia_en_all_nopic")
    assert b.updated.startswith("2025-09")
    assert b.filename == "wikipedia_en_all_nopic_2025-09.zim"
    assert b.zim_url.endswith(".zim") and b.meta4_url.endswith(".meta4")
    assert b.size_bytes == 56000000000
    assert kiwix_opds.parse_feed(FEED, "nothing_here") is None


def test_zim_filenames_and_superseded(tmp_path):
    assert store.parse_zim_filename("ifixit_en_all_2025-03.zim") == ("ifixit_en_all", "2025-03")
    assert store.parse_zim_filename("random.zim") is None
    for n in ("ifixit_en_all_2025-03.zim", "ifixit_en_all_2025-07.zim", "wikivoyage_en_all_maxi_2025-01.zim"):
        (tmp_path / n).write_bytes(b"x")
    inst = store.installed_zims(tmp_path)
    assert inst["ifixit_en_all"].date == "2025-07"
    assert [p.name for p in store.superseded_zims(tmp_path)] == ["ifixit_en_all_2025-03.zim"]


def test_age_months():
    i = store.Installed(Path("x"), "x", "2025-01", 1, 0)
    import time

    now = time.mktime((2025, 7, 15, 0, 0, 0, 0, 0, 0))
    assert i.age_months(now) == 6
    assert store.Installed(Path("x"), "x", "", 1, 0).age_months() is None
