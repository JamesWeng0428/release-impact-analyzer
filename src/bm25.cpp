#include "ria/bm25.h"

#include <algorithm>
#include <cmath>
#include <string>
#include <stdexcept>
#include <unordered_map>

#include "ria/tokenizer.h"

namespace ria {

double bm25_idf(std::size_t num_docs, std::size_t df) {
  const auto n = static_cast<double>(num_docs);
  const auto d = static_cast<double>(df);
  return std::log(1.0 + (n - d + 0.5) / (d + 0.5));
}

std::vector<SearchResult> bm25_search(const InvertedIndex& index,
                                      std::string_view query, std::size_t k,
                                      const Bm25Params& params) {
  if (!std::isfinite(params.k1) || params.k1 < 0 ||
      !std::isfinite(params.b) || params.b < 0 || params.b > 1) {
    throw std::invalid_argument("BM25 requires finite k1 >= 0 and 0 <= b <= 1");
  }
  if (k == 0) {
    return {};
  }

  std::unordered_map<std::string, std::uint32_t> query_tf;
  for (std::string& term : tokenize(query)) {
    ++query_tf[std::move(term)];
  }

  // Term-at-a-time scoring: one accumulator per document, plus the list of
  // documents that received any score so ranking never scans the whole index.
  std::vector<double> scores(index.num_documents(), 0.0);
  std::vector<DocId> matched;
  // Only reached when some term has postings, so avgdl > 0 here.
  const double avgdl = index.average_doc_length();

  for (const auto& [term, qtf] : query_tf) {
    const auto postings = index.postings(term);
    if (postings.empty()) {
      continue;
    }
    const double idf = bm25_idf(index.num_documents(), postings.size());
    for (const Posting& p : postings) {
      // Every contribution is > 0 (idf > 0, tf >= 1), so a zero score means
      // this is the first query term seen in the document.
      if (scores[p.doc] == 0.0) {
        matched.push_back(p.doc);
      }
      const double tf = p.tf;
      const double length_ratio = index.doc_length(p.doc) / avgdl;
      const double norm = params.k1 * (1.0 - params.b + params.b * length_ratio);
      scores[p.doc] += qtf * idf * tf * (params.k1 + 1.0) / (tf + norm);
    }
  }

  std::vector<SearchResult> results;
  results.reserve(matched.size());
  for (const DocId doc : matched) {
    results.push_back({doc, scores[doc]});
  }

  // partial_sort only fully orders the first k entries: O(m log k).
  const auto better = [](const SearchResult& a, const SearchResult& b) {
    return a.score != b.score ? a.score > b.score : a.doc < b.doc;
  };
  const std::size_t top = std::min(k, results.size());
  std::partial_sort(results.begin(),
                    results.begin() + static_cast<std::ptrdiff_t>(top),
                    results.end(), better);
  results.resize(top);
  return results;
}

}  // namespace ria
