# Garmin Connect App Release Impact Analyzer

CS410 (Fall 2026) final project by James Weng (zweng7).

Garmin users with sync and Bluetooth problems have to dig through reviews and
support discussions to find similar reports and see whether complaints changed
after an app update. This project:

1. **Searches** user reports (App Store reviews; forum posts later) with a C++
   retrieval engine (inverted index + BM25),
   using a symptom as the query, while keeping each review's ID, app version,
   country, rating and date.
2. **Tracks** keyword-labeled connectivity complaints across Garmin Connect
   app versions, flags changes, and checks later releases for evidence of
   recovery. These are review trends, not proof of a device-firmware bug or fix.
3. **Evaluates** keyword overlap, BM25 and BM25 with fixed query expansion on
   frozen query-review pools. AI relevance labels cover all development and test
   pairs; independent human validation is still pending. Topic modeling is
   future work.

## Layout

```
include/ria/   public C++ headers
src/           C++ core library (ria_core)
apps/          command-line tool (ria)
tests/         GoogleTest unit tests
examples/      small made-up corpus for demos
python/        pybind11 bindings, used by the evaluation scripts
crawler/       data collection (Python, standard library only)
analysis/      per-release analysis of the collected data
retrieval/     metadata-preserving search through the C++ Python bindings
evaluation/    queries, blind annotation pools and ranking metrics
```

## Build and test

Use Python 3.12 (the CI-tested version), a C++20 compiler, CMake 3.25+ and
Ninja. From a fresh checkout, create an isolated environment first:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Use this environment for both CMake's Python interpreter and every Python
command below. The first build downloads GoogleTest; installing dependencies
also requires network access. Tests and examples then run offline. Build
directories are machine-specific: regenerate them after moving a checkout.

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

Search a corpus (one document per line); each line typed on stdin is a query:

```bash
./build/ria examples/sample_posts.txt 3
```

`examples/sample_posts.txt` holds a few made-up example posts for demos.

Build the Python module (in its own build directory, without sanitizers):

```bash
python3 -m pip install -r requirements-dev.txt
cmake -S . -B build-py -G Ninja -DCMAKE_BUILD_TYPE=Release -DRIA_BUILD_TESTS=OFF -DRIA_BUILD_PYTHON=ON -DPython_EXECUTABLE="$(which python3)" -Dpybind11_DIR="$(python3 -m pybind11 --cmakedir)"
cmake --build build-py
PYTHONPATH=build-py python3 -c "import ria; print(ria.tokenize('Edge 1050 sync failed after 31.20'))"
```

`requirements-dev.txt` provides the Python test tools and pybind11. If pybind11
is already installed through a system package manager, its CMake directory can
be supplied instead. Use the same Python interpreter to configure, test and
run the bindings.

## Search and retrieval evaluation

Run these commands from the project root after building `build-py`:

```bash
PYTHONPATH=build-py python3 -m retrieval.search "bluetooth disconnect" --top-k 5
PYTHONPATH=build-py python3 -m retrieval.search "sync" --version 5.21.1 --system bm25_expanded --json
PYTHONPATH=build-py python3 -m pytest -q crawler analysis retrieval evaluation
```

Search returns the original review text and metadata. The `--version` filter
means **app version**, not device firmware. BM25 scores use the entire collection
even when results are filtered. Search results do not change the denominator
used by the release timeline or regression analysis.

## Complete release impact report

After collecting data, one command combines the timeline, all regression tests,
recovery bounds and original review evidence:

```bash
python -m analysis.report --output build-py/impact-report.md
python -m analysis.report --format json --output build-py/impact-report.json
```

The report needs no native bindings. It records input SHA-256 fingerprints,
analysis parameters, sample sizes and illustrative complaint/non-complaint
reviews (up to two of each per version, sorted by review ID). Selecting evidence
does not filter the statistical population. Search remains a separate command.
Reports contain review text and are local outputs, not committed artifacts.

An offline example works immediately after cloning:

```bash
python -m analysis.report --reviews examples/retrieval_reviews.jsonl
```

This tiny synthetic corpus intentionally reports insufficient comparable
versions under the default thresholds. End-to-end tests also construct a larger
synthetic spike/recovery scenario and verify the expected conclusions.

All analysis commands require an existing, nonempty review file. Invalid JSON,
duplicate IDs, invalid ratings, version strings or dates produce file/line
diagnostics. Missing data is never reported as evidence of no regression.
Official release history is optional: commands use `data/app_releases.jsonl`
when present, or estimate dates from first reviews when absent. An explicit
`--releases PATH` must exist and contain valid records. Dates in input records
must be ISO 8601 timestamps with timezones. Versions are ordered numerically.

The collector alone permits a missing destination on its first run. Failed
collection leaves the previous dataset intact; review and release writes use
atomic replacement. Run only one collector per output file at a time.

## Reproduce metrics and measure performance

Published AI evaluation metrics now reproduce from a fresh clone, without
native bindings, network access or the private review corpus:

```bash
python -m evaluation.reproduce
```

