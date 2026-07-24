#!/usr/bin/env python3
"""Adjust Hyprland's cursor-centred zoom without losing rapid input events."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys


ZOOM_STEP = 1.12
MAX_ZOOM = 4.0


def hyprctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["hyprctl", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"in", "out"}:
        raise SystemExit("usage: hyprland-infinite-zoom <in|out>")

    runtime_dir = Path(
        os.environ.get(
            "INFINITE_DESKTOP_RUNTIME_DIR",
            str(Path(os.environ["XDG_RUNTIME_DIR"]) / "hyprland-infinite-desktop"),
        )
    )
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    with (runtime_dir / "zoom.lock").open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        current = float(
            json.loads(hyprctl("getoption", "cursor:zoom_factor", "-j").stdout)["float"]
        )
        if sys.argv[1] == "in":
            target = min(MAX_ZOOM, current * ZOOM_STEP)
        else:
            target = max(1.0, current / ZOOM_STEP)
            if target < 1.01:
                target = 1.0
        hyprctl("-q", "keyword", "cursor:zoom_factor", f"{target:.6f}")


if __name__ == "__main__":
    main()
