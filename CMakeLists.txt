cmake_minimum_required(VERSION 3.25)
project(release_impact_analyzer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(RIA_BUILD_TESTS "Build unit tests" ON)
option(RIA_BUILD_PYTHON "Build the Python module (needs pybind11)" OFF)
option(RIA_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(RIA_SANITIZE "Build with AddressSanitizer and UBSan" OFF)

# ASan cannot be loaded into an already-running Python process via dlopen.
if(RIA_SANITIZE AND RIA_BUILD_PYTHON)
  message(FATAL_ERROR "RIA_SANITIZE and RIA_BUILD_PYTHON cannot be combined; use separate build directories.")
endif()

# Flags shared by every target in this project.
add_library(ria_options INTERFACE)
target_compile_options(ria_options INTERFACE -Wall -Wextra -Wpedantic -Wshadow -Wconversion)
if(RIA_WARNINGS_AS_ERRORS)
  target_compile_options(ria_options INTERFACE -Werror)
endif()
if(RIA_SANITIZE)
  target_compile_options(ria_options INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(ria_options INTERFACE -fsanitize=address,undefined)
endif()

# Core library: everything the CLI, tests and Python module share.
add_library(ria_core
  src/inverted_index.cpp
  src/tokenizer.cpp
)
target_include_directories(ria_core PUBLIC include)
target_link_libraries(ria_core PRIVATE ria_options)
set_target_properties(ria_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_executable(ria apps/ria_cli.cpp)
target_link_libraries(ria PRIVATE ria_core ria_options)

if(RIA_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/releases/download/v1.17.0/googletest-1.17.0.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP ON
    SYSTEM  # treat gtest headers as system headers so our -Werror ignores them
  )
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  enable_testing()
  add_executable(ria_tests
    tests/test_inverted_index.cpp
    tests/test_tokenizer.cpp
  )
  target_link_libraries(ria_tests PRIVATE ria_core ria_options GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(ria_tests)
endif()

if(RIA_BUILD_PYTHON)
  find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(ria_py python/bindings.cpp)
  set_target_properties(ria_py PROPERTIES OUTPUT_NAME ria)
  target_link_libraries(ria_py PRIVATE ria_core)
endif()
