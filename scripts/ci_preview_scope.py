"""Allow only canonical ImgBot modifications of existing documentation previews."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

PREVIEWS = frozenset(
    {
        "android/artwork/previews/dark-home.png",
        "android/artwork/previews/large-text.png",
        "android/artwork/previews/light-home.png",
        "android/artwork/swu-checkin-icon-preview.png",
        "android/artwork/ui-preview.png",
    }
)


def preview_only(event_name: str, event: dict) -> bool:
    if event_name != "pull_request":
        return False
    try:
        pr = event["pull_request"]
        user = pr["user"]
        if (user["login"], user["id"], user["type"]) != ("imgbot[bot]", 31301654, "Bot"):
            return False
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha) for sha in (base, head)):
            return False
        # No rename detection: renaming code to a PNG produces D+A, never M.
        diff = (
            subprocess.check_output(["git", "diff", "--name-status", "--no-renames", "-z", f"{base}...{head}", "--"])
            .decode("utf-8")
            .split("\0")
        )
        fields = diff[:-1] if diff[-1] == "" else diff
        return (
            bool(fields)
            and len(fields) % 2 == 0
            and all(fields[index] == "M" and fields[index + 1] in PREVIEWS for index in range(0, len(fields), 2))
        )
    except (KeyError, TypeError, OSError, UnicodeError, subprocess.CalledProcessError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    event = json.loads(args.event_path.read_text(encoding="utf-8"))
    selected = preview_only(os.environ.get("GITHUB_EVENT_NAME", ""), event)
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"preview_only={str(selected).lower()}\n")
    print(f"preview_only={str(selected).lower()}")


if __name__ == "__main__":
    main()
