# =================================================================================
# SPDX-FileCopyrightText: Copyright (c) 2022-2025, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: BSD 3-Clause License
# =================================================================================

cmake_minimum_required(VERSION 3.26.4 FATAL_ERROR)

include(../fetch_rapids.cmake)
include(rapids-cmake)
include(rapids-cpm)
include(rapids-export)
include(rapids-find)

file(READ "${CMAKE_CURRENT_LIST_DIR}/../VERSION" _version_contents)
if(_version_contents MATCHES "^([0-9]+)\\.([0-9]+)\\.([0-9]+).*$")
  set(libucxx_version "${CMAKE_MATCH_1}.${CMAKE_MATCH_2}.${CMAKE_MATCH_3}")
else()
  string(REPLACE "\n" "\n  " _version_contents_formatted "${_version_contents}")
  message(FATAL_ERROR "Could not determine ucxx version. Contents of VERSION file:\n  ${_version_contents_formatted}")
endif()

project(
  UCXX
  VERSION ${libucxx_version}
  LANGUAGES C CXX
)

# Needed because GoogleBenchmark changes the state of FindThreads.cmake, causing subsequent runs to
# have different values for the `Threads::Threads` target. Setting this flag ensures
# `Threads::Threads` is the same value in first run and subsequent runs.
set(THREADS_PREFER_PTHREAD_FLAG ON)

# ##################################################################################################
# * build options ---------------------------------------------------------------------------------

option(BUILD_TESTS "Configure CMake to build tests" ON)
option(BUILD_BENCHMARKS "Configure CMake to build benchmarks" OFF)
option(BUILD_EXAMPLES "Configure CMake to build examples" OFF)
option(BUILD_SHARED_LIBS "Build UCXX shared libraries" ON)
option(UCXX_ENABLE_RMM "Enable support for CUDA multi-buffer transfer with RMM" OFF)
option(DISABLE_DEPRECATION_WARNINGS "Disable warnings generated from deprecated declarations." OFF)

message(VERBOSE "UCXX: Configure CMake to build tests: ${BUILD_TESTS}")
message(VERBOSE "UCXX: Configure CMake to build benchmarks: ${BUILD_BENCHMARKS}")
message(VERBOSE "UCXX: Configure CMake to build examples: ${BUILD_EXAMPLES}")
message(VERBOSE "UCXX: Build UCXX shared libraries: ${BUILD_SHARED_LIBS}")
message(VERBOSE "UCXX: Enable support for CUDA multi-buffer transfer with RMM: ${UCXX_ENABLE_RMM}")
message(
  VERBOSE
  "UCXX: Disable warnings generated from deprecated declarations: ${DISABLE_DEPRECATION_WARNINGS}"
)

# Set a default build type if none was specified
rapids_cmake_build_type("Release")
set(LIBUCXX_BUILD_TESTS ${BUILD_TESTS})
set(LIBUCXX_BUILD_BENCHMARKS ${BUILD_BENCHMARKS})
set(LIBUCXX_BUILD_EXAMPLES ${BUILD_EXAMPLES})

set(UCXX_CXX_FLAGS -Wall -Wattributes -Werror -Wextra -Wsign-conversion -Wno-missing-field-initializers)
set(UCXX_CXX_DEFINITIONS "")

# Set RMM logging level
set(RMM_LOGGING_LEVEL
    "INFO"
    CACHE STRING "Choose the logging level."
)
set_property(
  CACHE RMM_LOGGING_LEVEL PROPERTY STRINGS "TRACE" "DEBUG" "INFO" "WARN" "ERROR" "CRITICAL" "OFF"
)
message(VERBOSE "UCXX: RMM_LOGGING_LEVEL = '${RMM_LOGGING_LEVEL}'.")

# ##################################################################################################
# * conda environment -----------------------------------------------------------------------------
rapids_cmake_support_conda_env(conda_env MODIFY_PREFIX_PATH)

