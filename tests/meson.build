# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

pytest = find_program('pytest', required: false)
if pytest.found()
  # The helper just built, not whatever build_native.sh left in the source tree.
  if native_built
    environment = {'TEMPERA_NATIVE': native_module.full_path(), 'TEMPERA_REQUIRE_NATIVE': '1'}
    built = [native_module]
  else
    environment = {'TEMPERA_NATIVE': 'off'}
    built = []
  endif
  test(
    'pytest',
    pytest,
    args: [meson.project_source_root() / 'tests'],
    workdir: meson.project_source_root(),
    env: environment,
    depends: built,
  )
endif
