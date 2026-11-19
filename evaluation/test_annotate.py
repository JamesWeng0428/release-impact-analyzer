import csv
import json
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request

import pytest

from evaluation.annotate import AnnotationStore, Conflict, make_server
from evaluation.retrieval import prepare, score

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    workspace = tmp_path / "workspace"
    prepare(ROOT / "examples/retrieval_reviews.jsonl", ROOT / "examples/retrieval_queries.jsonl", workspace)
    return AnnotationStore(workspace, "test-fixture", demo=True)


def payload(state, row=None, grade=2):
    row = row or state["rows"][0]
    return {"revision": state["revision"], "query_id": row["query_id"],
            "review_id": row["review_id"], "relevance": grade}


def test_save_reload_edit_and_complete_scoring_without_changing_source(store):
    original = store.path.read_bytes()
    state = store.state()
    first = state["rows"][0]
    saved = store.save(payload(state))
    assert saved["rows"][0]["relevance"] == "2"
    reopened = AnnotationStore(store.workspace, "test-fixture", demo=True)
    assert reopened.state() == saved
    saved = reopened.save(payload(saved, first, grade=0))
    assert saved["rows"][0]["relevance"] == "0"
    assert (store.workspace / "judgments.before-annotation.csv").read_bytes() == original
    for row in saved["rows"]:
        if not row["relevance"]:
            saved = reopened.save(payload(saved, row, grade=1))
    report = score(store.workspace, split="all")
    assert report["judgment_provenance"] == {"synthetic": len(saved["rows"])}
    with store.path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert all(r["assessor"] == "test-fixture" for r in rows)


def test_stale_tab_cannot_overwrite_a_saved_label(store):
    old = store.state()
    store.save(payload(old))
    before = store.path.read_bytes()
    with pytest.raises(Conflict):
        store.save(payload(old, grade=0))
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("grade", [True, -1, 3, "2", None])
def test_invalid_grade_never_writes(store, grade):
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save(payload(store.state(), grade=grade))
    assert store.path.read_bytes() == before


def test_failed_write_does_not_advance_or_lose_data(store, monkeypatch):
    before = store.path.read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        store.save(payload(store.state()))
    assert store.path.read_bytes() == before
    assert store.state()["rows"][0]["relevance"] == ""
    assert not list(store.workspace.glob(".annotation-*"))


def test_ai_labeled_sheet_is_rejected_and_source_text_is_protected(store):
    content = store.path.read_text()
    with store.path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    rows[0].update(relevance="2", assessor="ai", provenance="ai")
    with store.path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="AI judgments"):
        store.state()
    store.path.write_text(content)
    rows[0].update(relevance="", title="changed", assessor="", provenance="")
    with store.path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="source text"):
        store.state()


def test_http_session_saves_and_rejects_cross_origin_or_missing_token(store):
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(url).read().decode()
        token = re.search(r"token='([a-f0-9]+)'", page)[1]
        state = json.loads(urllib.request.urlopen(url + "/api/state").read())
        assert all("system" not in r and "score" not in r and "provenance" not in r for r in state["rows"])
        data = json.dumps(payload(state)).encode()
        for headers in ({}, {"X-Annotation-Token": token, "Origin": "https://example.invalid"}):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url + "/api/label", data=data, headers=headers))
            assert error.value.code == 403
        request = urllib.request.Request(url + "/api/label", data=data,
                                         headers={"X-Annotation-Token": token, "Origin": url})
        saved = json.loads(urllib.request.urlopen(request).read())
        assert saved["rows"][0]["relevance"] == "2"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 409
    finally:
        server.shutdown(); server.server_close(); thread.join()
