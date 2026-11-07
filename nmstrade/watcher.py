"""Background thread: notice new saves and parse them off the UI thread."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from .playerstate import Snapshot, read_snapshot
from .savefile import newest_save


class SaveWatcher(threading.Thread):
    def __init__(self, out: "queue.Queue", root: Path | None = None, poll: float = 2.0,
                 fixed_file: Path | None = None):
        super().__init__(daemon=True)
        self.out = out
        self.root = root
        self.poll = poll
        self.fixed_file = fixed_file
        self._stop = threading.Event()
        self._last: tuple[str, float, int] | None = None
        self.force = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _pick(self) -> Path | None:
        if self.fixed_file:
            return self.fixed_file if self.fixed_file.exists() else None
        return newest_save(self.root)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                path = self._pick()
                if path is None:
                    self.out.put(("status", "Nie znaleziono zapisu NMS – ustaw folder w USTAWIENIACH"))
                else:
                    st = path.stat()
                    sig = (str(path), st.st_mtime, st.st_size)
                    if sig != self._last or self.force.is_set():
                        self.force.clear()
                        time.sleep(0.8)  # let the game finish writing
                        st2 = path.stat()
                        if (st2.st_mtime, st2.st_size) != (st.st_mtime, st.st_size):
                            continue
                        self.out.put(("status", f"Czytam {path.name}…"))
                        snap: Snapshot = read_snapshot(path)
                        self._last = sig
                        self.out.put(("snapshot", snap))
            except Exception as e:  # keep watching whatever happens
                self.out.put(("error", f"{type(e).__name__}: {e}"))
                self._last = None
                self._stop.wait(max(self.poll, 5))
                continue
            self._stop.wait(self.poll)
