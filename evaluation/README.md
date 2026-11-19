# Retrieval evaluation

This evaluates **query-document relevance**. `connectivity_holdout.csv` evaluates
the separate connectivity complaint classifier; those binary labels are not
reused as relevance judgments.

## Methods

All methods index the same `title + text`, using the C++ tokenizer. Reviews are
sorted lexicographically by external review ID before indexing. This keeps
document mapping and score ties stable if the source JSONL is reordered.

| Method | Ranking |
|---|---|
| `keyword` | Number of distinct query terms present in each review; OR matching |
| `bm25` | C++ BM25, k1=1.2 and b=0.75 |
| `bm25_expanded` | The same BM25 with the fixed domain vocabulary in `retrieval/search.py` |

The keyword method ignores term frequency, rarity and document length. BM25
uses all three. Expansion is an experimental variant: matching more word forms
can introduce irrelevant results. No improvement is assumed in advance.

Version and country are filters for interactive search, not indexed search
terms. The initial evaluation compares unfiltered rankings.

## Freeze and annotate

From the repository root, with the native module built:

```bash
PYTHONPATH=build-py python3 -m evaluation.retrieval prepare
```

The curated query list contains 24 English information needs: 8 `dev` and 16
`test`. Each query includes a description of what should count as relevant.
The split is by query, not by document, user, device or time; it does not measure
generalization to a new app or an unseen release. Different queries can retrieve
the same review.

`prepare` creates a local workspace:

| File | Purpose |
|---|---|
| `corpus.jsonl` | Frozen review records with original IDs and metadata |
| `queries.jsonl` | Frozen query text, information needs and dev/test split |
| `runs.jsonl` | Ranked IDs and scores for all three methods |
| `pool.csv` | Immutable, deterministically shuffled union of their top-10 results |
| `judgments.csv` | Editable copy of the pool; labels start blank |
| `manifest.json` | SHA-256 hashes, corpus size, methods and parameter values |

Keep this directory local: it contains review text and is ignored by Git.
Prepare into a new directory after any corpus, query or retrieval-method change.
The tool refuses to overwrite a nonempty directory. Scoring rejects changes to
the frozen corpus, query file, runs or original pool.

The pool conceals system names, scores and ranks. While judging, do not inspect
`runs.jsonl`. Read the query's **information need**, review title and full text.
Fill these columns in `judgments.csv`:

| Column | Allowed values |
|---|---|
| `relevance` | `2`: directly answers the need; `1`: partly relevant or missing a requested detail; `0`: unrelated or contradicts the requested problem |
| `assessor` | A reviewer identifier, e.g. `james` |
| `provenance` | `human`, `ai`, or `synthetic` |

A low star rating does not establish relevance. A five-star review can describe
the requested failure. For a query asking about failed sync, “sync works
perfectly” is not relevant; for a query asking whether a fix worked, it may be.
Do not infer an unnamed device, update or symptom from the star rating alone.
Use the information need to distinguish partial matches from direct answers.

Judge development queries first. Use them to inspect failure cases and make
method decisions. Freeze those decisions before inspecting test judgments. If a
method changes, re-pool the candidates before scoring it. Do not tune to the
test results and then describe them as an untouched held-out comparison.

For final project results, use human judgments and report who judged them.
Have a second person independently judge a subset when feasible, record
disagreements and explain how they were resolved. AI labels can support an
explicitly identified pilot; they are not independent human ground truth.

## Score

```bash
python3 -m evaluation.retrieval score --split dev --report evaluation/workspace/dev-report.json
python3 -m evaluation.retrieval score --split test --report evaluation/workspace/test-report.json
```

Scoring uses saved rankings, so it does not require the native module. It
requires every pooled pair for the selected split to have a valid judgment,
assessor and provenance. Blank labels produce an error, rather than a score
that silently treats unjudged results as irrelevant. Duplicate and unknown
pairs also produce errors.

- **P@5**: number of grades greater than zero in the first five ranks, divided
  by five. Returning fewer than five results does not reduce the denominator.
- **NDCG@10**: gain `2^grade - 1`, discounted by `log2(rank + 1)` for ranks
  starting at 1. IDCG uses the best ordering of all judged pool documents for
  that query. A query with no known relevant items receives zero and a warning.
- Aggregate values are unweighted means across queries. JSON reports include
  per-query values, label provenance and all snapshot hashes.

