#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <span>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace ria {

// Dense internal document id, assigned in insertion order starting at 0.
using DocId = std::uint32_t;

// One entry in a term's postings list: the term appears `tf` times in `doc`.
struct Posting {
  DocId doc;
  std::uint32_t tf;

  bool operator==(const Posting&) const = default;
};

// Maps each term to the documents that contain it, plus the per-document
// lengths BM25 needs. Documents are tokenized with ria::tokenize().
class InvertedIndex {
 public:
  // Tokenizes and indexes `text`, returning the new document's id.
  DocId add_document(std::string_view text);

  // Postings for `term`, sorted by doc id; empty if the term never appears.
  // `term` must already be normalized, i.e. be an output of tokenize().
  std::span<const Posting> postings(std::string_view term) const;

  // Number of documents containing `term`.
  std::size_t document_frequency(std::string_view term) const {
    return postings(term).size();
  }

  // Number of tokens in `doc`. `doc` must be a valid id.
  std::uint32_t doc_length(DocId doc) const { return doc_lengths_.at(doc); }

  std::size_t num_documents() const { return doc_lengths_.size(); }
  std::size_t num_terms() const { return postings_.size(); }

  // Average document length in tokens; 0 when the index is empty.
  double average_doc_length() const;

 private:
  // Lets postings_ be searched with a std::string_view without first
  // copying it into a std::string.
  struct StringHash {
    using is_transparent = void;
    std::size_t operator()(std::string_view s) const noexcept {
      return std::hash<std::string_view>{}(s);
    }
  };

  std::unordered_map<std::string, std::vector<Posting>, StringHash,
                     std::equal_to<>>
      postings_;
  std::vector<std::uint32_t> doc_lengths_;
  std::uint64_t total_length_ = 0;
};

}  // namespace ria
