// Python bindings, so the evaluation scripts can call the C++ engine directly:
//
//   import ria
//   ria.tokenize("Edge 1050 sync failed")

#include "ria/tokenizer.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

PYBIND11_MODULE(ria, m) {
  m.doc() = "Garmin firmware release impact analyzer (C++ core)";
  m.def("tokenize", &ria::tokenize, pybind11::arg("text"),
        "Split text into lowercase search terms.");
}
