import argparse
import io
import json
from pathlib import Path
import urllib.error

import pytest

from crawler import appstore_reviews as ar
from crawler.test_appstore_reviews import make_entry
from crawler import app_releases as rel


@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError("https://example.invalid", 429, "limited", {}, None),
    urllib.error.HTTPError("https://example.invalid", 503, "unavailable", {}, None),
    urllib.error.URLError("offline"), TimeoutError("timeout"),
])
def test_transient_network_failures_retry_then_succeed(monkeypatch, failure):
    calls, sleeps = [], []
    def request(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise failure
        return io.StringIO('{"ok": true}')
    monkeypatch.setattr(ar.urllib.request, "urlopen", request)
    monkeypatch.setattr(ar.time, "sleep", sleeps.append)
    assert ar.fetch_json("https://example.invalid", retries=2, backoff=0.5) == {"ok": True}
    assert sleeps == [0.5, 1.0]
    assert len(calls) == 3


@pytest.mark.parametrize("status,expected", [(404, 1), (500, 3)])
def test_retry_limit_and_nonretryable_errors(monkeypatch, status, expected):
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("https://example.invalid", status, "error", {}, None)
    monkeypatch.setattr(ar.urllib.request, "urlopen", request)
    monkeypatch.setattr(ar.time, "sleep", lambda _: None)
    with pytest.raises(urllib.error.HTTPError):
        ar.fetch_json("https://example.invalid", retries=2)
    assert len(calls) == expected


def test_failed_collection_keeps_previous_dataset_intact(tmp_path, monkeypatch):
    path = tmp_path / "reviews.jsonl"
    old = ar.parse_feed({"feed": {"entry": make_entry()}}, "us")[0]
    ar.save_reviews(path, {old["id"]: old})
    original = path.read_bytes()
    def broken_fetch(*args):
        yield {**old, "id": "new"}
        raise TimeoutError("feed unavailable")
    monkeypatch.setattr(ar, "fetch_country", broken_fetch)
    with pytest.raises(TimeoutError):
        ar.cmd_fetch(argparse.Namespace(out=path, countries=["us"], app_id="123", delay=0))
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", [{"rating": True}, {"rating": 6}, {"date": "yesterday"},
                                  {"date": "2026-01-01"}, {"app_version": ""}, {"text": None}])
def test_invalid_record_has_file_and_line_diagnostic(tmp_path, change):
    record = ar.parse_feed({"feed": {"entry": make_entry()}}, "us")[0]
    path = tmp_path / "reviews.jsonl"
    path.write_text("\n" + json.dumps({**record, **change}))
    with pytest.raises(ValueError, match=r"reviews.jsonl:2:"):
        ar.load_reviews(path)


def test_duplicate_ids_fail_instead_of_silently_changing_denominator(tmp_path):
    record = ar.parse_feed({"feed": {"entry": make_entry()}}, "us")[0]
    path = tmp_path / "reviews.jsonl"
    path.write_text((json.dumps(record) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate id"):
        ar.load_reviews(path)


def test_blank_lines_are_allowed_and_missing_ok_is_explicit(tmp_path):
    path = tmp_path / "reviews.jsonl"
    with pytest.raises(FileNotFoundError):
        ar.load_reviews(path)
    assert ar.load_reviews(path, missing_ok=True) == {}
    record = ar.parse_feed({"feed": {"entry": make_entry()}}, "us")[0]
    path.write_text("\n" + json.dumps(record) + "\n\n")
    assert ar.load_reviews(path) == {record["id"]: record}


@pytest.mark.parametrize("kind", ["reviews", "releases"])
def test_failed_atomic_replace_preserves_data_and_cleans_temporary_file(tmp_path, monkeypatch, kind):
    path = tmp_path / "records.jsonl"
    review = ar.parse_feed({"feed": {"entry": make_entry()}}, "us")[0]
    release = {"version": "1", "release_date": "2026-01-01T00:00:00Z"}
    if kind == "reviews":
        ar.save_reviews(path, {review["id"]: review})
    else:
        rel.record_release(path, release)
    original = path.read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        if kind == "reviews":
            ar.save_reviews(path, {review["id"]: {**review, "rating": 5}})
        else:
            rel.record_release(path, {**release, "version": "2"})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