# ##################################################################################################
# * compiler options ------------------------------------------------------------------------------
# Due to https://github.com/openucx/ucx/issues/9614, we cannot export the ucx
# dependency because users would then have no control over whether ucx is found
# multiple times, causing potential configure errors. Therefore, we use a raw
# find_package call instead of rapids_find_package and skip exporting the ucx
# dependency. Consumers of ucxx must find ucx themselves. Once we move the
# minimum version to UCX 1.16 we can remove the above find_package in favor of
# the commented out lines below. For the same reason, we must also gate this
# find_package call behind a check for the target already existing so that
# consumers can use tools like CPM.cmake to either find or build ucxx from
# source if it cannot be found (i.e. both cases must allow prior finding of
# ucx).
if(NOT TARGET ucx::ucp)
  find_package(ucx REQUIRED)
endif()
#rapids_find_package(
#  ucx REQUIRED
#  BUILD_EXPORT_SET ucxx-exports
#  INSTALL_EXPORT_SET ucxx-exports
#)

# ##################################################################################################
# * dependencies ----------------------------------------------------------------------------------

# find Threads (needed by ucxxtestutil)
rapids_find_package(
  Threads REQUIRED
  BUILD_EXPORT_SET ucxx-exports
  INSTALL_EXPORT_SET ucxx-exports
)

# add third party dependencies using CPM
rapids_cpm_init()
# find rmm
if(UCXX_ENABLE_RMM)
  include(cmake/thirdparty/get_rmm.cmake)
endif()
# find or install GoogleTest
if(BUILD_TESTS)
  include(${rapids-cmake-dir}/cpm/gtest.cmake)

  # Find or install GoogleTest
  rapids_cpm_gtest(BUILD_STATIC)
endif()

# ##################################################################################################
# * library targets -------------------------------------------------------------------------------

# Build main library
add_library(
  ucxx
  src/address.cpp
  src/buffer.cpp
  src/component.cpp
  src/config.cpp
  src/context.cpp
  src/delayed_submission.cpp
  src/endpoint.cpp
  src/header.cpp
  src/inflight_requests.cpp
  src/internal/request_am.cpp
  src/listener.cpp
  src/log.cpp
  src/memory_handle.cpp
  src/remote_key.cpp
  src/request.cpp
  src/request_am.cpp
  src/request_data.cpp
  src/request_endpoint_close.cpp
  src/request_flush.cpp
  src/request_helper.cpp
  src/request_mem.cpp
  src/request_stream.cpp
  src/request_tag.cpp
  src/request_tag_multi.cpp
  src/worker.cpp
  src/worker_progress_thread.cpp
  src/utils/callback_notifier.cpp
  src/utils/file_descriptor.cpp
  src/utils/python.cpp
  src/utils/sockaddr.cpp
  src/utils/ucx.cpp
)

set_target_properties(
  ucxx
  PROPERTIES BUILD_RPATH "\$ORIGIN"
             INSTALL_RPATH "\$ORIGIN"
             # set target compile options
             CXX_STANDARD 17
             CXX_STANDARD_REQUIRED ON
             POSITION_INDEPENDENT_CODE ON
             INTERFACE_POSITION_INDEPENDENT_CODE ON
)

target_compile_options(
  ucxx PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:${UCXX_CXX_FLAGS}>"
)

# Specify include paths for the current target and dependents
target_include_directories(
  ucxx
  PUBLIC "$<BUILD_INTERFACE:${UCXX_SOURCE_DIR}/include>"
  PRIVATE "$<BUILD_INTERFACE:${UCXX_SOURCE_DIR}/src>"
  INTERFACE "$<INSTALL_INTERFACE:include>"
)

target_compile_definitions(
  ucxx PUBLIC "$<$<COMPILE_LANGUAGE:CXX>:${UCXX_CXX_DEFINITIONS}>"
)

