#!/usr/bin/env python3
"""Window-edge snapping and connected-window resize propagation for Hyprland."""

import json
import subprocess
import threading
import time

from hypr_ipc import batch_async, move_window_exact_lua


def _hypr_json(*arguments, timeout=0.5):
    result = subprocess.run(
        ["hyprctl", *arguments, "-j"],
        capture_output=True,
        check=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(result.stdout)


def _geometry(window):
    x, y = window["at"]
    width, height = window["size"]
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "right": x + width,
        "bottom": y + height,
    }


def _overlaps(start_a, end_a, start_b, end_b):
    return min(end_a, end_b) > max(start_a, start_b)


class SnapManager:
    """Maintain snap relationships without grouping application windows."""

    def __init__(self):
        self.lock = threading.RLock()
        self.dragged_address = None
        self.relations = []
        self.last_geometry = {}
        self.gap = 8
        self.threshold = 24
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self._refresh_gap()
        threading.Thread(target=self._watch_resizes, daemon=True).start()

    def begin_drag(self, address):
        with self.lock:
            self.dragged_address = address
            self.relations = [
                relation
                for relation in self.relations
                if address not in relation[:2]
            ]

    def update_drag(self, address):
        try:
            clients = self._floating_clients()
            moving = clients.get(address)
            if moving is None:
                return
            target_x, target_y = self._snap_target(address, clients)
            current = _geometry(moving)
            if target_x != current["x"] or target_y != current["y"]:
                batch_async([move_window_exact_lua(target_x, target_y, address)])
        except Exception:
            return

    def end_drag(self, address):
        try:
            clients = self._floating_clients()
            with self.lock:
                self.dragged_address = None
                self.relations = self._discover_relations(clients)
                self.last_geometry = {
                    key: _geometry(value) for key, value in clients.items()
                }
        except Exception:
            with self.lock:
                self.dragged_address = None

    def _refresh_gap(self):
        try:
            option = _hypr_json("getoption", "general:gaps_in")
            custom = str(option.get("custom", "")).split()
            value = option.get("int")
            if value is None and custom:
                value = custom[0]
            self.gap = max(0, int(value if value is not None else 8))
        except Exception:
            self.gap = 8
        self.threshold = max(24, self.gap * 2 + 8)

    def _floating_clients(self):
        clients = _hypr_json("clients")
        return {
            window["address"]: window
            for window in clients
            if window.get("floating")
            and window.get("mapped", True)
            and not window.get("hidden")
            and window.get("workspace", {}).get("id", 0) > 0
        }

    def _snap_target(self, address, clients):
        moving = _geometry(clients[address])
        x_candidates = []
        y_candidates = []

        for other_address, other_window in clients.items():
            if other_address == address:
                continue
            other = _geometry(other_window)
            vertical_overlap = _overlaps(
                moving["y"], moving["bottom"], other["y"], other["bottom"]
            )
            horizontal_overlap = _overlaps(
                moving["x"], moving["right"], other["x"], other["right"]
            )

            left_distance = abs(moving["right"] + self.gap - other["x"])
            right_distance = abs(moving["x"] - self.gap - other["right"])
            if vertical_overlap and left_distance <= self.threshold:
                x_candidates.append(
                    (left_distance, other["x"] - self.gap - moving["width"])
                )
            if vertical_overlap and right_distance <= self.threshold:
                x_candidates.append((right_distance, other["right"] + self.gap))

            top_distance = abs(moving["bottom"] + self.gap - other["y"])
            bottom_distance = abs(moving["y"] - self.gap - other["bottom"])
            if horizontal_overlap and top_distance <= self.threshold:
                y_candidates.append(
                    (top_distance, other["y"] - self.gap - moving["height"])
                )
            if horizontal_overlap and bottom_distance <= self.threshold:
                y_candidates.append((bottom_distance, other["bottom"] + self.gap))

            horizontally_adjacent = min(left_distance, right_distance) <= self.threshold
            vertically_adjacent = min(top_distance, bottom_distance) <= self.threshold
            if horizontally_adjacent:
                y_candidates.extend(
                    [
                        (abs(moving["y"] - other["y"]), other["y"]),
                        (
                            abs(moving["bottom"] - other["bottom"]),
                            other["bottom"] - moving["height"],
                        ),
                    ]
                )
            if vertically_adjacent:
                x_candidates.extend(
                    [
                        (abs(moving["x"] - other["x"]), other["x"]),
                        (
                            abs(moving["right"] - other["right"]),
                            other["right"] - moving["width"],
                        ),
                    ]
                )

        x_candidates = [
            candidate for candidate in x_candidates if candidate[0] <= self.threshold
        ]
        y_candidates = [
            candidate for candidate in y_candidates if candidate[0] <= self.threshold
        ]
        target_x = min(x_candidates)[1] if x_candidates else moving["x"]
        target_y = min(y_candidates)[1] if y_candidates else moving["y"]
        return int(target_x), int(target_y)

    def _discover_relations(self, clients):
        relations = []
        addresses = sorted(clients)
        tolerance = 3
        for index, first_address in enumerate(addresses):
            first = _geometry(clients[first_address])
            for second_address in addresses[index + 1 :]:
                second = _geometry(clients[second_address])
                if _overlaps(
                    first["y"], first["bottom"], second["y"], second["bottom"]
                ):
                    if abs(first["right"] + self.gap - second["x"]) <= tolerance:
                        relations.append(
                            (first_address, second_address, "horizontal")
                        )
                    elif abs(second["right"] + self.gap - first["x"]) <= tolerance:
                        relations.append(
                            (second_address, first_address, "horizontal")
                        )
                if _overlaps(
                    first["x"], first["right"], second["x"], second["right"]
                ):
                    if abs(first["bottom"] + self.gap - second["y"]) <= tolerance:
                        relations.append((first_address, second_address, "vertical"))
                    elif abs(second["bottom"] + self.gap - first["y"]) <= tolerance:
                        relations.append((second_address, first_address, "vertical"))
        return relations

    def _active_address(self):
        try:
            return _hypr_json("activewindow").get("address")
        except Exception:
            return None

    def _watch_resizes(self):
        while self.running:
            try:
                clients = self._floating_clients()
                geometries = {
                    address: _geometry(window) for address, window in clients.items()
                }
                active = self._active_address()
                with self.lock:
                    dragging = self.dragged_address is not None
                    previous = self.last_geometry.get(active)
                    current = geometries.get(active)
                    resized = (
                        not dragging
                        and previous is not None
                        and current is not None
                        and (
                            previous["width"] != current["width"]
                            or previous["height"] != current["height"]
                        )
                    )
                    self.relations = [
                        relation
                        for relation in self.relations
                        if relation[0] in geometries and relation[1] in geometries
                    ]
                if resized:
                    self._propagate_from(active, geometries)
                    clients = self._floating_clients()
                    geometries = {
                        address: _geometry(window)
                        for address, window in clients.items()
                    }
                with self.lock:
                    self.last_geometry = geometries
            except Exception:
                pass
            time.sleep(0.05)

    def _propagate_from(self, root_address, geometries):
        pending = [root_address]
        visited = {root_address}
        expressions = []

        while pending:
            current_address = pending.pop(0)
            current = geometries.get(current_address)
            if current is None:
                continue
            for first, second, orientation in list(self.relations):
                if current_address == first:
                    neighbor_address = second
                    direction = 1
                elif current_address == second:
                    neighbor_address = first
                    direction = -1
                else:
                    continue
                if neighbor_address in visited or neighbor_address not in geometries:
                    continue
                neighbor = geometries[neighbor_address]
                if orientation == "horizontal":
                    target_x = (
                        current["right"] + self.gap
                        if direction == 1
                        else current["x"] - self.gap - neighbor["width"]
                    )
                    target_y = neighbor["y"]
                else:
                    target_x = neighbor["x"]
                    target_y = (
                        current["bottom"] + self.gap
                        if direction == 1
                        else current["y"] - self.gap - neighbor["height"]
                    )
                neighbor["x"] = target_x
                neighbor["y"] = target_y
                neighbor["right"] = target_x + neighbor["width"]
                neighbor["bottom"] = target_y + neighbor["height"]
                expressions.append(
                    move_window_exact_lua(target_x, target_y, neighbor_address)
                )
                visited.add(neighbor_address)
                pending.append(neighbor_address)

        batch_async(expressions)