See the [Stanford IR textbook's ranked retrieval evaluation chapter](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-ranked-retrieval-results-1.html)
for the rationale for graded relevance and NDCG.

These metrics describe the fixed judged pool, not all relevant reviews in the
corpus. Pooling may miss relevant documents found by other methods. A new system
needs a new, expanded pool; it should not score its unjudged results as zero.
With only 16 test queries, report per-query failures and avoid claiming broad or
statistically significant superiority from a small mean difference.

## Offline example and current status

`examples/retrieval_reviews.jsonl`, `examples/retrieval_queries.jsonl` and
`examples/retrieval_judgments.csv` are constructed examples. They exercise the
full pipeline with explicit `synthetic` provenance. See the main README for
the two commands to run them. Their scores are not project effectiveness results.

The initial real-data workspace contains 1,435 reviews and 433 pooled pairs
(141 development, 292 test). The preparation script does not infer any labels.

`relevance_ai_dev.csv` contains 141 explicit AI judgments with short rationales,
covering the 8 development queries. The assessor read the pool text and
information needs without system names or ranks. The same AI implemented the
methods and assigned these labels, so this is a diagnostic pilot, not an
independent assessment. No methods were tuned after inspecting these scores.

| Method | Dev NDCG@10 | Dev P@5 |
|---|---:|---:|
| Keyword overlap | 0.6716 | 0.8500 |
| BM25 | 0.7093 | 0.9500 |
| BM25 + fixed expansion | 0.7826 | 1.0000 |

The high P@5 values count both partial and direct matches as relevant. They do
not establish that every top result directly answers its query. These pilot
scores do not establish performance on unseen queries or superiority under
human judgments. `ai_dev_report.json` records per-query values, label provenance
and the exact corpus/query/run hashes. Use these labels only with that snapshot.

The averages conceal failures. For `d02` (pairing after an update), expansion
reduces NDCG@10 from 0.6645 to 0.5304. For `d04` (crash at startup), it increases
the metric from 0.3425 to 0.8429. Inspect these cases before deciding which
method to use; the interactive search default remains plain BM25.

```bash
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_dev.csv --split dev
```

The remaining 292 pairs across 16 test queries are now labeled in
`relevance_ai_test.csv`. Each row records `assessor=codex-ai-test`,
`provenance=ai`, a 0/1/2 relevance grade and a short rationale. The source is
the Codex AI assistant in this chat; the exact deployed model identifier is
not exposed. These labels were assigned from the query need and full review
text without displaying system names, ranks or scores. All test labels were
written before test scores were computed. Retrieval code, parameters, corpus,
queries, rankings and pool were unchanged, and no method was tuned on the
test results.

`relevance_ai_all.csv` combines those test labels with the unchanged 141 dev
labels. `ai_annotation_manifest.json` records the annotation source, rubric,
per-query grade counts and SHA-256 hashes of the snapshot, labels, reports and
retrieval code. Reports retain the `ai` provenance warning.

| Method | Test NDCG@10 | Test P@5 | All NDCG@10 | All P@5 |
|---|---:|---:|---:|---:|
| Keyword overlap | 0.5869 | 0.6625 | 0.6151 | 0.7250 |
| BM25 | 0.6535 | 0.7625 | 0.6721 | 0.8250 |
| BM25 + fixed expansion | 0.6821 | 0.7875 | 0.7156 | 0.8583 |

Test contains 16 queries and 292 judgments; All contains 24 queries and 433
judgments. **All includes development queries and is descriptive, not a
held-out test estimate.** The test split was held out from method tuning, but
its AI labels are not independent human ground truth.

The test average also conceals important failures:

- `t08` (freeze screen): expansion increases NDCG@10 from 0.4182 to 1.0000.
- `t10` (Fenix sync): expansion decreases NDCG@10 from 0.7786 to 0.6640.
- `t02` (activity missing after sync): expansion decreases NDCG@10 from 0.7119
  to 0.6652.
- `t13` (sending planned workouts) and `t16` (update restored connectivity)
  have no grade-2 direct matches in their judged pools. Partial matches still
  contribute to P@5 and NDCG. These scores do not establish that the system
  found a direct answer, or that no direct answer exists elsewhere in the corpus.

Reproduce the scored comparisons without building the native module:

```bash
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_test.csv --split test --report evaluation/workspace/test-ai-recomputed.json
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_all.csv --split all --report evaluation/workspace/all-ai-recomputed.json
```

The full per-query results are in `ai_test_report.json` and
`ai_all_report.json`. The default `workspace/judgments.csv` remains blank for
independent human annotation; no AI label has been recorded as human.
