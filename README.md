# Garmin Firmware Release Impact Analyzer

CS410 (Fall 2026) final project by James Weng (zweng7).

Garmin users with sync and Bluetooth problems have to dig through forum threads,
support FAQs and firmware changelogs to find out whether their issue is a known
bug and whether a later release fixed it. This project:

1. **Searches** user reports (App Store reviews; forum posts later) with a C++
   retrieval engine (inverted index + BM25),
   using a symptom or a changelog entry as the query.
2. **Mines** complaints with topic modeling and tracks each issue across
   firmware releases, to spot which release introduced a problem and whether a
   "fixed" item actually reduced complaints.

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
```

## Build and test

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
cmake -S . -B build-py -G Ninja -DCMAKE_BUILD_TYPE=Release -DRIA_BUILD_TESTS=OFF -DRIA_BUILD_PYTHON=ON -DPython_EXECUTABLE="$(which python3)"
cmake --build build-py
PYTHONPATH=build-py python3 -c "import ria; print(ria.tokenize('Edge 1050 sync failed after 31.20'))"
```

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
- [ ] Document store (external ids, title, device, date)
- [x] BM25 ranking + top-k retrieval
- [ ] Stemming / query expansion ("dropout" vs "drops out", "pair" vs "pairing")
- [ ] Field boosting (device model, firmware version)
- [x] App Store review fetcher (Garmin Connect, versioned reviews)
- [ ] Garmin forum posts (on hold: Terms of Use)
- [x] Release timeline (official dates + first-review estimates, keyword baseline for connectivity complaints)
- [x] Regression detection: Wilson intervals, one-sided Fisher exact tests against the previous versions, Benjamini-Hochberg FDR control
- [x] Fix verification (later releases vs regression and frozen pre-regression baseline, with uncertainty bounds)
- [ ] Relevance labels + evaluation (NDCG@10 vs keyword baseline)
- [ ] Topic modeling + per-release issue trends
- [ ] CI regression gates on quality, latency and memory

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
