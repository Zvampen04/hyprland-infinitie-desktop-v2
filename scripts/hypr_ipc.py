#!/usr/bin/env python3
"""Hyprland 0.55 positional-dispatch compatibility for Sarod's helpers."""

import json
import subprocess
import time


def _run(args, timeout=2):
    return subprocess.run(
        ["hyprctl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def hyprctl_json(args, timeout=2):
    result = _run([*args, "-j"], timeout=timeout)
    return json.loads(result.stdout) if result.stdout.strip() else None


def dispatch(spec, timeout=2):
    return _run(["dispatch", *spec], timeout=timeout)


def dispatch_async(spec):
    subprocess.Popen(
        ["hyprctl", "dispatch", *spec],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def batch(specs, timeout=5):
    command = " ; ".join(
        "dispatch " + " ".join(spec)
        for spec in specs
    )
    return _run(["--batch", command], timeout=timeout)


def batch_async(specs):
    if not specs:
        return
    command = " ; ".join(
        "dispatch " + " ".join(spec)
        for spec in specs
    )
    subprocess.Popen(
        ["hyprctl", "--batch", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _exact_move_positions(specs):
    positions = {}
    for spec in specs:
        if len(spec) != 4 or spec[:2] != ("movewindowpixel", "exact"):
            continue
        y_and_address = spec[3].split(",address:", 1)
        if len(y_and_address) != 2:
            continue
        positions[y_and_address[1]] = (int(spec[2]), int(y_and_address[0]))
    return positions


def wait_for_positions(positions, timeout=1):
    if not positions:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            clients = hyprctl_json(["clients"], timeout=min(timeout, 0.2)) or []
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            clients = []
        current = {
            client.get("address"): tuple(client.get("at", ()))
            for client in clients
        }
        if all(current.get(address) == position for address, position in positions.items()):
            return True
        time.sleep(0.01)
    return False


def batch_wait(specs, timeout=2):
    result = batch(specs, timeout=timeout)
    if not wait_for_positions(_exact_move_positions(specs), timeout=timeout):
        raise TimeoutError("Hyprland did not apply the requested move batch")
    return result


def toggle_floating_lua(address=None):
    target = f"address:{address}" if address else "activewindow"
    return ("togglefloating", target)


def toggle_floating(address=None):
    return dispatch(toggle_floating_lua(address))


def focus_window_lua(address):
    return ("focuswindow", f"address:{address}")


def focus_window(address):
    return dispatch(focus_window_lua(address))


def move_focus_lua(direction):
    return ("movefocus", direction)


def move_focus(direction):
    return dispatch(move_focus_lua(direction))


def move_window_tiled_lua(direction):
    return ("movewindow", direction)


def move_window_tiled(direction):
    return dispatch(move_window_tiled_lua(direction))


def exec_cmd_lua(command):
    return ("exec", command)


def move_window_exact_lua(x, y, address):
    return (
        "movewindowpixel",
        "exact",
        str(int(x)),
        f"{int(y)},address:{address}",
    )


def move_window_exact(x, y, address, timeout=2):
    return dispatch(move_window_exact_lua(x, y, address), timeout=timeout)


def move_window_exact_wait(x, y, address, timeout=2):
    spec = move_window_exact_lua(x, y, address)
    result = dispatch(spec, timeout=timeout)
    if not wait_for_positions(_exact_move_positions([spec]), timeout=timeout):
        raise TimeoutError(f"Hyprland did not move {address} to ({int(x)}, {int(y)})")
    return result


def move_window_exact_async(x, y, address):
    dispatch_async(move_window_exact_lua(x, y, address))


def resize_window_exact_lua(width, height, address):
    return (
        "resizewindowpixel",
        "exact",
        str(int(width)),
        f"{int(height)},address:{address}",
    )


def resize_window_exact(width, height, address, timeout=2):
    return dispatch(
        resize_window_exact_lua(width, height, address),
        timeout=timeout,
    )
