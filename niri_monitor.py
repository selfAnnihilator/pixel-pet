"""Long-lived niri event monitoring for the fullscreen Hiding Reason."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from typing import Callable


class NiriState:
    """Reduce niri event-stream messages into focused-window fullscreen state."""

    def __init__(self) -> None:
        self.outputs: dict[str, dict] = {}
        self.workspaces: dict[int, dict] = {}
        self.windows: dict[int, dict] = {}
        self.focused_window_id: int | None = None

    def apply(self, event: object) -> bool | None:
        if not isinstance(event, dict) or len(event) != 1:
            return None
        name, payload = next(iter(event.items()))
        if not isinstance(payload, dict):
            return None
        if name == "OutputsChanged":
            outputs = payload.get("outputs")
            if isinstance(outputs, dict):
                self.outputs = outputs
        elif name == "WorkspacesChanged":
            workspaces = payload.get("workspaces")
            if isinstance(workspaces, list):
                self.workspaces = {
                    workspace["id"]: workspace
                    for workspace in workspaces
                    if isinstance(workspace, dict) and isinstance(workspace.get("id"), int)
                }
        elif name == "WindowsChanged":
            windows = payload.get("windows")
            if isinstance(windows, list):
                self.windows = {
                    window["id"]: window
                    for window in windows
                    if isinstance(window, dict) and isinstance(window.get("id"), int)
                }
                focused = next(
                    (
                        window_id
                        for window_id, window in self.windows.items()
                        if window.get("is_focused")
                    ),
                    None,
                )
                self.focused_window_id = focused
        elif name == "WindowOpenedOrChanged":
            window = payload.get("window")
            if isinstance(window, dict) and isinstance(window.get("id"), int):
                self.windows[window["id"]] = window
                if window.get("is_focused"):
                    self.focused_window_id = window["id"]
        elif name == "WindowClosed":
            window_id = payload.get("id")
            if isinstance(window_id, int):
                self.windows.pop(window_id, None)
                if self.focused_window_id == window_id:
                    self.focused_window_id = None
        elif name == "WindowFocusChanged":
            window_id = payload.get("id")
            if window_id is None or isinstance(window_id, int):
                self.focused_window_id = window_id
        elif name == "WindowLayoutsChanged":
            changes = payload.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if not (isinstance(change, list) and len(change) == 2):
                        continue
                    window_id, layout = change
                    window = self.windows.get(window_id)
                    if isinstance(window, dict) and isinstance(layout, dict):
                        updated = dict(window)
                        updated["layout"] = layout
                        self.windows[window_id] = updated
        else:
            return None
        return self.is_fullscreen()

    def is_fullscreen(self) -> bool:
        window = self.windows.get(self.focused_window_id)
        if not isinstance(window, dict):
            return False
        layout = window.get("layout")
        tile_size = layout.get("tile_size") if isinstance(layout, dict) else None
        if tile_size is None and isinstance(layout, dict):
            tile_size = layout.get("window_size")
        if not (
            isinstance(tile_size, list)
            and len(tile_size) == 2
            and all(isinstance(value, (int, float)) for value in tile_size)
        ):
            return False
        output = self._output_for(window)
        logical = output.get("logical") if isinstance(output, dict) else None
        if not isinstance(logical, dict):
            return False
        width, height = logical.get("width"), logical.get("height")
        return bool(width and height and tuple(tile_size) == (width, height))

    def _output_for(self, window: dict) -> dict | None:
        workspace_id = window.get("workspace_id")
        workspace = self.workspaces.get(workspace_id)
        output_name = workspace.get("output") if isinstance(workspace, dict) else None
        if isinstance(output_name, str):
            output = self.outputs.get(output_name)
            if isinstance(output, dict):
                return output
        return None


class NiriFullscreenMonitor:
    """Own one niri event-stream process, recovery, and visibility delivery."""

    RETRY_DELAYS_MS = (1000, 2000, 5000, 10000, 30000)

    def __init__(
        self,
        on_fullscreen: Callable[[bool], None],
        *,
        dispatch: Callable[[Callable[[], bool]], object],
        schedule_retry: Callable[[int, Callable[[], bool]], object],
        cancel_retry: Callable[[object], None],
        executable: str = "niri",
        popen: Callable[..., object] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        load_outputs: Callable[[], dict] | None = None,
    ) -> None:
        self._on_fullscreen = on_fullscreen
        self._dispatch = dispatch
        self._schedule_retry = schedule_retry
        self._cancel_retry = cancel_retry
        self._executable = executable
        self._popen = popen
        self._clock = clock
        self._load_outputs = load_outputs or self._default_load_outputs
        self._state = NiriState()
        self._process = None
        self._thread: threading.Thread | None = None
        self._retry_source = None
        self._retry_index = 0
        self._launched_at: float | None = None
        self._running = False
        self._last_fullscreen: bool | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if shutil.which(self._executable) is None:
            self._emit(False)
            return
        self._launch()

    def _default_load_outputs(self) -> dict:
        result = subprocess.run(
            [self._executable, "msg", "--json", "outputs"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2.0,
        )
        outputs = json.loads(result.stdout)
        if not isinstance(outputs, dict):
            raise ValueError("niri outputs response is not an object")
        return outputs

    def stop(self) -> None:
        self._running = False
        if self._retry_source is not None:
            self._cancel_retry(self._retry_source)
            self._retry_source = None
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        if process is not None:
            try:
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def consume_line(self, line: str) -> bool | None:
        event = self._decode_line(line)
        if event is None:
            return None
        return self._consume_event(event)

    @staticmethod
    def _decode_line(line: str) -> dict | None:
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            return None
        if isinstance(event, dict) and ("Ok" in event or "Err" in event):
            return None
        return event if isinstance(event, dict) else None

    def _consume_event(self, event: dict) -> bool | None:
        fullscreen = self._state.apply(event)
        if fullscreen is not None:
            self._emit(fullscreen)
        return fullscreen

    def _launch(self) -> None:
        if not self._running:
            return
        self._launched_at = self._clock()
        self._thread = threading.Thread(
            target=self._run_stream,
            name="pixel-pet-niri",
            daemon=True,
        )
        self._thread.start()

    def _run_stream(self) -> None:
        try:
            outputs = self._load_outputs()
            if not isinstance(outputs, dict):
                raise ValueError("niri outputs response is not an object")
            process = self._popen(
                [self._executable, "msg", "--json", "event-stream"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            self._dispatch(lambda: self._stream_ended(None))
            return
        if not self._running:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return
        self._process = process
        self._state = NiriState()
        self._state.outputs = outputs
        saw_workspaces = False
        if process.stdout is not None:
            for line in process.stdout:
                if not self._running or process is not self._process:
                    return
                event = self._decode_line(line)
                if event is None:
                    continue
                if "WorkspacesChanged" in event:
                    if saw_workspaces:
                        try:
                            refreshed = self._load_outputs()
                            self._state.outputs = (
                                refreshed if isinstance(refreshed, dict) else {}
                            )
                        except (OSError, ValueError, subprocess.SubprocessError):
                            self._state.outputs = {}
                            self._emit(False)
                    saw_workspaces = True
                self._consume_event(event)
        try:
            process.wait()
        except OSError:
            pass
        self._dispatch(lambda process=process: self._stream_ended(process))

    def _stream_ended(self, process) -> bool:
        if not self._running:
            return False
        if process is not None and process is not self._process:
            return False
        if (
            self._launched_at is not None
            and self._clock() - self._launched_at >= 30.0
        ):
            self._retry_index = 0
        self._process = None
        self._launched_at = None
        self._emit(False)
        delay = self.RETRY_DELAYS_MS[
            min(self._retry_index, len(self.RETRY_DELAYS_MS) - 1)
        ]
        self._retry_index += 1
        self._retry_source = self._schedule_retry(delay, self._retry)
        return False

    def _retry(self) -> bool:
        self._retry_source = None
        self._launch()
        return False

    def _emit(self, fullscreen: bool) -> None:
        if fullscreen == self._last_fullscreen:
            return
        self._last_fullscreen = fullscreen
        if self._running:
            self._dispatch(lambda: self._deliver(fullscreen))
        else:
            self._on_fullscreen(fullscreen)

    def _deliver(self, fullscreen: bool) -> bool:
        if self._running:
            self._on_fullscreen(fullscreen)
        return False
