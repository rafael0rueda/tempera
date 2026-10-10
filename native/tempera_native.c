/* SPDX-FileCopyrightText: 2026 Rafael Rueda
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The loops over every pixel that are slow from Python: the search a fill and
 * the magic wand make, and the border of what the wand picked.
 *
 * Plain C that knows nothing of Python or cairo. tempera/native.py loads it
 * and hands it the memory of surfaces Tempera made itself, with their sizes;
 * tempera/regions.py and tempera/selection.py do the same work without it,
 * more slowly, and the tests hold the two to the same answers.
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* A rectangle as [left, right) by [top, bottom), and how many pixels it is about. */
typedef struct {
    int32_t left, top, right, bottom;
    int64_t count;
} Bounds;

/* One row of a mask: 1 for each pixel with every channel within `tolerance`
 * of the target's, 0 for the rest. A plain loop, so that the compiler does
 * sixteen or more pixels at a time. */
static void
match_row (const uint8_t *restrict row, const uint8_t *target, int tolerance,
           uint8_t *restrict matched, int width)
{
    const int t0 = target[0], t1 = target[1], t2 = target[2], t3 = target[3];
    for (int x = 0; x < width; x++) {
        const uint8_t *pixel = row + x * 4;
        matched[x] = (abs (pixel[0] - t0) <= tolerance) & (abs (pixel[1] - t1) <= tolerance)
                   & (abs (pixel[2] - t2) <= tolerance) & (abs (pixel[3] - t3) <= tolerance);
    }
}

/* The pixels joined to (x, y) through pixels of near enough its colour, as
 * 255 in `mask`, which must come in all zero: one byte a pixel, `mask_stride`
 * apart. Returns 0, or -1 when there is no memory for the search.
 *
 * A scanline search. While it runs, 1 in the mask is a pixel that matches
 * and has not been reached; rows are only looked at as the search gets to
 * them, so a small region in a large picture reads little of it. */
int
tempera_flood (const uint8_t *pixels, int stride, int width, int height,
               int x, int y, int tolerance,
               uint8_t *mask, int mask_stride, Bounds *found)
{
    Bounds bounds = { width, height, 0, 0, 0 };
    uint8_t target[4];
    size_t room = 1024, waiting = 0;
    int32_t *seeds;
    uint8_t *read;

    *found = bounds;
    if (x < 0 || y < 0 || x >= width || y >= height)
        return 0;
    seeds = malloc (room * 2 * sizeof (int32_t));
    read = calloc (height, 1);
    if (seeds == NULL || read == NULL) {
        free (seeds);
        free (read);
        return -1;
    }
    memcpy (target, pixels + (size_t) y * stride + (size_t) x * 4, 4);

#define READ_ROW(row) \
    do { \
        if (!read[row]) { \
            read[row] = 1; \
            match_row (pixels + (size_t) (row) * stride, target, tolerance, \
                       mask + (size_t) (row) * mask_stride, width); \
        } \
    } while (0)

    READ_ROW (y);
    seeds[0] = x;
    seeds[1] = y;
    waiting = 1;
    while (waiting > 0) {
        int seed_x, seed_y, left, right;
        uint8_t *row;

        waiting--;
        seed_x = seeds[waiting * 2];
        seed_y = seeds[waiting * 2 + 1];
        row = mask + (size_t) seed_y * mask_stride;
        if (row[seed_x] != 1)
            continue;

        left = seed_x;
        right = seed_x + 1;
        while (left > 0 && row[left - 1] == 1)
            left--;
        while (right < width && row[right] == 1)
            right++;
        memset (row + left, 255, right - left);
        bounds.count += right - left;
        if (left < bounds.left) bounds.left = left;
        if (right > bounds.right) bounds.right = right;
        if (seed_y < bounds.top) bounds.top = seed_y;
        if (seed_y + 1 > bounds.bottom) bounds.bottom = seed_y + 1;

        for (int step = -1; step <= 1; step += 2) {
            int beside_y = seed_y + step, scan = left;
            const uint8_t *beside;

            if (beside_y < 0 || beside_y >= height)
                continue;
            READ_ROW (beside_y);
            beside = mask + (size_t) beside_y * mask_stride;
            /* One seed for each run of matching pixels alongside the one just found. */
            while (scan < right) {
                const uint8_t *hit = memchr (beside + scan, 1, right - scan);
                if (hit == NULL)
                    break;
                scan = (int) (hit - beside);
                if (waiting == room) {
                    int32_t *grown = realloc (seeds, room * 2 * 2 * sizeof (int32_t));
                    if (grown == NULL) {
                        free (seeds);
                        free (read);
                        return -1;
                    }
                    seeds = grown;
                    room *= 2;
                }
                seeds[waiting * 2] = scan;
                seeds[waiting * 2 + 1] = beside_y;
                waiting++;
                while (scan < right && beside[scan] == 1)
                    scan++;
            }
        }
    }
#undef READ_ROW

    /* What matched but was never reached is no part of it. */
    for (int row_y = 0; row_y < height; row_y++) {
        uint8_t *row = mask + (size_t) row_y * mask_stride;
        if (!read[row_y])
            continue;
        for (int column = 0; column < width; column++)
            row[column] = row[column] == 255 ? 255 : 0;
    }
    free (seeds);
    free (read);
    if (bounds.count == 0)
        bounds.left = bounds.top = 0;
    *found = bounds;
    return 0;
}

