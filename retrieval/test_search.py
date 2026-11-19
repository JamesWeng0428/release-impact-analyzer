import math

import pytest
import ria

from retrieval.search import ReviewSearch, expand_query, load_documents, main


def review(id, text, version="5.21.1", **changes):
    return {"id": id, "title": "", "text": text, "app_version": version,
            "date": "2026-01-30T12:00:00Z", "country": "us", "rating": 1, **changes}


def test_native_search_matches_hand_computed_bm25():
    index = ria.InvertedIndex()
    assert index.add_document("sync sync") == 0
    index.add_document("battery")
    result = ria.bm25_search(index, "sync", 1)[0]
    expected = math.log(2) * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 2 / 1.5))
    assert result.doc == 0
    assert result.score == pytest.approx(expected)
    assert index.num_documents == 2 and index.document_frequency("sync") == 1


@pytest.mark.parametrize("k1,b", [(-1, 0.75), (1.2, 2), (float("nan"), 0.75)])
def test_native_parameters_are_checked(k1, b):
    params = ria.Bm25Params()
    params.k1, params.b = k1, b
    with pytest.raises(ValueError, match="BM25 requires"):
        ria.bm25_search(ria.InvertedIndex(), "sync", params=params)


def test_search_preserves_metadata_and_ids_when_input_is_reordered():
    docs = [review("b", "sync failed"), review("a", "sync failed", rating=4)]
    left = ReviewSearch(docs).search("sync")
    right = ReviewSearch(list(reversed(docs))).search("sync")
    assert left == right
    assert [hit["id"] for hit in left] == ["a", "b"]
    assert {k: v for k, v in left[0].items() if k != "score"} == docs[1]
    docs[1]["text"] = "changed externally"
    assert left[0]["text"] == "sync failed"


@pytest.mark.parametrize("system", ["keyword", "bm25", "bm25_expanded"])
def test_filters_are_applied_before_top_k(system):
    engine = ReviewSearch([review("a", "sync", "5.20"), review("b", "sync", "5.21")])
    hits = engine.search("sync", 1, system, version="5.21")
    assert [hit["id"] for hit in hits] == ["b"]
    assert not engine.search("sync", system=system, country="gb")


def test_keyword_baseline_is_distinct_term_overlap_not_bm25():
    engine = ReviewSearch([review("a", "sync sync sync"), review("b", "sync bluetooth")])
    hits = engine.search("sync sync bluetooth", system="keyword")
    assert [(h["id"], h["score"]) for h in hits] == [("b", 2), ("a", 1)]


def test_expansion_recovers_a_word_form_without_modifying_plain_bm25():
    engine = ReviewSearch([review("a", "syncing fails")])
    assert not engine.search("sync")
    assert engine.search("sync", system="bm25_expanded")[0]["id"] == "a"
    assert expand_query("sync sync syncing").split().count("syncing") == 1
    assert expand_query("sync sync").split().count("sync") == 2


def test_empty_query_unknown_terms_and_zero_k():
    engine = ReviewSearch([review("a", "sync")])
    for system in ("keyword", "bm25", "bm25_expanded"):
        assert not engine.search("", system=system)
        assert not engine.search("xyznohit", system=system)
        assert not engine.search("sync", 0, system)
    assert not ReviewSearch([]).search("sync")


def test_duplicate_ids_and_missing_corpus_fail(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        ReviewSearch([review("a", "one"), review("a", "two")])
    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path / "missing.jsonl")


def test_cli_returns_json_with_original_review_id(tmp_path, capsys):
    import json

    path = tmp_path / "reviews.jsonl"
    path.write_text(json.dumps(review("apple-123", "sync failed")) + "\n")
    main(["sync", "--reviews", str(path), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["id"] == "apple-123"
