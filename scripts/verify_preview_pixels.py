"""Verify that the existing documentation PNG previews retain their rendered pixels."""

import io
import json
import os
import subprocess
from pathlib import Path

from ci_preview_scope import PREVIEWS, preview_only
from PIL import Image


def pixels(data: bytes) -> tuple:
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Preview exceeds the permitted file size")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Unexpected preview format or dimensions")
        image.load()
        return image.size, image.convert("RGBA").tobytes(), image.info.get("icc_profile"), image.info.get("gamma")


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
