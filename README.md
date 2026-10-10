# Tempera

A straightforward raster paint application for Fedora / GNOME, in the spirit of the
classic Windows Paint. Built with GTK4 and libadwaita, it follows the system light/dark
preference and accent colour automatically, and works entirely offline.

![Tempera's main window: the brush's options in a bar under the header, the tools on the left with the brush selected, a painted meadow with a house, a tree and the sun on the canvas, the colour palette in a column beside it, and the layers panel on the right listing the picture's five layers](data/screenshots/main-window.png)

## Features

- Layers: add, duplicate, reorder, hide, fade, merge and flatten them, kept in
  OpenRaster files that GIMP and Krita open too, and exported as PNG or JPEG copies
- Pencil, brush, airbrush and eraser, which can rub back to transparency
- Nine shapes — line, curve, arrow, rectangle, rounded rectangle, ellipse, triangle, star
  and polygon — filled or outlined, solid, dashed or dotted, with smooth or crisp edges,
  and resized or moved by their grips before they land
- Text in any installed font: bold, italic, underlined or struck through, aligned, and
  on a box of its own if wanted
- Flood fill with a tolerance, and a colour picker for the canvas or anywhere on screen
- A colour editor with hex values, opacity and colours kept for later, and the colours
  painted with lately beside the palette
- Rectangle, free-form and magic wand selection to move, copy, cut, stretch, turn, skew
  or crop to, with the background colour left out if wanted
- Paste screenshots and drop images onto the canvas; resize, rotate or flip the image
- Zoom from 10% to 800%, drawn by the graphics card, with crisp pixels and an optional
  pixel grid
- Printing, fitted to the page or at actual size, with a preview
- Unsaved work, layers and all, kept safe and offered back after a crash
- Keyboard shortcuts you can change, and an interface size up to 200%

The [user guide](USER_GUIDE.md) explains every tool, option and shortcut.

## Installing a release

Each [release](https://github.com/rafael0rueda/tempera/releases) has a Flatpak bundle
attached. Download `Tempera-<version>-x86_64.flatpak` and install it for your user:

```
flatpak install --user Tempera-2.1.1-x86_64.flatpak
```

It runs on the GNOME 50 runtime, which Flatpak offers to fetch from Flathub if you do
not have it yet. Installing a newer bundle the same way updates it.

## Requirements

Fedora Workstation 43 or newer (Tempera needs libadwaita 1.8):

```
sudo dnf install python3-gobject python3-cairo gtk4 libadwaita
```

To build and install, also: `sudo dnf install meson ninja-build gcc`

## Running from source

No build step is needed for development:

```
python3 -m tempera
```

Optionally pass an image to open: `python3 -m tempera picture.png`

Filling and the magic wand are some ten times quicker on photos with a small C helper,
which a meson build compiles and installs. Tempera works the same without it, so from
source it is optional; `build-aux/build_native.sh` compiles it next to the Python (it
needs `gcc`), and `TEMPERA_NATIVE=off` runs without it.

## Running the tests

The pytest suite covers the drawing, file, clipboard, selection, text and undo logic,
and checks that every module and icon the app uses gets installed. The window tests
create real widgets, so run it inside your desktop session, or under `xvfb-run -a`
without one; no window ever appears.

```
sudo dnf install python3-pytest
python3 -m pytest
```

From a meson build directory, `meson test -C builddir` runs the same suite.

The tests that hold the C helper and the Python to the same answers are skipped until
the helper is built; set `TEMPERA_REQUIRE_NATIVE=1` to have its absence fail instead.

GitHub Actions runs the same suite on Fedora for every push and pull request,
validates the desktop entry and metainfo, and builds the Flatpak
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Installing

```
meson setup builddir --prefix=/usr/local
meson install -C builddir
```

This installs the `tempera` launcher, the desktop entry, the app icon and the app data
(stylesheet plus tool icons). The launcher points at the installed data directory;
`TEMPERA_DATA_DIR` overrides it if you need to.

## Flatpak

`flatpak/io.github.rafael0rueda.Tempera.json` builds against `org.gnome.Platform` 50. It needs
`flatpak-builder` and the GNOME SDK, which are not installed by default:

```bash
sudo dnf install flatpak-builder
flatpak install flathub org.gnome.Sdk//50 org.gnome.Platform//50
flatpak-builder --user --install --force-clean build flatpak/io.github.rafael0rueda.Tempera.json
```

The manifest deliberately grants no network permission — the app has no reason to
reach the network, and the sandbox enforces that. It grants no filesystem access
either: Tempera only sees the images you pick in the Open and Save dialogs, drop onto the
canvas or copy from Files, all of which reach it through the desktop's file portal.

## Translations

Tempera is in English, but every string a person reads is marked for translation, and
the desktop entry and app metadata are translated at build time. [po/README.md](po/README.md)
explains how to add a language; no code has to change.

## Privacy

Tempera works entirely offline: no network, no update checks, no telemetry, no accounts.
The Flatpak has no network permission, so the sandbox enforces it.

Saved images carry no metadata — no EXIF, no camera details, no location — even when the
image you opened had them. The orientation an EXIF tag asked for is applied to the pixels
as the photo opens, so nothing is lost by dropping the rest.

The crash-recovery copies of unsaved images live in `~/.local/share/tempera/recovery/`
(`~/.var/app/io.github.rafael0rueda.Tempera/data/tempera/recovery/` for the Flatpak),
readable only by you, and are deleted as soon as the image is saved or its changes are
thrown away.

**Recent Files** keeps the last eight names in `~/.config/tempera/recent-files.txt`. It
follows GNOME's **Settings › Privacy › File History** switch: with that off, nothing is
recorded and the list stays empty. **Clear Recent Files** in the menu empties it at any
time.

[SECURITY.md](SECURITY.md) explains how to report a security problem.

## Theming

libadwaita does the work: the app follows the system colour scheme and accent colour
with no configuration. The only custom styling lives in `data/style.css`, written
against libadwaita's named colours (`@accent_bg_color`, `@headerbar_bg_color`, …) rather
than fixed values, so re-theming the app means editing that one file. Tool icons are
symbolic SVGs in `data/icons/`, so they recolour with the theme too.

## Licence

Tempera is free software under the GNU General Public License, version 3 or later; the
full text is in [LICENSE](LICENSE). Source and data files carry `SPDX-License-Identifier`
headers. The AppStream metainfo file is CC0-1.0, as AppStream requires of metadata.
