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