This checks frozen rankings, queries, label/report hashes and recomputes every
per-query and aggregate metric for dev, test and all. It does **not** rerun
retrieval or turn AI labels into human ground truth. See
[evaluation/README.md](evaluation/README.md) for full corpus requirements.

Measure all three search methods on your local corpus:

```bash
PYTHONPATH=build-py python -m evaluation.benchmark --output build-py/benchmark.json
```

The output records corpus/query hashes, environment, load/index time, warm-query
p50/p95/max latency and whole-process peak RSS (including Python and native
memory). It does not measure filtered queries or per-request startup time.
See [the measured local baseline](evaluation/performance_baseline.md).
CI verifies correctness and runs the benchmark as a smoke check; machine-specific
latency/memory thresholds are not enforced on shared runners.

## Prepare a new retrieval experiment

### Label one review at a time

For the existing frozen local workspace, launch the annotation page:

```bash
python -m evaluation.annotate --open
```

Open `http://127.0.0.1:8765`. Choose Test (formal labels) or Dev (practice),
read the information need and full review, and click or press **0 / 1 / 2**.
Each choice is atomically saved to `evaluation/workspace/judgments.csv` as
`assessor=james`, `provenance=human`, before advancing. Use `--assessor NAME`
for another annotator, with a separate workspace copy for independent labels.
The first save creates `judgments.before-annotation.csv` as a recovery copy.

Refresh or restart the server to resume at the first unjudged pair. Previous/next
controls let you revise earlier answers; skip leaves the score blank. The UI
hides AI labels, system names and rankings. A conflicting edit from another tab
is rejected and asks you to reload. Keep the terminal running while annotating;
Ctrl+C stops the server without deleting saved progress. The page binds only to
this computer's loopback interface and requires no extra dependencies.

The workspace itself is local and ignored by Git. On a fresh clone, run the
`prepare` command below on your corpus before launching the annotation page.
For disposable UI tests, `--demo --workspace PATH` writes `synthetic` provenance;
never use that option on your actual human annotation workspace.

Freeze the local corpus and prepare the real relevance annotation task:

```bash
PYTHONPATH=build-py python3 -m evaluation.retrieval prepare
# Fill relevance (0/1/2), assessor and provenance in:
# evaluation/workspace/judgments.csv
python3 -m evaluation.retrieval score --split dev --report evaluation/workspace/dev-report.json
python3 -m evaluation.retrieval score --split test --report evaluation/workspace/test-report.json
```

The query set has 8 development and 16 test queries. Preparation pools the top
10 results from each of three methods and hides ranks and system names in the
annotation sheet. Scoring requires all pooled pairs for the selected split to
be judged; blank labels are not treated as irrelevant. The separate human
annotation sheet remains blank. AI judgments with rationales are available for
all 433 pooled pairs, with development, test and combined reports:

```bash
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_dev.csv --split dev
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_test.csv --split test
python3 -m evaluation.retrieval score --judgments evaluation/relevance_ai_all.csv --split all
```

The 16-query AI-labeled test comparison gives NDCG@10 of 0.5869 (keyword),
0.6535 (BM25) and 0.6821 (BM25 + expansion). These are AI judgments, not
independent human ground truth. `evaluation/ai_annotation_manifest.json`
records the source, rubric, coverage and data/code hashes. The combined result
includes development queries and should not be described as held-out performance.

An entirely synthetic example runs offline without annotating real reviews:

```bash
PYTHONPATH=build-py python3 -m evaluation.retrieval prepare --reviews examples/retrieval_reviews.jsonl --queries examples/retrieval_queries.jsonl --out build-py/evaluation-example
python3 -m evaluation.retrieval score --workspace build-py/evaluation-example --judgments examples/retrieval_judgments.csv --split all --report build-py/example-report.json
```

Use a fresh output directory for a second preparation; existing annotations are
never overwritten. The synthetic example checks the pipeline, not effectiveness
on Garmin reviews. See [evaluation/README.md](evaluation/README.md) for the
judging rubric, metric definitions and evaluation limitations.

Options (pass as `-DNAME=ON`):

| Option | Default | Purpose |
|---|---|---|
| `RIA_BUILD_TESTS` | ON | Build unit tests (downloads GoogleTest) |
| `RIA_BUILD_PYTHON` | OFF | Build the `ria` Python module (needs pybind11) |
| `RIA_WARNINGS_AS_ERRORS` | OFF | `-Werror`; CI turns it on |
| `RIA_SANITIZE` | OFF | AddressSanitizer + UBSan; CI turns it on |

## Data

Garmin Connect reviews come from Apple's public App Store review feed. Each
country serves only its most recent reviews, so the fetcher merges every run
into one JSONL file (keyed by review id); running it weekly builds up history
across app versions. Reviewer names are not stored, and `data/` is not
committed.