/* Give the pixels the mask covers, within `where`, one colour. `changed` gets
 * the rectangle around those that were not that colour already, and how many
 * they were. */
void
tempera_fill (uint8_t *pixels, int stride, const uint8_t *mask, int mask_stride,
              const Bounds *where, const uint8_t *color, Bounds *changed)
{
    Bounds bounds = { where->right, where->bottom, where->left, where->top, 0 };
    uint32_t paint;

    memcpy (&paint, color, 4);
    for (int y = where->top; y < where->bottom; y++) {
        uint32_t *row = (uint32_t *) (pixels + (size_t) y * stride);
        const uint8_t *covered = mask + (size_t) y * mask_stride;
        int first = where->left, last = where->right;
        int64_t count = 0;

        while (first < last && !(covered[first] && row[first] != paint))
            first++;
        if (first == last)
            continue;
        while (!(covered[last - 1] && row[last - 1] != paint))
            last--;
        for (int x = first; x < last; x++) {
            int paints = (covered[x] != 0) & (row[x] != paint);
            count += paints;
            row[x] = paints ? paint : row[x];
        }
        bounds.count += count;
        if (first < bounds.left) bounds.left = first;
        if (last > bounds.right) bounds.right = last;
        if (y < bounds.top) bounds.top = y;
        bounds.bottom = y + 1;
    }
    if (bounds.count == 0)
        bounds.left = bounds.top = bounds.right = bounds.bottom = 0;
    *changed = bounds;
}

static inline int
covers (const uint8_t *mask, int mask_stride, int width, int height, int x, int y)
{
    return x >= 0 && y >= 0 && x < width && y < height && mask[(size_t) y * mask_stride + x] != 0;
}

/* The border of the pixels a mask covers, inside one rectangle of it: lines
 * along the edges of its pixels, each as (x1, y1, x2, y2) in `lines`, moved by
 * (offset_x, offset_y). Returns how many there are, and writes no more than
 * `room` of them, so asking with no room counts them.
 *
 * A line is cut wherever it crosses a multiple of `cut`, and one along the
 * right or bottom side of the rectangle is left to the rectangle beyond,
 * unless that side is the mask's own. Asked for a tile at a time, with the
 * tiles on multiples of `cut`, every stretch of border then comes once, as
 * the same lines whichever tiles are asked for, and the dashes drawn along
 * them stay put as the view scrolls. */
int64_t
tempera_edges (const uint8_t *mask, int mask_stride, int width, int height,
               int left, int top, int right, int bottom, int cut,
               int offset_x, int offset_y, int32_t *lines, int64_t room)
{
    int64_t found = 0;

    if (left < 0) left = 0;
    if (top < 0) top = 0;
    if (right > width) right = width;
    if (bottom > height) bottom = height;
    if (right <= left || bottom <= top || cut < 1)
        return 0;

#define LINE(x1, y1, x2, y2) \
    do { \
        if (found < room) { \
            int32_t *line = lines + found * 4; \
            line[0] = (x1) + offset_x; line[1] = (y1) + offset_y; \
            line[2] = (x2) + offset_x; line[3] = (y2) + offset_y; \
        } \
        found++; \
    } while (0)

    /* Across: wherever a row and the one above it differ. */
    for (int y = top; y < bottom || (y == bottom && bottom == height); y++) {
        const uint8_t *row = y < height ? mask + (size_t) y * mask_stride : NULL;
        const uint8_t *above = y > 0 ? mask + (size_t) (y - 1) * mask_stride : NULL;
        int start = -1;

        for (int x = left; x < right; x++) {
            int differs = ((row != NULL && row[x] != 0) != (above != NULL && above[x] != 0));
            if (start >= 0 && (!differs || x % cut == 0)) {
                LINE (start, y, x, y);
                start = -1;
            }
            if (differs && start < 0)
                start = x;
        }
        if (start >= 0)
            LINE (start, y, right, y);
    }
    /* Up and down: wherever a pixel differs from the one to its left. */
    for (int x = left; x < right || (x == right && right == width); x++) {
        int start = -1;

        for (int y = top; y < bottom; y++) {
            int differs = covers (mask, mask_stride, width, height, x, y)
                       != covers (mask, mask_stride, width, height, x - 1, y);
            if (start >= 0 && (!differs || y % cut == 0)) {
                LINE (x, start, x, y);
                start = -1;
            }
            if (differs && start < 0)
                start = y;
        }
        if (start >= 0)
            LINE (x, start, x, bottom);
    }
#undef LINE
    return found;
}
