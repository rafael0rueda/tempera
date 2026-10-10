# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

project('tempera', 'c',
  version: '2.1.1',
  meson_version: '>= 0.62.0',
  default_options: ['c_std=c11', 'warning_level=2'],
)

python = import('python').find_installation('python3')
gnome = import('gnome')
i18n = import('i18n')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / meson.project_name()
localedir = prefix / get_option('localedir')
pkglibdir = prefix / get_option('libdir') / meson.project_name()

subdir('native')
subdir('tempera')
subdir('data')
subdir('po')
subdir('tests')

gnome.post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
