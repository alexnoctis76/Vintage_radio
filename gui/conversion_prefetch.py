"""Background MP3 conversion into the host sync cache while the app is idle."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Set

from PyQt6 import QtCore

if TYPE_CHECKING:
    from gui.radio_manager import RadioManager


class ConversionPrefetchController(QtCore.QObject):
    """Debounced idle prefetch of converted MP3s after library imports."""

    def __init__(self, owner: RadioManager) -> None:
        super().__init__(owner)
        self._owner = owner
        self._pending_song_ids: Set[int] = set()
        self._prefetch_all = False
        self._running = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self._start_worker)
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[QtCore.QObject] = None

    def schedule(self, song_ids: Optional[List[int]] = None) -> None:
        if not self._owner._retain_conversion_cache():
            return
        if song_ids is not None:
            if not song_ids:
                return
            self._pending_song_ids.update(int(s) for s in song_ids)
        else:
            self._prefetch_all = True
        self._timer.start()

    def _start_worker(self) -> None:
        if self._running:
            self._timer.start()
            return
        song_ids = None if self._prefetch_all else list(self._pending_song_ids)
        self._pending_song_ids.clear()
        self._prefetch_all = False
        if song_ids is not None and not song_ids:
            return

        self._running = True
        profile = self._owner._selected_conversion_profile()
        software_source = self._owner._software_source_for_sync()
        dfplayer_eq = (
            self._owner._selected_dfplayer_eq() if software_source == "our" else "normal"
        )

        class _Worker(QtCore.QObject):
            finished = QtCore.pyqtSignal(int)
            error = QtCore.pyqtSignal(str)

            def __init__(
                self,
                sd_manager,
                *,
                song_ids: Optional[List[int]],
                conversion_profile: str,
                dfplayer_eq: str,
            ) -> None:
                super().__init__()
                self._sd_manager = sd_manager
                self._song_ids = song_ids
                self._conversion_profile = conversion_profile
                self._dfplayer_eq = dfplayer_eq

            @QtCore.pyqtSlot()
            def run(self) -> None:
                try:
                    count = self._sd_manager.prefetch_basic_conversion_cache(
                        song_ids=self._song_ids,
                        conversion_profile=self._conversion_profile,
                        dfplayer_eq=self._dfplayer_eq,
                    )
                    self.finished.emit(int(count))
                except Exception as exc:
                    self.error.emit(str(exc))

        thread = QtCore.QThread(self)
        worker = _Worker(
            self._owner.sd_manager,
            song_ids=song_ids,
            conversion_profile=profile,
            dfplayer_eq=dfplayer_eq,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_worker_finished(self, count: int) -> None:
        if count > 0:
            self._owner.statusBar().showMessage(
                f"Prepared {count} track(s) in the background for faster syncing.",
                6000,
            )

    def _on_worker_error(self, msg: str) -> None:
        from gui.session_log import write_session_line

        write_session_line(f"Background conversion prefetch failed: {msg}", prefix="PREFETCH")

    def _on_thread_finished(self) -> None:
        self._running = False
        self._thread = None
        self._worker = None
        if self._pending_song_ids or self._prefetch_all:
            self._timer.start()
