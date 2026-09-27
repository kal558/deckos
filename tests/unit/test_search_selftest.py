import time

from deckos import manifest, search, selftest

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Water purification</title><link>/content/wikipedia_en_all_nopic_2025-09/Water_purification</link>
    <description>Water purification is the process of removing  undesirable chemicals…</description>
    <book><title>Wikipedia</title></book></item>
  <item><title>Boiling water</title><link>/content/zimgit-water_en_2024-01/boil.html</link>
    <book><title>Water treatment</title></book></item>
  <item><title></title><link>/x</link></item>
</channel></rss>"""


def test_parse_kiwix_rss():
    res = search.parse_kiwix_rss(RSS)
    assert [r.title for r in res] == ["Water purification", "Boiling water"]
    assert res[0].source == "Wikipedia"
    assert res[0].command == ("deck-reader", "--url",
                              "http://127.0.0.1:8080/content/wikipedia_en_all_nopic_2025-09/Water_purification")
    assert "  " not in res[0].subtitle


def test_search_apps():
    apps = [manifest.App("radio", "Radio", ("deck-radio",), description="FM, DAB+"),
            manifest.App("mesh", "Mesh", ("deck-mesh",))]
    assert [r.title for r in search.search_apps("dab", apps)] == ["Radio"]
    assert search.search_apps("mesh", apps)[0].command == ("deck-launch", "mesh")


def test_search_isolates_failing_and_slow_providers(monkeypatch):
    monkeypatch.setattr(search, "PROVIDER_TIMEOUT", 0.2)

    def ok(q):
        return [search.Result(f"hit {q}", "A")]

    def boom(q):
        raise RuntimeError("provider exploded")

    def slow(q):
        time.sleep(2)
        return [search.Result("late", "C")]

    res = search.search("water", {"a": ok, "b": boom, "c": slow})
    assert [r.title for r in res] == ["hit water"]
    assert search.search("w", {"a": ok}) == []  # too short
    assert set(search.grouped(res)) == {"A"}


def test_notes_search(root):
    notes = root / "persist/notes"
    notes.mkdir(parents=True)
    (notes / "2026-01-01.md").write_text("# day\nFilter water through cloth first\n")
    (notes / "other.md").write_text("nothing here")
    res = search.search_notes("cloth")
    assert len(res) == 1 and res[0].subtitle == "Filter water through cloth first"


SS = """tcp   LISTEN 0 4096      127.0.0.1:8080      0.0.0.0:*
tcp   LISTEN 0 4096      [::1]:8090          [::]:*
udp   UNCONN 0 0     127.0.0.53%lo:53        0.0.0.0:*
udp   UNCONN 0 0           0.0.0.0:68        0.0.0.0:*
tcp   LISTEN 0 128         0.0.0.0:22        0.0.0.0:*
udp   UNCONN 0 0              *:5353         *:*
"""


def test_non_local_listeners():
    assert selftest.non_local_listeners(SS) == ["tcp 0.0.0.0:22", "udp *:5353"]
