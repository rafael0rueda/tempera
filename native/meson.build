# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

# The pixel loops in C: see tempera_native.c. The app runs without it, more
# slowly, so it has a home of its own and the launcher says where that is;
# and with no C compiler about, the app is built without it.
native_built = add_languages('c', required: false, native: false)
if native_built
  native_module = shared_module('tempera_native',
    'tempera_native.c',
    name_prefix: '',
    c_args: ['-O3'],
    install: true,
    install_dir: pkglibdir,
  )
endif

# Writing JPEG XL: see tempera_jxl.c. Kept apart because it needs libjxl, and
# built only where that is there; the app then opens the format but does not
# write it.
libjxl = dependency('libjxl', required: false)
libjxl_threads = dependency('libjxl_threads', required: false)
jxl_built = native_built and libjxl.found() and libjxl_threads.found()
if jxl_built
  jxl_module = shared_module('tempera_jxl',
    'tempera_jxl.c',
    name_prefix: '',
    dependencies: [libjxl, libjxl_threads],
    install: true,
    install_dir: pkglibdir,
  )
endif
