"""Verify that the existing documentation PNG previews retain their rendered pixels."""

import io
import json
import os
import struct
import subprocess
from pathlib import Path

from ci_preview_scope import PREVIEWS, preview_only
from PIL import Image


def color_signature(data: bytes, image: Image.Image) -> tuple:
    """Normalize standard sRGB metadata for these five browser documentation previews.

    Untagged previews use the browser's sRGB default. PNG's specified fallback
    gAMA/cHRM values may replace an sRGB marker. Custom profiles, HDR, orientation,
    significant bits and rendering metadata must still be byte-for-byte stable.
    https://www.w3.org/TR/png-3/#11sRGB
    """
    chunks = []
    position = 8
    while position < len(data):
        length = struct.unpack_from(">I", data, position)[0]
        kind = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        if kind in {b"cICP", b"mDCV", b"cLLI", b"sBIT", b"eXIf", b"bKGD"}:
            chunks.append((kind, payload))
        position += length + 12
    gamma = image.info.get("gamma")
    chroma = image.info.get("chromaticity")
    srgb = image.info.get("srgb")
    icc = image.info.get("icc_profile")
    standard_chroma = (0.3127, 0.329, 0.64, 0.33, 0.3, 0.6, 0.15, 0.06)
    if icc is None and gamma in (None, 0.45455) and chroma in (None, standard_chroma) and srgb in (None, 0):
        color = ("browser-srgb",)
    else:
        color = ("custom", icc, srgb, gamma, chroma)
    # Keep physical aspect ratio/scale, higher-precedence color data and EXIF
    # unchanged; adding timestamps or losslessly dropping opaque alpha is safe.
    return color, tuple(sorted(chunks)), image.info.get("dpi"), image.info.get("aspect")


def pixels(data: bytes) -> tuple:
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Preview exceeds the permitted file size")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Unexpected preview format or dimensions")
        if data[24] == 16:
            raise ValueError("16-bit previews require a separate lossless verifier")
        image.load()
        return image.size, image.convert("RGBA").tobytes(), color_signature(data, image)


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    if not preview_only(os.environ["GITHUB_EVENT_NAME"], event):
        raise ValueError("The PR is not a trusted preview-only optimization")
    pr = event["pull_request"]
    base = subprocess.check_output(["git", "merge-base", pr["base"]["sha"], pr["head"]["sha"]], text=True).strip()
    for path in sorted(PREVIEWS):
        old = subprocess.check_output(["git", "show", f"{base}:{path}"])
        new = subprocess.check_output(["git", "show", f"{pr['head']['sha']}:{path}"])
        if pixels(old) != pixels(new):
            raise ValueError(f"Preview pixels or color profile changed: {path}")
    print("All five documentation previews preserve dimensions, pixels and color profiles.")


if __name__ == "__main__":
    main()
