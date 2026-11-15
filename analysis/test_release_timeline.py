from analysis import release_timeline as tl


def review(version, date, rating=1, title="", text=""):
    return {"app_version": version, "date": date, "rating": rating, "title": title, "text": text}


def test_version_key_sorts_numerically():
    versions = ["5.28", "5.10", "5.27.3", "5.9", "5.28.1"]
    assert sorted(versions, key=tl.version_key) == ["5.9", "5.10", "5.27.3", "5.28", "5.28.1"]


def test_connectivity_baseline():
    assert tl.is_connectivity_complaint(review("5.29", "", 1, "Sync failed", ""))
    assert tl.is_connectivity_complaint(review("5.29", "", 2, "", "Watch keeps disconnecting"))
    # The app's own name is not a connection problem.
    assert not tl.is_connectivity_complaint(review("5.29", "", 1, "Garmin Connect crashes", ""))
    # Happy reviews that mention syncing are not complaints.
    assert not tl.is_connectivity_complaint(review("5.29", "", 5, "Syncs perfectly", ""))


def test_explicit_failures_from_review_audit():
    for rating, text in [
        (4, "My Fenix stopped working and I cannot reconnect it."),
        (3, "Can’t pair my watch anymore with Garmin Connect."),
        (1, "Unpaired my watch. Instructions to fix don’t work."),
        (1, "The update left my watch undiscoverable by the app."),
        (3, "I had to reset my watch before it would pair again."),
    ]:
        assert tl.is_connectivity_complaint(review("5.21.1", "", rating, text=text)), text


def test_higher_ratings_need_a_connection_failure():
    for text in [
        "No sync issues with my watch.",
        "I can't customize my watch face. Sync works perfectly.",
        "I unpaired my headphones to use them elsewhere.",
        "I reset my watch. It would pair instantly.",
    ]:
        assert not tl.is_connectivity_complaint(review("5.21.1", "", 4, text=text)), text


def test_build_timeline_prefers_official_dates_and_computes_shares():
    reviews = [
        review("5.28", "2026-08-20T10:00:00-07:00", 1, "Sync failed"),
        review("5.28", "2026-08-15T10:00:00-07:00", 5, "Love it"),
        review("5.29", "2026-09-10T10:00:00-07:00", 4, "Fine"),
    ]
    releases = [{"version": "5.29", "release_date": "2026-09-08T14:30:31Z", "notes": ""}]

    rows = tl.build_timeline(reviews, releases)
    assert [r["version"] for r in rows] == ["5.28", "5.29"]

    old, new = rows
    assert (old["release_date"], old["date_source"]) == ("2026-08-15", "first review")
    assert (new["release_date"], new["date_source"]) == ("2026-09-08", "official")
    assert old["reviews"] == 2 and old["avg_rating"] == 3.0 and old["connectivity_share"] == 0.5
    assert new["connectivity_share"] == 0.0


def test_official_release_without_reviews_is_kept():
    rows = tl.build_timeline([], [{"version": "5.30", "release_date": "2026-10-01T00:00:00Z"}])
    assert rows[0]["reviews"] == 0 and rows[0]["avg_rating"] is None
    assert "5.30" in tl.format_table(rows)
