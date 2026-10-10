# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

# The pixel loops in C: see tempera_native.c. The app runs without it, more
# slowly, so it has a home of its own and the launcher says where that is.
shared_module('tempera_native',
  'tempera_native.c',
  name_prefix: '',
  c_args: ['-O3'],
  install: true,
  install_dir: pkglibdir,
)
