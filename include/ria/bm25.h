#pragma once

#include <cstddef>
#include <string_view>
#include <vector>

#include "ria/inverted_index.h"

namespace ria {

struct Bm25Params {
  double k1 = 1.2;  // How quickly repeated terms stop adding score (>= 0).
  double b = 0.75;  // How strongly long documents are penalized (0..1).
};

struct SearchResult {
  DocId doc;
  double score;

  bool operator==(const SearchResult&) const = default;
};

// IDF used by BM25: ln(1 + (N - df + 0.5) / (df + 0.5)).
// The "1 +" keeps it positive even for terms found in most documents.
double bm25_idf(std::size_t num_docs, std::size_t df);

// Returns up to `k` documents matching at least one query term, best first.
// Equal scores are ordered by doc id so results are deterministic.
// A query term that appears twice counts twice.
std::vector<SearchResult> bm25_search(const InvertedIndex& index,
                                      std::string_view query, std::size_t k,
                                      const Bm25Params& params = {});

}  // namespace ria
