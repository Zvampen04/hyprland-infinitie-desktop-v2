#!/usr/bin/env python3
"""Resize the requested edge by 10% of the containing output."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import hyprctl_json, move_window_exact, resize_window_exact

MIN_SIZE = 100


def main():
    if (
        len(sys.argv) != 3
        or sys.argv[1] not in ("left", "right", "up", "down")
        or sys.argv[2] not in ("grow", "shrink")
    ):
        print("usage: resize_window.py <left|right|up|down> <grow|shrink>")
        sys.exit(1)

    direction = sys.argv[1]
    operation = sys.argv[2]

    window = hyprctl_json(["activewindow"])
    if not window or not window.get("floating"):
        sys.exit(0)

    addr = window["address"]
    x, y = window["at"]
    width, height = window["size"]
    center_x = x + width // 2
    center_y = y + height // 2
    monitors = hyprctl_json(["monitors"])
    monitor = next(
        (
            item
            for item in monitors
            if item["x"] <= center_x < item["x"] + item["width"]
            and item["y"] <= center_y < item["y"] + item["height"]
        ),
        next((item for item in monitors if item.get("focused")), monitors[0]),
    )
    horizontal_step = round(monitor["width"] / 10)
    vertical_step = round(monitor["height"] / 10)
    delta = 1 if operation == "grow" else -1
    new_x, new_y = x, y
    new_w, new_h = width, height

    if direction in ("left", "right"):
        change = horizontal_step * delta
        new_w = max(MIN_SIZE, width + change)
        applied = new_w - width
        if direction == "left":
            new_x = x - applied
    else:
        change = vertical_step * delta
        new_h = max(MIN_SIZE, height + change)
        applied = new_h - height
        if direction == "up":
            new_y = y - applied

    move_window_exact(new_x, new_y, addr)
    resize_window_exact(new_w, new_h, addr)


if __name__ == "__main__":
    main()