# Enable RMM if necessary
if(UCXX_ENABLE_RMM)
    target_link_libraries(ucxx
      PUBLIC rmm::rmm
    )

    # Define spdlog level
    target_compile_definitions(ucxx PUBLIC UCXX_ENABLE_RMM "RMM_LOG_ACTIVE_LEVEL=RAPIDS_LOGGER_LEVEL_${RMM_LOGGING_LEVEL}")
endif()

# Specify the target module library dependencies
target_link_libraries(ucxx PUBLIC ucx::ucp)


# Add Conda library, and include paths if specified
if(TARGET conda_env)
  target_link_libraries(ucxx PRIVATE conda_env)
endif()

add_library(ucxx::ucxx ALIAS ucxx)

# ##################################################################################################
# * tests and benchmarks --------------------------------------------------------------------------
# ##################################################################################################

# ##################################################################################################
# * add tests -------------------------------------------------------------------------------------

if(LIBUCXX_BUILD_TESTS)
  # include CTest module -- automatically calls enable_testing()
  include(CTest)

  # Always print verbose output when tests fail if run using `make test`.
  list(APPEND CMAKE_CTEST_ARGUMENTS "--output-on-failure")
  add_subdirectory(tests)
endif()

# ##################################################################################################
# * add benchmarks --------------------------------------------------------------------------------

if(LIBUCXX_BUILD_BENCHMARKS)
  add_subdirectory(benchmarks)
endif()

# ##################################################################################################
# * add examples ----------------------------------------------------------------------------------

if(LIBUCXX_BUILD_EXAMPLES)
  add_subdirectory(examples)
endif()

# ##################################################################################################
# * install targets -------------------------------------------------------------------------------
rapids_cmake_install_lib_dir(lib_dir)
include(CPack)
include(GNUInstallDirs)

set(CMAKE_INSTALL_DEFAULT_COMPONENT_NAME ucxx)
set(_components_export_string)

install(
  TARGETS ucxx
  DESTINATION ${lib_dir}
  EXPORT ucxx-exports
)

install(DIRECTORY ${UCXX_SOURCE_DIR}/include/ucxx
                  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

set(doc_string
    [=[
Provide targets for the ucxx library.

UCXX is a C++ interface for the UCX communication framework. It aims to provide
a high-level API for the UCP layer, encompassing both transparent lifetime
management of objects and thread-safety.


Imported Targets
^^^^^^^^^^^^^^^^

If ucxx is found, this module defines the following IMPORTED GLOBAL
targets:

 ucxx::ucxx             - The main ucxx library.
    ]=]
)

rapids_export(
  INSTALL ucxx
  EXPORT_SET ucxx-exports ${_components_export_string}
  GLOBAL_TARGETS ucxx
  NAMESPACE ucxx::
  DOCUMENTATION doc_string
)

# ##################################################################################################
# * build export -------------------------------------------------------------------------------
rapids_export(
  BUILD ucxx
  EXPORT_SET ucxx-exports ${_components_export_string}
  GLOBAL_TARGETS ucxx
  NAMESPACE ucxx::
  DOCUMENTATION doc_string
)

# ##################################################################################################
# * make documentation ----------------------------------------------------------------------------

# doc targets for UCXX
add_custom_command(
  OUTPUT UCXX_DOXYGEN
  WORKING_DIRECTORY ${UCXX_SOURCE_DIR}/doxygen
  COMMAND ${CMAKE_COMMAND} -E env "UCXX_VERSION=${libucxx_version}" doxygen Doxyfile
  VERBATIM
  COMMENT "Custom command for building ucxx doxygen docs."
)

add_custom_target(
  docs_ucxx
  DEPENDS UCXX_DOXYGEN
  COMMENT "Custom command for building ucxx doxygen docs."
)

# ##################################################################################################
# * make gdb helper scripts ------------------------------------------------------------------------

# build pretty-printer load script
if(rmm_SOURCE_DIR)
  configure_file(scripts/load-pretty-printers.in load-pretty-printers @ONLY)
endif()
