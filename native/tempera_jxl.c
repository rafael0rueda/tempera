/* SPDX-FileCopyrightText: 2026 Rafael Rueda
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Writing JPEG XL. GdkPixbuf reads the format but cannot write it, so this
 * calls libjxl, the one thing here that needs a library: it is kept apart from
 * tempera_native.c so that a missing libjxl costs JPEG XL and nothing else.
 *
 * tempera/jxl.py loads it. Without it, Tempera opens JPEG XL files and does
 * not offer to save them.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

#include <jxl/color_encoding.h>
#include <jxl/encode.h>
#include <jxl/thread_parallel_runner.h>

/* Raised whenever a call below changes what it takes or what it gives back:
 * tempera/jxl.py will not use one built from older source than its own. */
int
tempera_jxl_version (void)
{
    return 1;
}

static int
write_all (JxlEncoder *encoder, uint8_t **encoded, size_t *encoded_size)
{
    size_t room = 64 * 1024, written = 0;
    uint8_t *output = malloc (room);
    JxlEncoderStatus status = JXL_ENC_NEED_MORE_OUTPUT;

    while (output != NULL && status == JXL_ENC_NEED_MORE_OUTPUT) {
        uint8_t *next = output + written;
        size_t left = room - written;

        status = JxlEncoderProcessOutput (encoder, &next, &left);
        written = next - output;
        if (status == JXL_ENC_NEED_MORE_OUTPUT) {
            uint8_t *larger = realloc (output, room * 2);

            if (larger == NULL) {
                free (output);
                return -1;
            }
            output = larger;
            room *= 2;
        }
    }
    if (output == NULL || status != JXL_ENC_SUCCESS) {
        free (output);
        return -1;
    }
    *encoded = output;
    *encoded_size = written;
    return 0;
}

static int
encode (JxlEncoder *encoder, const uint8_t *pixels, int width, int height, int quality,
        uint8_t **encoded, size_t *encoded_size)
{
    const int lossless = quality >= 100;
    const JxlPixelFormat format = { 4, JXL_TYPE_UINT8, JXL_NATIVE_ENDIAN, 0 };
    const size_t size = (size_t) width * height * 4;
    JxlBasicInfo info;
    JxlColorEncoding color;
    JxlEncoderFrameSettings *settings;

    JxlEncoderInitBasicInfo (&info);
    info.xsize = width;
    info.ysize = height;
    info.bits_per_sample = 8;
    info.exponent_bits_per_sample = 0;
    info.num_color_channels = 3;
    info.num_extra_channels = 1;
    info.alpha_bits = 8;
    info.alpha_exponent_bits = 0;
    /* Lossless has to keep the numbers it was given, not a perceptual version. */
    info.uses_original_profile = lossless ? JXL_TRUE : JXL_FALSE;
    if (JxlEncoderSetBasicInfo (encoder, &info) != JXL_ENC_SUCCESS)
        return -1;

    JxlColorEncodingSetToSRGB (&color, JXL_FALSE);
    if (JxlEncoderSetColorEncoding (encoder, &color) != JXL_ENC_SUCCESS)
        return -1;

    settings = JxlEncoderFrameSettingsCreate (encoder, NULL);
    if (settings == NULL)
        return -1;
    if (lossless) {
        if (JxlEncoderSetFrameLossless (settings, JXL_TRUE) != JXL_ENC_SUCCESS
            || JxlEncoderSetFrameDistance (settings, 0.0f) != JXL_ENC_SUCCESS)
            return -1;
    } else if (JxlEncoderSetFrameDistance (settings, JxlEncoderDistanceFromQuality (quality))
               != JXL_ENC_SUCCESS) {
        return -1;
    }

    if (JxlEncoderAddImageFrame (settings, &format, pixels, size) != JXL_ENC_SUCCESS)
        return -1;
    JxlEncoderCloseInput (encoder);
    return write_all (encoder, encoded, encoded_size);
}

/* Encode a picture of straight (not premultiplied) RGBA bytes, its rows one
 * straight after another. A `quality` of 1 to 99 follows libjxl's scale, close
 * to a JPEG's; 100 keeps every pixel exactly. Returns 0 with the file in
 * `encoded`, for tempera_jxl_free(), or -1. */
int
tempera_jxl_encode (const uint8_t *pixels, int width, int height, int quality,
                    uint8_t **encoded, size_t *encoded_size)
{
    JxlEncoder *encoder = JxlEncoderCreate (NULL);
    void *runner = JxlThreadParallelRunnerCreate (NULL,
                                                  JxlThreadParallelRunnerDefaultNumWorkerThreads ());
    int result = -1;

    if (encoder != NULL && runner != NULL
        && JxlEncoderSetParallelRunner (encoder, JxlThreadParallelRunner, runner) == JXL_ENC_SUCCESS)
        result = encode (encoder, pixels, width, height, quality, encoded, encoded_size);

    JxlThreadParallelRunnerDestroy (runner);
    JxlEncoderDestroy (encoder);
    return result;
}

void
tempera_jxl_free (uint8_t *encoded)
{
    free (encoded);
}
