# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

project('tempera',
  version: '1.3.0',
  meson_version: '>= 0.62.0',
)

python = import('python').find_installation('python3')
gnome = import('gnome')
i18n = import('i18n')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / meson.project_name()
localedir = prefix / get_option('localedir')

subdir('tempera')
subdir('data')
subdir('po')
subdir('tests')

gnome.post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
