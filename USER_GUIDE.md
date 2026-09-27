# Using Tempera

How to draw, select, save and print with Tempera, and every keyboard shortcut. For
installing and building it, see the [README](README.md).

## Contents

- [Tools and shortcuts](#tools-and-shortcuts)
- [Colours](#colours)
- [Layers](#layers)
- [Opening and saving](#opening-and-saving)
- [Exporting](#exporting)
- [Printing](#printing)
- [Zooming](#zooming)
- [What Tempera remembers](#what-tempera-remembers)
- [Crash recovery](#crash-recovery)
- [Moving the palette](#moving-the-palette)
- [Resizing the image](#resizing-the-image)
- [Resizing the canvas](#resizing-the-canvas)
- [Pasting images](#pasting-images)
- [Selecting, moving and copying](#selecting-moving-and-copying)
- [Turning and skewing a selection](#turning-and-skewing-a-selection)
- [Rotating and flipping](#rotating-and-flipping)
- [Adding text](#adding-text)
- [Keyboard and screen readers](#keyboard-and-screen-readers)
- [Interface size](#interface-size)

## Tools and shortcuts

| Tool          | Key | Notes                                                                |
| ------------- | --- | -------------------------------------------------------------------- |
| Pencil        | `P` | Hard-edged, no antialiasing                                          |
| Brush         | `B` | Soft round stroke                                                    |
| Airbrush      | `A` | Sprays dots across the brush size, and keeps spraying while held     |
| Eraser        | `E` | Paints the secondary (background) colour, or rubs back to nothing    |
| Shapes        |     | Nine shapes in one tool; see below                                   |
| Text          | `T` | Type onto the canvas in any installed font                           |
| Fill          | `F` | Flood fill, with a tolerance slider for how far it spreads           |
| Color Picker  | `K` | Picks the colour that shows under the cursor, or anywhere on screen  |
| Rectangle Select | `S` | Rectangle to move, copy or cut                                    |
| Free Select   | `Shift+S` | Any shape drawn by hand, to move, copy or cut                  |
| Magic Wand    | `M` | The pixels joined to the one clicked through near enough colours     |

Rectangle Select and Free Select share one button in the sidebar, which takes up
whichever was used last, the way Paint's Select does; the bar above the canvas picks
between the two while either is in hand.

With the **Shapes** tool in hand, the bar above the canvas shows the nine shapes in a
row. Each shape also has its own key, which picks up the tool as well.

| Shape             | Key | How to draw it                                                   |
| ----------------- | --- | ---------------------------------------------------------------- |
| Line              | `L` | Drag; `Shift` snaps it to 45° steps                              |
| Curve             | `C` | Drag a line, then drag twice to bend it (`Enter` after one bend) |
| Arrow             | `W` | Drag from tail to tip; the head grows with the size              |
| Rectangle         | `R` | Drag; `Shift` draws a square                                     |
| Rounded rectangle | `U` | Drag; `Shift` draws a square                                     |
| Ellipse           | `O` | Drag; `Shift` draws a circle                                     |
| Triangle          | `I` | Drag; `Shift` makes it as wide as it is tall                     |
| Star              | `H` | Drag; `Shift` makes it regular                                   |
| Polygon           | `G` | Click each corner; click the first one again, or the last twice  |

Every shape can be resized and moved after it is drawn, before it lands; see below.

**Outline** draws the edge in the primary colour and **Fill** fills the inside with the
secondary colour; each button shows the colour it uses. Turn on either or both — a
shape with only **Fill** has no edge line at all. At least one stays on: turning off the
last one turns the other on. The line, the arrow and the curve are all outline. The polygon and the
curve stay open for more clicks until they are finished: `Enter` lands one early, `Esc`
drops it.

A shape does not land as soon as it is drawn. It waits, with grips on it, so it can be
put right before it becomes pixels:

- The rectangle, rounded rectangle, ellipse, triangle and star sit in a dashed box with
  a grip on each corner and on the middle of each side. A corner changes both
  directions at once, a side only its own. `Shift` on a grip squares the shape up.
- The line and the arrow have a grip on each end, the curve one on each end and one at
  each bend, and the polygon one on every corner. `Shift` snaps the point being dragged
  to 45°, the same way drawing it does.
- Dragging anywhere inside the shape slides it somewhere else, and the arrow keys nudge
  it a pixel at a time — ten with `Shift`.
- The colour, size, **Outline**, **Fill** and the outline's style apply to the shape as
  it waits, so a rectangle can be recoloured, filled or dashed before it lands.

`Enter` lands the shape, `Esc` drops it, and so does `Ctrl+Z`. Picking another tool or
shape lands it, as does saving, and so does drawing somewhere else: the drag that starts
the next shape lands the one waiting. However it lands, it is a single step to undo.

Three rows of buttons after **Outline** and **Fill** set how a shape is drawn:

- **Solid**, **Dashed** or **Dotted** outline. The dashes are three line widths long
  with gaps of two, and the dots one width across, so a thick line has big dashes and a
  thin one small. This goes for every shape, the curve and the polygon too.
- For the arrow only, a head at the **End** the drag finished on, or at **Both** ends.
  The heads stay solid on a dashed arrow.
- **Smooth** or **Crisp** edges. Crisp leaves every pixel either in the shape or out of
  it, with nothing blended along the edge: what pixel art wants.

Left click draws with the primary colour, right click with the secondary one. The
palette swatches work the same way: left click sets the primary colour, right click the
secondary. `X`, or the arrows beside the two current colours, swaps them. The paint
tools show the primary colour on their icons: the pencil's point, the brush's bristles,
the spray, the drip and so on.

The bar above the canvas names the tool in hand and shows only what applies to it: the
**Size** for the pencil, brush, airbrush, eraser, shapes and text, then the shapes with
**Outline**, **Fill** and their style for the Shapes tool, **Density** for the airbrush,
**Erase to nothing** for the eraser, a **Tolerance** for the fill and the magic wand,
**Rectangle** or **Free** and **Transparent** for the selection tools, **Pick from
Screen** for the colour picker, and the font and its style for the text tool.

The size can be dragged on the slider, typed into the box beside it — `Enter`, or
clicking elsewhere, takes it — or chosen from the usual sizes in the list next to the
box: the ones a word processor offers for text, and steps that grow with the brush for
the tools that paint.

| Action                      | Shortcut                                         |
| --------------------------- | ------------------------------------------------ |
| New / Open / Save / Save As | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S`  |
| Export As                   | `Ctrl+Shift+E`                                   |
| Print                       | `Ctrl+P`                                         |
| Canvas size                 | `Ctrl+E`                                         |
| Resize image                | `Ctrl+R`                                         |
| Select all                  | `Ctrl+A`                                         |
| Cut / Copy / Paste          | `Ctrl+X` / `Ctrl+C` / `Ctrl+V`                   |
| Nudge a selection or paste  | Arrow keys (`Shift` for 10 px)                   |
| Land / discard a paste      | `Enter` / `Esc`                                  |
| Drop / clear a selection    | `Esc` / `Delete`                                 |
| Land / discard typed text   | `Ctrl+Enter` / `Esc`                             |
| Undo / Redo                 | `Ctrl+Z` / `Ctrl+Shift+Z` (or `Ctrl+Y`)          |
| Zoom in / out / 100%        | `Ctrl++` / `Ctrl+-` / `Ctrl+0`, or `Ctrl`+scroll |
| Zoom to fit                 | `Ctrl+9`                                         |
| Show pixel grid             | `Ctrl+G`                                         |
| Show layers                 | `Ctrl+L`                                         |
| New / duplicate layer       | `Ctrl+Shift+N` / `Ctrl+Shift+D`                  |
| Move layer up / down        | `Ctrl+]` / `Ctrl+[`                              |
| Layer above / below         | `Alt+]` / `Alt+[`                                |
| Merge down / rename layer   | `Ctrl+M` / `F2`                                  |
| Bold / italic / underline   | `Ctrl+B` / `Ctrl+I` / `Ctrl+U`                   |
| Smaller / bigger brush      | `[` / `]`                                        |
| Preferences                 | `Ctrl+,`                                         |
| Keyboard shortcuts          | `Ctrl+?`                                         |
| Quit                        | `Ctrl+Q`                                         |

### Customising shortcuts

The keys above are the defaults. **Keyboard Shortcuts** in the main menu (or `Ctrl+?`)
lists every shortcut: click one and press the new key, `Backspace` to remove it, or `Esc`
to leave it as it was. A key another action already uses can be moved over after a
confirmation. Crop, rotate and flip, deleting a layer or flattening the image, the outline
styles and the text alignments have no key by default but can be given one. Keys the
canvas needs — arrows, `Enter`, `Esc`, `Delete`, `Tab` — are listed but cannot be
reassigned. While a field takes typed text, such as a layer's name or a colour's hex
value, the keys without `Ctrl` stand aside, so typing an `s` types it. Changes are saved in `~/.config/tempera/settings.ini`; only keys that differ
from the defaults are stored, and **Reset All Shortcuts** puts everything back.

## Colours

The two current colours overlap, the primary in front. Clicking either opens the colour
editor. The big square sets how strong and how bright the colour is — drag in it, or
use the arrow keys, ten times as far with `Shift` — the rainbow slider under it picks
the colour itself, and **Opacity** how see-through it is: a see-through colour paints over what is
already there instead of replacing it. The colour as it was shows beside the colour as
it is now, and a hex value can be typed in as `#rgb`, `#rrggbb` or `#rrggbbaa`. A grey
leaves the rainbow slider where it was, so making it stronger again goes back to the
colour it came from. **Select** takes the colour; **Cancel**, or closing the editor, keeps the old
one.

The button beside the hex value takes a colour from anywhere on the screen, other
windows included: GNOME shows a crosshair, and the colour clicked comes back, keeping
the opacity already set. **Pick from Screen** on the colour picker's bar does the same
straight into the primary colour.

**Custom Colours** in the editor keeps colours for later: `+` keeps the colour now,
clicking a kept one takes it up, and a right-click, or `Delete`, lets it go. Sixteen can
be kept, the newest first, and they are remembered.

![The colour editor over a meadow picture: a square of purples to set how strong and bright the colour is, a rainbow slider under it, the opacity at 100%, the colour beside its hex value #9141ac with a button to pick from the screen, and ten custom colours kept below](data/screenshots/color-editor.png)

The last six colours you painted with gather under **Recent**, so a mixed colour is one
click away next time. A colour counts once something has been painted with it — a
stroke, a fill, a shape as it lands, text — not when it is only picked; the eraser does
not count.

## Layers

A picture is a stack of layers, each painted on apart from the others, the higher ones
covering the lower. **Layers**, the button in the header bar, **Show Layers** in the main
menu or `Ctrl+L` shows them in a panel on the right, the top layer first, each with a
small picture of it. A new picture has one layer, **Background**.

The tools paint on the layer picked out in the list, which a click on another row
changes; `Alt+]` and `Alt+[` pick the layer above or below. The fill and the magic wand
look at that layer only, while the colour picker takes the colour that shows, whatever
layer it is on.

- The eye beside a layer hides it or shows it again.
- **Opacity**, under the list, makes the layer in hand see-through; however far it is
  dragged, it is a single step to undo.
- A double click on a layer, `F2`, or **Rename Layer…** in the menu at the end of the
  buttons renames it.
- The buttons under the list add a new, empty layer above the one in hand
  (`Ctrl+Shift+N`), duplicate it (`Ctrl+Shift+D`), move it up (`Ctrl+]`) or down
  (`Ctrl+[`), and delete it. Dragging a row onto another moves the layer there. The last
  layer cannot be deleted.
- **Merge Down** (`Ctrl+M`) paints the layer in hand, at its opacity, onto the one
  beneath, and **Flatten Image** merges every layer that shows into one; hidden layers
  are dropped.

Every one of these is a step to undo. A paste, text or a shape still being placed shows
at the depth of the layer it will land on, and lands there before the layers change.
Resizing, rotating, flipping and cropping the image reach every layer. What is emptied,
by `Delete`, by moving a selection, or by growing the canvas, is white on the bottom
layer and see-through on the ones above it, so the layers beneath show through.

The panel stays open or closed as you left it, and opens by itself for a picture that
has more than one layer.

## Opening and saving

Images open in any format GdkPixbuf reads (PNG, JPEG, BMP, TIFF, WebP, GIF, ICO…), and
OpenRaster (`.ora`) with its layers, up to 8192 × 8192 pixels; a larger image is refused with a message rather than loaded, as
is anything that is not an ordinary file, such as a named pipe. Reading and writing
happen in the background, with a spinner in the header bar, so a large image or a slow
disk never freezes the window; you can keep drawing while a save finishes, and the file
holds the image as it was when you asked to save it.
Photos open the right way up, following the orientation the camera or phone recorded.
**Recent Files** in the main menu lists the last eight images you opened or saved; one
that can no longer be opened is taken off the list when you pick it.

Saving writes OpenRaster, PNG, JPEG, BMP, TIFF, WebP or ICO, picked by the file
extension. Only OpenRaster keeps the layers, with their names, order, opacity and
whether they show; GIMP, Krita and MyPaint open it too. The other formats get the picture
as it shows, every visible layer merged, and the first time a picture with layers is
saved that way a message says so, with a button to save the layers after all. Save As
suggests an `.ora` name for a picture with more than one layer. A name typed without one
of those extensions gets `.png` added, or `.ora` for a picture with layers — Tempera asks
first if that would replace an existing file. **Save As** to a JPEG asks for a quality from 1 to 100; `Ctrl+S`
afterwards keeps that choice without asking again, for as long as the window is open.
An image opened from a format Tempera cannot write, such as GIF, is never overwritten:
`Ctrl+S` asks where to save it, suggesting the same name as a PNG. The image is
written in full before it replaces the old file, so a save that fails, on a full disk
say, leaves the original untouched. BMP and JPEG have no transparency, so transparent
areas are saved as white; ICO files are limited to 256 × 256 pixels.

Closing a window, opening another image or starting a new one asks first when there are
unsaved changes, including a paste or typed text that has not landed yet; **Cancel**
leaves everything exactly as it was. `Ctrl+Q` closes every window, asking in each one
that has unsaved changes.

The title shows `•` while there are unsaved changes, and undoing back to the image as
it was last saved clears it again. Undo keeps up to 50 steps. Each step holds only the
part of the picture that edit changed, so brush strokes on a large photo cost little; a
step that changes the whole picture, such as a fill or a rotation, holds all of it, and
the history gives up its oldest steps rather than use more than 1 GB. Changes to the
layers themselves — hiding one, moving it, renaming it — cost next to nothing.

## Exporting

**Export As…** in the main menu (`Ctrl+Shift+E`) writes a copy of the picture as it
shows, in any of the formats above. Unlike **Save As**, the picture keeps its own file:
`Ctrl+S` goes on saving there, with the layers if it is an OpenRaster file, and the `•`
for unsaved changes stays until it does. So a picture kept as `.ora` can be shared as a
PNG or a JPEG as often as it changes. The first export suggests the picture's own folder
and name, as PNG; the next one starts where the last one went.

## Printing

**Print…** in the main menu (or `Ctrl+P`) first shows the page with the image on it.
**Fit to Page** makes the image as big as the paper allows, and **Actual Size** prints it
as big as it looks at 100% zoom, 96 pixels to the inch; an image too big for one page is
spread over several, which it says, to be laid side by side. The page turns to landscape
for a wide image, and **Portrait** and **Landscape** change that. **Print…** then opens
the system's print dialog, to choose the printer, paper and copies, or to print to a PDF.
What prints is the picture as it shows when you chose **Print…** — every visible layer
at its opacity — with any floating paste or text landed first. Tempera remembers the fit, and the printer and paper last used.

## Zooming

`Ctrl`+scroll zooms around the pointer, so whatever is under it stays put; `Ctrl++` and
`Ctrl+-` step through the usual levels between 10% and 800%, and `Ctrl+0` — or clicking
the zoom level in the status bar — goes back to 100%. `Ctrl+9` fits the whole image in
the window, which is also how an image too large for the window opens. Drag with the
middle mouse button to move around a zoomed image, or pinch on a touchpad to zoom. The
status bar has `−` and `+` buttons either side of the zoom level, and scrolling over the
level steps it up or down; the main menu has the same row, with zoom to fit beside it.
Every tool keeps working at any zoom, and from 100% up each image pixel shows as a crisp
square, which makes pixel-level touch-ups with the pencil easy. The status bar also
shows which image pixel the pointer is over, and how big the selection is.

**Show Pixel Grid** in the main menu (or `Ctrl+G`) draws a thin line between every two
pixels from 400% zoom up; further out the lines would hide the picture. The grey lines
show on light and dark colours alike, though they are faint on mid grey. The grid is
only on screen and never saved into the image.

## What Tempera remembers

The window size, the tool and shape in hand, the brush and text sizes, the font and the
text's style, the fill and magic wand tolerances, the airbrush density, whether shapes
get an outline and a fill and how they are drawn, whether selections are transparent,
whether the pixel grid and the layers panel show, both colours with the ones painted
with lately and the ones kept in the colour editor, the JPEG quality, where the palette
sits and the interface size are all kept in `~/.config/tempera/settings.ini` and put back the next
time, along with how to fit a print. The printer and paper last printed on are kept in
`~/.config/tempera/print-settings.ini`. A **New image** can start transparent instead of white.

## Crash recovery

While an image has unsaved changes, Tempera keeps a copy of it every 30 seconds in its
own data folder. Your files are never touched — only **Save** writes them. If Tempera
stops without closing, because of a crash or a power cut, the next start asks about each
image left unsaved: **Recover** opens it as unsaved changes to the file it came from,
**Discard** throws the copy away, and **Decide Later** keeps it to ask again next time.
Saving, closing a window, or choosing **Discard** when closing deletes the copy, so it
only lasts as long as the unsaved work does. A recovered image starts a fresh undo
history. The copy keeps the layers, and which one was in hand.

## Moving the palette

The colour palette sits in a column right of the canvas by default. **Palette
Position** in the main menu moves it under the tools on the left, which leaves the most
room for the image, or to a row along the bottom. The choice is remembered in
`~/.config/tempera/settings.ini`.

## Resizing the image

**Resize Image…** (`Ctrl+R`) in the main menu stretches or shrinks the whole picture, in
pixels or as a percentage. The height follows the width unless **Keep aspect ratio** is
turned off, and one `Ctrl+Z` puts the old size back. This is the picture itself; the
canvas around it is the next section.

## Resizing the canvas

Drag one of the three grips on the right, bottom and bottom-right edge of the image to
resize it by hand; the dashed outline and the size readout in the status bar follow the
pointer, and the change is applied when you let go. For an exact size, click that
readout or use **Canvas Size…** (`Ctrl+E`) in the main menu. Either way the image keeps
its top-left corner — growing the canvas adds white to the bottom layer and nothing to
the ones above, shrinking it crops every layer — and the resize can be undone with
`Ctrl+Z`.

While the select tool has a selection, its own eight handles take the place of these
grips; press `Esc` to drop the selection and get them back.

## Pasting images

`Ctrl+V` drops whatever image is on the clipboard — a screenshot, most usefully — onto
the canvas, where it floats inside a dashed outline until you decide where it goes.
Drag it into place, then press `Enter` or click anywhere outside it to stamp it down;
`Esc` or `Ctrl+Z` throws it away instead. Dragging an image file or an image from
another application onto the canvas does the same thing, and an image copied as a file
in Files pastes just as well as one copied as pixels.

If the pasted image runs off the right or bottom edge — a full-screen screenshot on a
smaller canvas usually does — the canvas grows to fit it when the paste lands, so
nothing is cropped. The one exception is the 8192 × 8192 pixel limit: whatever would
land past it is cut off, and a message says so. The size readout in the status bar counts out the size you are
heading for while the paste is still floating, and one `Ctrl+Z` afterwards takes back
both the pixels and the new canvas size.

`Ctrl+C` with nothing selected copies the whole of the layer in hand the other way, so
it can be pasted into other applications. A paste lands on the layer in hand.

## Selecting, moving and copying

Pick the select tool (`S`) and drag a rectangle over the part of the image you want; a
dashed outline marks it out. Dragging from inside that outline lifts those pixels and
carries them somewhere else — hold `Ctrl` as you start the drag to leave a copy behind
instead of moving them. The pixels float exactly like a paste does, so `Enter` or a
click outside lands them, `Esc` or `Ctrl+Z` puts them back, and moving them past the
right or bottom edge grows the canvas. A move leaves white behind on the bottom layer —
the colour the canvas is made of, not whichever colour you happen to be painting with —
and a see-through gap on a layer above it, and the whole move, the gap and the pixels in
their new place, is a single `Ctrl+Z`.

Because a drag that starts inside the rectangle moves it, press `Esc` first when what
you want is to select a different area that overlaps the current one.

The lasso (`Shift+S`) selects any shape: hold the button down and draw around what you
want, and letting go closes the outline back to where it began. Everything above then
follows that outline rather than the rectangle around it: only the pixels inside it
move, copy, cut or clear, a move leaves a gap of the same shape, and the pixels copied
to the clipboard are transparent outside it. **Crop to Selection** keeps the rectangle
around the outline and makes what lies outside the outline transparent. The outline is
hard-edged, taking whole pixels, so nothing half-moved is left along its edge.

With the select tool or the lasso in hand, a selection has eight handles around it. Dragging one
stretches or squashes the selected pixels, again with `Ctrl` to leave the original in
place; the stretch keeps hard edges hard rather than blurring them. A floating paste
has the same handles, so a screenshot can be scaled down before it lands. The arrow
keys nudge a selection or a paste by one pixel, or ten with `Shift`, lifting the
selection the first time the same way a drag would.

The magic wand (`M`) selects by colour: a click takes the pixel under it and every pixel
joined to it through colours near enough its own, on the layer in hand. **Tolerance**
says how near; at 0 only the exact colour counts. What it takes moves, copies, cuts,
clears and crops like any selection, and the marching ants run along the edges of its
pixels.

**Transparent**, in the bar while a selection tool is in hand, leaves the secondary
colour out of whatever is moved or pasted, as in Paint, where it is the background
colour: a shape cut from a white background drops onto something else without a white
box around it. The button wears the colour it leaves out, and turning it on, or picking
another secondary colour, while something floats shows the change at once.

`Ctrl+A` selects the whole image and switches to the select tool, and **Crop to
Selection** in the main menu cuts the canvas down to just the selected rectangle.

The selection outlives the tool that made it: `Ctrl+C` copies just that rectangle
rather than the whole layer, `Ctrl+X` cuts it out and `Delete` clears it — to white on
the bottom layer, to nothing on the others — without touching the clipboard, whichever
tool is in hand. Only the selection tools pick the pixels up, though — with a brush selected you paint over them as usual. `Esc`, or
a click outside the selection while the select tool or the lasso is in hand, drops it.

## Turning and skewing a selection

A selection, or a paste, has a round grip on a short stalk above it — below it when
there is no room above — to turn it by. Dragging the grip turns it about its middle as
the pointer goes round; with `Shift` it turns in steps of 15°. Once it floats, `Ctrl` on
the grip in the middle of a side skews it instead: that side slides along itself while
the side facing it stays put. On a selection not yet lifted, `Ctrl` still means to leave
a copy behind.

Turned or skewed, the grips turn with it and stretch it along its own sides. It lands
the same way as before — `Enter`, a click outside, another tool — resampled smoothly,
since its pixels no longer line up with the image's; whatever ends up above or left of
the canvas is lost, as the canvas only grows right and down.

## Rotating and flipping

The row of buttons under **Crop to Selection** in the main menu turns the whole image a
quarter turn either way — swapping its width and height — or mirrors it left to right or
top to bottom; `Ctrl+Shift+R` turns it counterclockwise. A paste or text still floating
is landed first and any selection is dropped; each is a single step to undo.

## Adding text

Pick the text tool (`T`) and click where the text should start: a dashed box appears
with a caret in it, and what you type is drawn straight onto the canvas in the primary
colour — right-click instead to type in the secondary one. The **Size** that sets the
brush sets the text instead while the text tool is selected, in points, and the button
after it, which shows the font's name, picks the family and style. Both apply to the box you are typing in
as well as the next one, so you can resize the text you are looking at.

The rest of the bar styles the text: **B**, **I**, **U** and **S** make it bold (`Ctrl+B`),
italic (`Ctrl+I`), underlined (`Ctrl+U`) or struck through; the three alignment buttons
line its lines up left, in the middle or right; and **Background** puts it on a box of
the other colour, the secondary one for text begun with the left button, as the inside
of a filled shape is. As in Paint, a style is for all of the text in a box, and changing
it while typing changes the text you are looking at. Slanted letters that reach past the
box land whole.

The text stays editable until it lands. `Enter` starts a new line, the arrow keys,
`Home`, `End`, `Backspace` and `Delete` work as usual, and clicking inside the box puts
the caret where you clicked. Dragging the box moves it. Nothing is written into the
image until you press `Ctrl+Enter`, click outside the box, or switch to another tool;
`Esc` or `Ctrl+Z` throws it away instead.

Input methods work too: while one is still composing, say Japanese before it is
converted, the unfinished word shows underlined at the caret. Only what the input method
has finished lands in the image.

Once it lands the text is pixels like everything else — there is no going back to
editing it, only `Ctrl+Z`. Text that runs off the right or bottom edge grows the canvas
the same way a paste does. Because the image should look the same everywhere, the text
is laid out at 96 dpi regardless of the desktop's text scaling, so a size of 24 always
gives the same pixels.

## Keyboard and screen readers

Every tool, menu item and file action has a keyboard shortcut, and `Tab` moves through
the tool options, the tools, the palette and the status bar. The colour swatches are buttons: `Tab` to
one and press `Enter` or `Space` to make it the primary colour, then `X` to swap the
primary and secondary colours around. With a pointer, right-clicking a swatch sets the
secondary colour directly.

Buttons that show only an icon carry a name for screen readers, the swatches announce
their colour by name ("Light blue (#99c1f1)"), and the canvas announces its size.

## Interface size

**Preferences** in the main menu (or `Ctrl+,`) has an **Interface Size** of 100%, 125%,
150% or 200%. It makes the whole app bigger at once: text, menus and dialogs, icons,
the tool buttons, the colour swatches, checkboxes and sliders, and the grips for
resizing the canvas. The change applies straight away to every open window and is
remembered. It adds to GNOME's own **Large Text** setting rather than replacing it; the
image itself and the file dialogs, which the desktop draws, keep their usual size. When
the window is too small for everything at a big size, the tool options, the sidebar and
the palette scroll.

![Tempera at 150% interface size, with the Shapes tool selected and its nine shapes, the size, the Outline and Fill buttons and the outline styles in the bar above the canvas, and a filled star with a dashed outline just drawn on a meadow, waiting in a dashed box with a grip on each corner and side](data/screenshots/interface-size.png)
