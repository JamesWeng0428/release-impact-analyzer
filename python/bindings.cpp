// Python bindings, so the evaluation scripts can call the C++ engine directly:
//
//   import ria
//   ria.tokenize("Edge 1050 sync failed")

#include "ria/bm25.h"
#include "ria/inverted_index.h"
#include "ria/tokenizer.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

PYBIND11_MODULE(ria, m) {
  m.doc() = "Garmin Connect app release impact analyzer (C++ core)";
  m.def("tokenize", &ria::tokenize, pybind11::arg("text"),
        "Split text into lowercase search terms.");
  pybind11::class_<ria::InvertedIndex>(m, "InvertedIndex")
      .def(pybind11::init<>())
      .def("add_document", &ria::InvertedIndex::add_document)
      .def("document_frequency", &ria::InvertedIndex::document_frequency)
      .def("doc_length", &ria::InvertedIndex::doc_length)
      .def_property_readonly("num_documents", &ria::InvertedIndex::num_documents)
      .def_property_readonly("num_terms", &ria::InvertedIndex::num_terms)
      .def_property_readonly("average_doc_length", &ria::InvertedIndex::average_doc_length);
  pybind11::class_<ria::Bm25Params>(m, "Bm25Params")
      .def(pybind11::init<>())
      .def_readwrite("k1", &ria::Bm25Params::k1)
      .def_readwrite("b", &ria::Bm25Params::b);
  pybind11::class_<ria::SearchResult>(m, "SearchResult")
      .def_readonly("doc", &ria::SearchResult::doc)
      .def_readonly("score", &ria::SearchResult::score);
  m.def("bm25_search", &ria::bm25_search,
     pybind11::arg("index"), pybind11::arg("query"), pybind11::arg("k") = 10,
     pybind11::arg("params") = ria::Bm25Params{});
}
