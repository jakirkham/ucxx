#!/bin/bash
# Copyright (c) 2024-2025, NVIDIA CORPORATION.

set -euo pipefail

package_name="libucxx"
package_dir="python/libucxx"

RAPIDS_PY_CUDA_SUFFIX="$(rapids-wheel-ctk-name-gen "${RAPIDS_CUDA_VERSION}")"

rapids-logger "Generating build requirements"

rapids-dependency-file-generator \
  --output requirements \
  --file-key "py_build_${package_name}" \
  --file-key "py_rapids_build_${package_name}" \
  --matrix "cuda=${RAPIDS_CUDA_VERSION%.*};arch=$(arch);py=${RAPIDS_PY_VERSION};cuda_suffixed=true" \
| tee /tmp/requirements-build.txt

rapids-logger "Installing build requirements"
rapids-pip-retry install \
    -v \
    --prefer-binary \
    -r /tmp/requirements-build.txt

# build with '--no-build-isolation', for better sccache hit rate
# 0 really means "add --no-build-isolation" (ref: https://github.com/pypa/pip/issues/5735)
export PIP_NO_BUILD_ISOLATION=0

export SKBUILD_CMAKE_ARGS="-DUCXX_ENABLE_RMM=ON"

./ci/build_wheel.sh "${package_name}" "${package_dir}"

mkdir -p "${package_dir}/final_dist"
python -m auditwheel repair \
    --exclude "libucp.so.0" \
    --exclude librapids_logger.so \
    -w "${package_dir}/final_dist" \
    ${package_dir}/dist/*

./ci/validate_wheel.sh "${package_dir}" final_dist

RAPIDS_PY_WHEEL_NAME="${package_name}_${RAPIDS_PY_CUDA_SUFFIX}" rapids-upload-wheels-to-s3 cpp "${package_dir}/final_dist"
