// Command-line entry point. For now it tokenizes each line of stdin so the
// tokenizer can be tried by hand; it will grow into the search CLI.
//
//   echo "Edge 1050 won't sync after 31.20" | ./build/ria

#include "ria/tokenizer.h"

#include <iostream>
#include <string>

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    const auto tokens = ria::tokenize(line);
    for (std::size_t i = 0; i < tokens.size(); ++i) {
      std::cout << (i ? " | " : "") << tokens[i];
    }
    std::cout << '\n';
  }
  return 0;
}
