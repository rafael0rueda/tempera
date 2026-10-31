#!/bin/sh
# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

# Compile the C helper next to the Python it speeds up, for running Tempera
# and its tests from the source tree. A meson build does this by itself.
set -e
cd "$(dirname "$0")/.."
${CC:-cc} -O3 -fPIC -shared -std=c11 -Wall -Wextra -Wpedantic \
  -o tempera/tempera_native.so native/tempera_native.c
echo "Built tempera/tempera_native.so"

# Writing JPEG XL needs libjxl to build against; without it the app only reads the format.
if pkg-config --exists libjxl libjxl_threads; then
  # shellcheck disable=SC2046
  ${CC:-cc} -O3 -fPIC -shared -std=c11 -Wall -Wextra -Wpedantic \
    -o tempera/tempera_jxl.so native/tempera_jxl.c $(pkg-config --cflags --libs libjxl libjxl_threads)
  echo "Built tempera/tempera_jxl.so"
else
  echo "Left out tempera/tempera_jxl.so: no libjxl to build against"
fi
