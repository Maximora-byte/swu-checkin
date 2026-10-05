"""Behavioral regressions for lossless browser preview verification."""

import io
import struct
import unittest
import zlib

from PIL import Image
from verify_preview_pixels import pixels


def png(*, mode="RGBA", color=(20, 40, 60, 255), size=(2, 2), chunks=(), icc=None, dpi=None):
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    options = {}
    if icc is not None:
        options["icc_profile"] = icc
    if dpi is not None:
        options["dpi"] = dpi
    image.save(output, format="PNG", **options)
    extra = b"".join(
        struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
        for kind, value in chunks
    )
    data = output.getvalue()
    return data[:33] + extra + data[33:]


STANDARD = (
    (b"gAMA", struct.pack(">I", 45455)),
    (
        b"cHRM",
        struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000),
    ),
)


class PreviewPixelsTests(unittest.TestCase):
    def test_standard_metadata_matches_srgb_marker(self):
        self.assertEqual(pixels(png(chunks=((b"sRGB", b"\0"),))), pixels(png(chunks=STANDARD)))

    def test_untagged_browser_preview_matches_standard_srgb(self):
        self.assertEqual(pixels(png()), pixels(png(chunks=STANDARD)))

    def test_opaque_alpha_removal_is_lossless(self):
        self.assertEqual(pixels(png()), pixels(png(mode="RGB", color=(20, 40, 60), chunks=STANDARD)))

    def test_timestamp_changes_do_not_change_rendering(self):
        self.assertEqual(
            pixels(png()),
            pixels(png(chunks=((b"tEXt", b"date:modify\x002026-10-06"),))),
        )

    def test_changed_pixel_fails_even_with_standard_metadata(self):
        self.assertNotEqual(pixels(png()), pixels(png(color=(21, 40, 60, 255), chunks=STANDARD)))

    def test_changed_alpha_fails(self):
        self.assertNotEqual(pixels(png()), pixels(png(color=(20, 40, 60, 254))))

    def test_changed_dimensions_fail(self):
        self.assertNotEqual(pixels(png()), pixels(png(size=(3, 2))))

    def test_custom_gamma_cannot_be_added_removed_or_changed(self):
        custom = png(chunks=((b"gAMA", struct.pack(">I", 100000)),))
        for other in (
            png(),
            png(chunks=STANDARD),
            png(chunks=((b"gAMA", struct.pack(">I", 45454)),)),
        ):
            with self.subTest(other=other[:32]):
                self.assertNotEqual(pixels(custom), pixels(other))
        self.assertEqual(pixels(custom), pixels(custom))

    def test_custom_chromaticity_cannot_be_dropped(self):
        custom = png(
            chunks=(
                (
                    b"cHRM",
                    struct.pack(">8I", 31271, 32900, 64000, 33000, 30000, 60000, 15000, 6000),
                ),
            )
        )
        self.assertNotEqual(pixels(custom), pixels(png()))

    def test_icc_profile_cannot_be_added_removed_or_changed(self):
        for left, right in (
            (png(icc=b"profile-one"), png()),
            (png(), png(icc=b"profile-one")),
            (png(icc=b"profile-one"), png(icc=b"profile-two")),
        ):
            self.assertNotEqual(pixels(left), pixels(right))
        self.assertEqual(pixels(png(icc=b"profile-one")), pixels(png(icc=b"profile-one")))

    def test_rendering_intent_cannot_change(self):
        self.assertNotEqual(pixels(png(chunks=((b"sRGB", b"\1"),))), pixels(png()))

    def test_hdr_and_rendering_chunks_cannot_be_added(self):
        for kind, payload in (
            (b"cICP", b"\1\15\0\1"),
            (b"mDCV", b"\0" * 24),
            (b"cLLI", b"\0" * 8),
            (b"sBIT", b"\7" * 4),
        ):
            with self.subTest(kind=kind):
                self.assertNotEqual(pixels(png()), pixels(png(chunks=((kind, payload),))))

    def test_full_precision_significant_bits_are_redundant(self):
        self.assertEqual(pixels(png(chunks=((b"sBIT", b"\10" * 4),))), pixels(png()))

    def test_browser_page_background_overrides_png_background_suggestion(self):
        self.assertEqual(
            pixels(png(color=(20, 40, 60, 128))),
            pixels(png(color=(20, 40, 60, 128), chunks=((b"bKGD", struct.pack(">3H", 255, 255, 255)),))),
        )

    def test_dpi_cannot_change(self):
        self.assertNotEqual(pixels(png(dpi=(96, 96))), pixels(png(dpi=(144, 144))))

    def test_animation_is_rejected(self):
        output = io.BytesIO()
        Image.new("RGBA", (2, 2), (20, 40, 60, 255)).save(
            output,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGBA", (2, 2), (21, 40, 60, 255))],
            duration=100,
        )
        with self.assertRaises(ValueError):
            pixels(output.getvalue())

    def test_non_png_is_rejected(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 2)).save(output, format="JPEG")
        with self.assertRaises(ValueError):
            pixels(output.getvalue())

    def test_16_bit_samples_are_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            pixels(png(mode="I;16", color=32768))


if __name__ == "__main__":
    unittest.main()
