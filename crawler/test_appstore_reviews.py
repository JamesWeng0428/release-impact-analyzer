from crawler import appstore_reviews as ar


def make_entry(review_id="1", rating="2", version="5.29", title="Sync failed",
               text="Watch keeps\ndisconnecting."):
    return {
        "author": {"name": {"label": "someone"}},
        "id": {"label": review_id},
        "updated": {"label": "2026-09-22T15:52:33-07:00"},
        "im:rating": {"label": rating},
        "im:version": {"label": version},
        "title": {"label": title},
        "content": {"label": text},
    }


def test_parse_feed_extracts_fields_and_drops_author():
    reviews = ar.parse_feed({"feed": {"entry": [make_entry()]}}, "us")
    assert reviews == [
        {
            "id": "1",
            "country": "us",
            "date": "2026-09-22T15:52:33-07:00",
            "rating": 2,
            "app_version": "5.29",
            "title": "Sync failed",
            "text": "Watch keeps\ndisconnecting.",
        }
    ]


def test_parse_feed_handles_single_entry_metadata_and_empty_pages():
    assert len(ar.parse_feed({"feed": {"entry": make_entry()}}, "us")) == 1
    app_metadata = {"id": {"label": "583446403"}, "title": {"label": "Garmin Connect"}}
    assert ar.parse_feed({"feed": {"entry": [app_metadata, make_entry()]}}, "us")[0]["id"] == "1"
    assert ar.parse_feed({"feed": {}}, "us") == []


def test_fetch_country_stops_at_first_empty_page(monkeypatch):
    pages = iter([
        {"feed": {"entry": [make_entry("1"), make_entry("2")]}},
        {"feed": {"entry": [make_entry("3")]}},
        {"feed": {}},
    ])
    requested = []

    def fake_fetch(url):
        requested.append(url)
        return next(pages)

    monkeypatch.setattr(ar, "fetch_json", fake_fetch)
    monkeypatch.setattr(ar.time, "sleep", lambda _: None)

    ids = [r["id"] for r in ar.fetch_country("gb")]
    assert ids == ["1", "2", "3"]
    assert len(requested) == 3
    assert "/gb/" in requested[0] and "page=3" in requested[2]


def test_save_and_load_round_trip_and_dedupe(tmp_path):
    path = tmp_path / "reviews.jsonl"
    first = ar.parse_feed({"feed": {"entry": [make_entry("1"), make_entry("2")]}}, "us")
    ar.save_reviews(path, {r["id"]: r for r in first})

    reviews = ar.load_reviews(path)
    edited = ar.parse_feed({"feed": {"entry": [make_entry("2", rating="5")]}}, "us")[0]
    reviews[edited["id"]] = edited
    ar.save_reviews(path, reviews)

    loaded = ar.load_reviews(path)
    assert sorted(loaded) == ["1", "2"]
    assert loaded["2"]["rating"] == 5
    assert not path.with_suffix(".jsonl.tmp").exists()


def test_to_corpus_line_is_a_single_line():
    review = ar.parse_feed({"feed": {"entry": [make_entry()]}}, "us")[0]
    assert ar.to_corpus_line(review) == "Sync failed. Watch keeps disconnecting."
