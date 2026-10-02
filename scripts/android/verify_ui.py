"""Accept a screenshot only after the feasibility UI is visible and ready."""

import argparse
from pathlib import Path
from xml.etree import ElementTree

APP_ID = "io.github.maximorabyte.swucheckin.feasibility"
REQUIRED_TEXT = {"Android / Python 3.13 可行性验证", "验证离线运行环境", "验证公共 HTTPS（python.org）"}


def verify(text: str, *, app_id: str = APP_ID) -> None:
    root = ElementTree.fromstring(text)
    visible = {
        node.get("text")
        for node in root.iter("node")
        if node.get("package") == app_id and node.get("enabled") == "true"
    }
    if not REQUIRED_TEXT <= visible:
        raise ValueError("feasibility UI is not ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    verify(args.report.read_text(encoding="utf-8"))
    print("Feasibility UI is ready")