```bash
python3 -m crawler.appstore_reviews fetch                      # -> data/appstore_reviews.jsonl
python3 -m crawler.app_releases                                # -> data/app_releases.jsonl
python3 -m crawler.appstore_reviews export > data/corpus.txt   # one review per line
./build/ria data/corpus.txt 5
python3 -m analysis.release_timeline --min-reviews 15          # per-version table
python3 -m analysis.regression                                 # significant changes only (--all for every version)
python3 -m analysis.fix_verification                           # later releases vs regression and original baseline
python3 -m pytest -q crawler analysis                          # offline unit tests
```

Apple's Lookup API only describes the current release, so `app_releases`
records one new version per run; older release dates are estimated from each
version's earliest review. Garmin Connect's release notes are mostly
"bug fixes and performance improvements", which is why the impact of each
release has to be inferred from reviews.

Garmin forum posts are on hold until it is clear that crawling them fits
Garmin's Terms of Use.

### Connectivity complaint labels

The timeline counts explicit pairing, discovery, and sync failures at any
star rating. For 1–2 star reviews it also counts weaker connectivity mentions.
The regression and recovery reports both use these labels.

`evaluation/connectivity_holdout.csv` contains 60 review IDs and text-based
labels assigned by one AI reviewer before comparing predictions. The sample
contains 20 previously unaudited reviews each from the earlier baseline,
5.21.1, and later releases. All 5.20.4 reviews had already been audited.
The labels count reported device or app data-transfer failures, including
third-party services. Mentions of someone else's problem alone do not count.

On these 60 reviews the original rule caught 19 of 27 complaints and the
revised rule caught 20. Both flagged one of 33 non-complaints. The balanced
release groups and small sample limit how far these counts generalize.
Join the labels to `data/appstore_reviews.jsonl` using its `id` field.

## Roadmap

- [x] Tokenizer (keeps firmware versions like `31.20` as one term)
- [x] Inverted index (postings with term frequencies, document lengths)
- [x] In-memory review store (external ids, title, app version, country, rating, date)
- [x] BM25 ranking + top-k retrieval
- [x] Fixed query expansion baseline (e.g. "pair" also retrieves "pairing")
- [ ] Stemming / learned query expansion
- [ ] Field boosting (device model, firmware version)
- [x] App Store review fetcher (Garmin Connect, versioned reviews)
- [ ] Garmin forum posts (on hold: Terms of Use)
- [x] Release timeline (official dates + first-review estimates, keyword baseline for connectivity complaints)
- [x] Regression detection: Wilson intervals, one-sided Fisher exact tests against the previous versions, Benjamini-Hochberg FDR control
- [x] Fix verification (later releases vs regression and frozen pre-regression baseline, with uncertainty bounds)
- [x] Relevance evaluation pipeline (NDCG@10, P@5; keyword vs BM25 vs expansion)
- [x] Unified impact report with input fingerprints and review evidence
- [x] Input/error handling, offline end-to-end tests and network-failure tests
- [x] Public frozen-ranking metric reproduction and CI checks
- [x] Latency/peak-RSS benchmark with explicit measurement scope
- [ ] Human relevance judgments + final held-out comparison
- [ ] Topic modeling + per-release issue trends
- [ ] Independent human quality validation and calibrated performance budgets

## Fix verification

Compare later releases with each detected regression and its frozen
pre-regression baseline:

```bash
python3 -m analysis.fix_verification
python3 -m analysis.fix_verification --recovery-margin 0.05
python3 -m analysis.fix_verification --json
```

A sequence stops before the next detected regression. Releases below
`--min-reviews` stay visible as `insufficient_data`; they do not
enter the pooled baseline. Later releases are candidates, not assumed hotfixes.

The report uses [exact binomial confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)
with a Bonferroni error budget across every eligible version and every possible
pooled baseline, counted before choosing regressions. Subtracting interval
endpoints gives conservative simultaneous bounds for the rate differences.
Overlapping groups do not require independence for this adjustment.

- `recovery_supported`: evidence of a drop from the regression, with the
  upper bound on excess complaints within the recovery tolerance.
- `partial_recovery`: evidence of improvement, but still elevated over baseline.
- `improved_recovery_uncertain`: evidence of improvement; too much uncertainty
  to establish recovery or remaining elevation.
- `no_clear_improvement`: insufficient evidence of a meaningful drop.
- `insufficient_data`: too few reviews to assess the candidate.

By default, improvement needs a positive lower confidence bound and an observed
drop of at least 10 percentage points (`--min-delta 0.10`). Recovery means the
upper bound on excess over baseline is at most 10 percentage points
(`--recovery-margin 0.10`). This tolerance is not exact equality; choose it
before interpreting the report. `--alpha 0.05` sets the regression detector's
FDR threshold and a separate 95% simultaneous coverage target for the recovery
bounds. These are separate guarantees, not a combined 95% guarantee about all
regression and recovery conclusions.

A non-significant baseline comparison alone never establishes recovery.
The bounds can be wide for small samples. Review populations can differ across
releases, and complaints currently use a keyword heuristic. The results describe
Garmin Connect app reviews and do not prove a causal fix or device-firmware
recovery.
