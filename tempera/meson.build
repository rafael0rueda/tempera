# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

python.install_sources(
  files(
    '__init__.py',
    '__main__.py',
    'canvas.py',
    'clipboard.py',
    'color.py',
    'document.py',
    'file_io.py',
    'i18n.py',
    'interface_size.py',
    'main.py',
    'preferences.py',
    'printing.py',
    'recent_files.py',
    'recovery.py',
    'selection.py',
    'settings.py',
    'shortcuts.py',
    'shortcuts_dialog.py',
    'text.py',
    'tool_icon.py',
    'window.py',
  ),
  subdir: 'tempera',
)

python.install_sources(
  files(
    'tools/__init__.py',
    'tools/airbrush.py',
    'tools/arrow.py',
    'tools/base.py',
    'tools/brush.py',
    'tools/curve.py',
    'tools/ellipse.py',
    'tools/eraser.py',
    'tools/fill.py',
    'tools/lasso.py',
    'tools/line.py',
    'tools/pencil.py',
    'tools/picker.py',
    'tools/polygon.py',
    'tools/rectangle.py',
    'tools/rounded_rectangle.py',
    'tools/select.py',
    'tools/shapes.py',
    'tools/star.py',
    'tools/text.py',
    'tools/triangle.py',
  ),
  subdir: 'tempera/tools',
)

launcher = configuration_data()
launcher.set('PYTHON', python.full_path())
launcher.set('PYTHON_DIR', python.get_install_dir())
launcher.set('PKGDATADIR', pkgdatadir)
launcher.set('LOCALEDIR', localedir)

configure_file(
  input: 'tempera.in',
  output: 'tempera',
  configuration: launcher,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)
