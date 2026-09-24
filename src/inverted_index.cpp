#include "ria/inverted_index.h"

#include "ria/tokenizer.h"

namespace ria {

DocId InvertedIndex::add_document(std::string_view text) {
  const auto doc = static_cast<DocId>(doc_lengths_.size());
  const std::vector<std::string> tokens = tokenize(text);

  // Count each term once per document first, so every term gets exactly one
  // posting for this doc. Views point into `tokens`, which outlives the map.
  std::unordered_map<std::string_view, std::uint32_t> term_counts;
  for (const std::string& token : tokens) {
    ++term_counts[token];
  }

  // Doc ids only ever increase, so appending keeps every list sorted by doc.
  for (const auto& [term, tf] : term_counts) {
    auto it = postings_.find(term);
    if (it == postings_.end()) {
      it = postings_.emplace(std::string(term), std::vector<Posting>{}).first;
    }
    it->second.push_back(Posting{doc, tf});
  }

  doc_lengths_.push_back(static_cast<std::uint32_t>(tokens.size()));
  total_length_ += tokens.size();
  return doc;
}

std::span<const Posting> InvertedIndex::postings(std::string_view term) const {
  const auto it = postings_.find(term);
  if (it == postings_.end()) {
    return {};
  }
  return it->second;
}

double InvertedIndex::average_doc_length() const {
  if (doc_lengths_.empty()) {
    return 0.0;
  }
  return static_cast<double>(total_length_) /
         static_cast<double>(doc_lengths_.size());
}

}  // namespace ria
