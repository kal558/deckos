import pytest

from deckos import geo
from deckos.maps import mapd, places


def test_haversine_london_paris():
    assert geo.haversine_m(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(343_500, rel=0.01)


def test_bbox_around_contains_circle():
    min_lat, min_lon, max_lat, max_lon = geo.bbox_around(51.5, -0.1, 10_000)
    assert geo.haversine_m(51.5, -0.1, max_lat, -0.1) == pytest.approx(10_000, rel=0.01)
    assert geo.haversine_m(51.5, -0.1, 51.5, max_lon) == pytest.approx(10_000, rel=0.01)
    assert min_lat < 51.5 < max_lat and min_lon < -0.1 < max_lon


@pytest.mark.parametrize("grid,lat,lon", [
    ("IO91", 51.5, -1.0),
    ("IO91wm", 51.52, -0.125),
    ("JN58", 48.5, 11.0),
    ("io91WM", 51.52, -0.125),
])
def test_maidenhead(grid, lat, lon):
    got = geo.maidenhead_to_latlon(grid)
    assert got == pytest.approx((lat, lon), abs=0.03)


@pytest.mark.parametrize("bad", ["", "IO9", "ZZ99", "IO91zz", "IOAB"])
def test_maidenhead_rejects(bad):
    with pytest.raises(ValueError):
        geo.maidenhead_to_latlon(bad)


def test_decode_polyline_precision5_reference():
    # Google's documented example
    pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert pts == pytest.approx([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])


def _features():
    return [
        places.Feature("London", "city", 51.507, -0.128, 100, "", "London"),
        places.Feature("Londonderry", "city", 54.997, -7.309, 100),
        places.Feature("London Road", "road", 51.40, -0.30, 25, "Kingston"),
        places.Feature("SW1A 1AA", "postcode", 51.501, -0.142, 70),
        places.Feature("Big Ben", "landmark", 51.5007, -0.1246, 30, "", "Big Ben"),
        places.Feature("Tower of London", "landmark", 51.5081, -0.0759, 30, "", "Tower of London"),
        places.Feature("Stonehenge", "landmark", 51.1789, -1.8262, 30, "", "Stonehenge"),
        places.Feature("Zürich", "city", 47.37, 8.54, 100),
    ]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "places.sqlite"
    assert places.build_index(p, _features()) == 8
    conn = places.open_db(p, readonly=True)
    yield conn
    conn.close()


def test_search_prefix_and_rank(db):
    res = [r["name"] for r in places.search(db, "lond")]
    assert set(res) >= {"London", "Londonderry", "London Road", "Tower of London"}
    # cities outrank roads and landmarks
    assert set(res[:2]) == {"London", "Londonderry"}


def test_search_multiword_postcode_and_diacritics(db):
    assert places.search(db, "sw1a 1aa")[0]["name"] == "SW1A 1AA"
    assert places.search(db, "zurich")[0]["name"] == "Zürich"
    assert places.search(db, '"') == []


def test_search_near_prefers_nearby(db):
    res = places.search(db, "london", near=(55.0, -7.3))
    assert res[0]["name"] == "Londonderry"


def test_nearby_wikipedia(db):
    res = places.nearby_wikipedia(db, 51.5007, -0.1246, radius_m=5_000)
    names = [r["name"] for r in res]
    assert names[0] == "Big Ben"
    assert "Stonehenge" not in names
    assert all(r["distance_m"] <= 5_000 for r in res)


def test_classify_and_wiki_title():
    assert places.classify({"place": "town"}) == ("town", 85)
    assert places.classify({"amenity": "drinking_water"}) == ("amenity=drinking_water", places.RANK_POI)
    assert places.classify({"highway": "residential"}) == ("road", places.RANK_ROAD)
    assert places.classify({"building": "yes"}) is None
    assert places.wiki_title({"wikipedia": "en:Big Ben"}) == "Big Ben"
    assert places.wiki_title({"wikipedia": "de:Berlin"}) is None


ROUTINO_OUT = (
    "# Creator : Routino - http://www.routino.org/\n"
    "# Latitude\tLongitude\tSection \tSection \tTotal   \tTotal   \tPoint\tSegment\tSegment\tHighway\n"
    "#        \t         \tDistance\tDuration\tDistance\tDuration\tType \tSpeed  \tBearing\t\n"
    "#\n"
    " 51.524677\t -0.127896\t0.000 km\t 0.0 min\t  0.0 km\t   0 min\tWaypt\t       \t       \t\n"
    " 51.523830\t -0.126955\t0.114 km\t 0.2 min\t  0.1 km\t   0 min\tJunct\t 48 km/h\t 142\tEuston Road\n"
    " 51.522900\t -0.125800\t0.130 km\t 0.3 min\t  0.2 km\t   1 min\tJunct\t 48 km/h\t 140\tEuston Road\n"
    " 51.521000\t -0.124000\t0.250 km\t 0.5 min\t  0.5 km\t   1 min\tWaypt\t 30 km/h\t 150\tGower Street\n"
)


def test_parse_routino_text_all():
    r = mapd.parse_routino_text_all(ROUTINO_OUT)
    assert r["geometry"]["coordinates"][0] == [-0.127896, 51.524677]
    assert len(r["geometry"]["coordinates"]) == 4
    assert r["km"] == 0.5 and r["minutes"] == 1
    assert [s["text"] for s in r["steps"]] == ["Follow Euston Road", "Follow Gower Street"]
    assert sum(s["km"] for s in r["steps"]) == pytest.approx(0.5)


def test_parse_routino_no_route():
    with pytest.raises(ValueError):
        mapd.parse_routino_text_all("# header only\n")


@pytest.mark.parametrize("header,size,expected", [
    (None, 100, None),
    ("bytes=0-9", 100, (0, 9)),
    ("bytes=90-", 100, (90, 99)),
    ("bytes=-10", 100, (90, 99)),
    ("bytes=50-500", 100, (50, 99)),
    ("bytes=200-300", 100, None),
    ("bytes=5-1", 100, None),
    ("items=0-1", 100, None),
    ("bytes=-", 100, None),
])
def test_parse_range(header, size, expected):
    assert mapd.parse_range(header, size) == expected
