#!/usr/bin/env python3
"""Focus a directional neighbor and pan only enough to reveal it."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (  # noqa: E402
    batch_wait,
    focus_window,
    hyprctl_json,
    move_focus,
    move_window_exact_lua,
)

DIR_SHORT = {"left": "l", "right": "r", "up": "u", "down": "d"}


def get_window_bounds(window):
    x, y = window["at"]
    width, height = window["size"]
    return {
        "left": x,
        "right": x + width,
        "top": y,
        "bottom": y + height,
        "center_x": x + width // 2,
        "center_y": y + height // 2,
    }


def get_monitor_bounds():
    monitors = hyprctl_json(["monitors"]) or []
    monitor = next(
        (item for item in monitors if item.get("focused")),
        monitors[0] if monitors else None,
    )
    if monitor is None:
        return {"left": 0, "right": 1920, "top": 0, "bottom": 1080}
    return {
        "left": monitor["x"],
        "right": monitor["x"] + monitor["width"],
        "top": monitor["y"],
        "bottom": monitor["y"] + monitor["height"],
    }


def overlap_h(first, second):
    return not (
        first["right"] <= second["left"] or first["left"] >= second["right"]
    )


def overlap_v(first, second):
    return not (
        first["bottom"] <= second["top"] or first["top"] >= second["bottom"]
    )


def find_target(floating, current, direction):
    current_bounds = get_window_bounds(current)
    center_x = current_bounds["center_x"]
    center_y = current_bounds["center_y"]

    aligned = []
    for window in floating:
        if window["address"] == current["address"]:
            continue
        bounds = get_window_bounds(window)
        if (
            direction == "left"
            and overlap_v(current_bounds, bounds)
            and bounds["center_x"] < center_x
        ):
            aligned.append((window, center_x - bounds["center_x"]))
        elif (
            direction == "right"
            and overlap_v(current_bounds, bounds)
            and bounds["center_x"] > center_x
        ):
            aligned.append((window, bounds["center_x"] - center_x))
        elif (
            direction == "up"
            and overlap_h(current_bounds, bounds)
            and bounds["center_y"] < center_y
        ):
            aligned.append((window, center_y - bounds["center_y"]))
        elif (
            direction == "down"
            and overlap_h(current_bounds, bounds)
            and bounds["center_y"] > center_y
        ):
            aligned.append((window, bounds["center_y"] - center_y))
    if aligned:
        return min(aligned, key=lambda item: item[1])[0]

    candidates = []
    for window in floating:
        if window["address"] == current["address"]:
            continue
        bounds = get_window_bounds(window)
        if direction == "left" and bounds["center_x"] < center_x:
            candidates.append((window, center_x - bounds["center_x"]))
        elif direction == "right" and bounds["center_x"] > center_x:
            candidates.append((window, bounds["center_x"] - center_x))
        elif direction == "up" and bounds["center_y"] < center_y:
            candidates.append((window, center_y - bounds["center_y"]))
        elif direction == "down" and bounds["center_y"] > center_y:
            candidates.append((window, bounds["center_y"] - center_y))
    if candidates:
        return min(candidates, key=lambda item: item[1])[0]

    if direction == "left":
        return max(floating, key=lambda item: get_window_bounds(item)["center_x"])
    if direction == "right":
        return min(floating, key=lambda item: get_window_bounds(item)["center_x"])
    if direction == "up":
        return max(floating, key=lambda item: get_window_bounds(item)["center_y"])
    return min(floating, key=lambda item: get_window_bounds(item)["center_y"])


def axis_delta(start, end, viewport_start, viewport_end):
    window_size = end - start
    viewport_size = viewport_end - viewport_start
    if window_size <= viewport_size:
        if start < viewport_start:
            return viewport_start - start
        if end > viewport_end:
            return viewport_end - end
        return 0
    if end > viewport_start and start < viewport_end:
        return 0
    candidates = (viewport_start - start, viewport_end - end)
    return min(candidates, key=abs)


def pan_to_window(floating, target, monitor):
    bounds = get_window_bounds(target)
    delta_x = axis_delta(
        bounds["left"], bounds["right"], monitor["left"], monitor["right"]
    )
    delta_y = axis_delta(
        bounds["top"], bounds["bottom"], monitor["top"], monitor["bottom"]
    )
    expressions = [
        move_window_exact_lua(
            window["at"][0] + delta_x,
            window["at"][1] + delta_y,
            window["address"],
        )
        for window in floating
    ]
    batch_wait(expressions)
    focus_window(target["address"])


def center_window(floating, target, monitor):
    bounds = get_window_bounds(target)
    target_x = (monitor["left"] + monitor["right"]) // 2
    target_y = (monitor["top"] + monitor["bottom"]) // 2
    delta_x = target_x - bounds["center_x"]
    delta_y = target_y - bounds["center_y"]
    expressions = [
        move_window_exact_lua(
            window["at"][0] + delta_x,
            window["at"][1] + delta_y,
            window["address"],
        )
        for window in floating
    ]
    batch_wait(expressions)
    focus_window(target["address"])


def distance_to_viewport(window, monitor):
    bounds = get_window_bounds(window)
    delta_x = axis_delta(
        bounds["left"], bounds["right"], monitor["left"], monitor["right"]
    )
    delta_y = axis_delta(
        bounds["top"], bounds["bottom"], monitor["top"], monitor["bottom"]
    )
    return delta_x * delta_x + delta_y * delta_y


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in (*DIR_SHORT, "center"):
        print("usage: navigate_windows.py <left|right|up|down|center>")
        sys.exit(1)
    direction = sys.argv[1]

    workspace = hyprctl_json(["activeworkspace"])
    if not workspace:
        sys.exit(1)
    clients = hyprctl_json(["clients"]) or []
    floating = [
        window
        for window in clients
        if window.get("floating")
        and window.get("workspace", {}).get("id") == workspace["id"]
    ]
    if not floating:
        if direction != "center":
            move_focus(DIR_SHORT[direction])
        return
    if len(floating) == 1:
        if direction == "center":
            center_window(floating, floating[0], get_monitor_bounds())
        else:
            focus_window(floating[0]["address"])
        return

    monitor = get_monitor_bounds()
    focused = hyprctl_json(["activewindow"]) or {}
    current = next(
        (
            window
            for window in floating
            if window["address"] == focused.get("address")
        ),
        None,
    )
    if direction == "center":
        if current is not None:
            center_window(floating, current, monitor)
        return
    if current is None:
        target = min(
            floating,
            key=lambda window: distance_to_viewport(window, monitor),
        )
    else:
        target = find_target(floating, current, direction)
    pan_to_window(floating, target, monitor)


if __name__ == "__main__":
    main()
