# Exercise the real CLI, including values that previously threw or wrapped.
foreach(k IN ITEMS -1 nope 2x "" 184467440737095516160)
  execute_process(COMMAND "${RIA}" "${CORPUS}" "${k}"
                  RESULT_VARIABLE status ERROR_VARIABLE error OUTPUT_VARIABLE output)
  if(NOT status EQUAL 2 OR NOT error MATCHES "nonnegative integer")
    message(FATAL_ERROR "Invalid k=${k}: status=${status}, stderr=${error}")
  endif()
endforeach()
foreach(k IN ITEMS 0 2)
  execute_process(COMMAND "${RIA}" "${CORPUS}" "${k}" INPUT_FILE "${CORPUS}"
                  RESULT_VARIABLE status ERROR_VARIABLE error OUTPUT_VARIABLE output)
  if(NOT status EQUAL 0 OR NOT error MATCHES "indexed")
    message(FATAL_ERROR "Valid k=${k}: status=${status}, stderr=${error}")
  endif()
endforeach()
