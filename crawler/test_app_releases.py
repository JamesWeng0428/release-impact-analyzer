from crawler import app_releases as rel

LOOKUP = {
    "resultCount": 1,
    "results": [
        {
            "trackName": "Garmin Connect",
            "version": "5.29",
            "currentVersionReleaseDate": "2026-09-08T14:30:31Z",
            "releaseNotes": "Bug fixes and performance improvements.",
        }
    ],
}


def test_parse_lookup():
    assert rel.parse_lookup(LOOKUP) == {
        "version": "5.29",
        "release_date": "2026-09-08T14:30:31Z",
        "notes": "Bug fixes and performance improvements.",
    }
    assert rel.parse_lookup({"resultCount": 0, "results": []}) is None


def test_record_release_appends_each_version_once(tmp_path):
    path = tmp_path / "releases.jsonl"
    release = rel.parse_lookup(LOOKUP)
    assert rel.record_release(path, release) is True
    assert rel.record_release(path, release) is False
    assert rel.record_release(path, {**release, "version": "5.30"}) is True
    assert [r["version"] for r in rel.load_releases(path)] == ["5.29", "5.30"]
