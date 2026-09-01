from __future__ import annotations

import sys
import uuid
import threading
import traceback
from functools import partial
from typing import Callable
from dataclasses import dataclass

from qtpy import QtWidgets, QtCore

from ayon_core import style

from .utils import (
    install_ffmpeg,
    install_oiio,
    InstallTracker,
)


@dataclass
class ErrorInfo:
    message: str
    detail: str | None


class InstallItem:
    def __init__(self, tracker: InstallTracker, func: Callable):
        self._id = uuid.uuid4().hex
        self._func = partial(func, tracker)
        self._tracker = tracker
        self._thread = None
        self._error: ErrorInfo | None = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def title(self) -> str:
        return self._tracker.get_title()

    @property
    def failed(self) -> bool:
        return self._error is not None

    @property
    def error(self) -> ErrorInfo | None:
        return self._error

    @property
    def progress(self) -> int:
        return self._tracker.get_progress()

    @property
    def label(self) -> str:
        return self._tracker.get_label()

    @property
    def finished(self) -> bool:
        if self._thread is None:
            return True
        return not self._thread.is_alive()

    def _start(self):
        try:
            self._func()

        except PermissionError:
            traceback.print_exc()
            self._error = ErrorInfo(
                "FAILED: Missing permissions",
                "Failed to download or extract files because"
                " of missing permissions on disk."
                "\n\nPlease contact your administrator.",
            )

        except Exception:
            tb = "".join(traceback.format_exception(*sys.exc_info()))
            # Print exception to console
            print(tb)
            self._error = ErrorInfo(
                "FAILED: Unknown error",
                "An unknown error occurred while downloading or extracting."
                "\n\nPlease contact your administrator.\n\n"
                f"{tb}"
            )

    def install(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._start)
            self._thread.start()

    def finish(self):
        if self._thread is None:
            return
        self._thread.join()
        self._thread = None


class DownloadController:
    def __init__(self, ffmpeg: bool, oiio: bool):
        ffmpeg_tracker = InstallTracker("FFmpeg")
        if not ffmpeg:
            ffmpeg_tracker.set_finished()

        oiio_tracker = InstallTracker("OpenImageIO")
        if not oiio:
            oiio_tracker.set_finished()

        items = [
            InstallItem(ffmpeg_tracker, install_ffmpeg),
            InstallItem(oiio_tracker, install_oiio),
        ]

        self._items = items
        self._items_by_id = {
            item.id: item
            for item in items
        }
        self._install_started = False
        self._install_finished = False

    def items(self):
        for item_id, item in self._items_by_id.items():
            yield item_id, item

    @property
    def install_items(self):
        for item in self._items:
            yield item

    @property
    def install_started(self) -> bool:
        return self._install_started

    @property
    def install_finished(self) -> bool:
        return self._install_finished

    @property
    def install_failed(self):
        for item in self.install_items:
            if item.failed:
                return True
        return False

    @property
    def is_installing(self) -> bool:
        if not self._install_started or self._install_finished:
            return False

        for item in self.install_items:
            if not item.finished:
                return True
        return False

    def start_install(self):
        if self._install_started:
            return
        self._install_started = True
        for item in self.install_items:
            item.install()

    def finish_install(self):
        if self._install_finished:
            return
        for item in self.install_items:
            item.finish()
        self._install_finished = True


class ProgressBarAYFFOIIO(QtWidgets.QProgressBar):
    def __init__(
        self, install_item: InstallItem, parent: QtWidgets.QWidget
    ):
        super().__init__(parent)
        self.setRange(0, 100)
        self._install_item = install_item
        self._text = "Starting..."

    def text(self):
        if self._text is not None:
            return self._text
        return super().text()

    def update_progress(self):
        text, tooltip = self._get_text_tooltip()
        self.setToolTip(tooltip)
        self._text = text
        self.repaint()

    def _get_text_tooltip(self) -> tuple[str | None, str]:
        if self._install_item.failed:
            error = self._install_item.error
            progress_label = error.message
            tooltip = ""
            if error.detail:
                tooltip = error.detail
            return progress_label, tooltip

        progress = self._install_item.progress
        if progress == -1:
            value = 0
            if self._install_item.finished:
                value = 100
            self.setMaximum(value)
            self.setValue(value)
            return self._install_item.label, ""
        self.setMaximum(100)
        self.setValue(progress)
        return None, ""

        # TODO replace with 'progress.is_running' once is fixed
        progress_is_running = not (
            not progress.started
            or progress.transfer_done
            or progress.failed
        )
        if progress_is_running:
            transfer_progress = progress.transfer_progress
            if transfer_progress is None:
                return "Downloading...", ""
            self.setValue(int(transfer_progress))
            return None, ""
        return "Extracting...", ""


class DownloadWindow(QtWidgets.QWidget):
    finished = QtCore.Signal()

    def __init__(
        self,
        controller: DownloadController,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent=parent)

        self.setWindowTitle("Installing 3rd party dependencies")

        content_widget = QtWidgets.QWidget(self)

        content_layout = QtWidgets.QGridLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)

        progress_widgets = []
        row = 0
        for item in controller.install_items:
            title_widget = QtWidgets.QLabel(item.title, content_widget)
            progress_widget = ProgressBarAYFFOIIO(item, content_widget)
            progress_widgets.append(progress_widget)
            content_layout.addWidget(title_widget, row, 0)
            content_layout.addWidget(progress_widget, row, 1)
            row += 1

        content_layout.setColumnStretch(0, 0)
        content_layout.setColumnStretch(1, 1)
        content_layout.setRowStretch(row, 1)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(content_widget, 1)

        timer = QtCore.QTimer()
        timer.setInterval(10)
        timer.timeout.connect(self._on_timer)

        self._timer = timer
        self._controller = controller
        self._progress_widgets = progress_widgets
        self._first_show = True
        self._start_on_show = False

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # Set stylesheet and resize
            self.setStyleSheet(_get_stylesheets())
            self.resize(360, 200)

        if self._start_on_show:
            self.start()

    def _update_progress(self):
        for widget in self._progress_widgets:
            widget.update_progress()

    def _on_timer(self):
        if self._controller.install_finished:
            self._timer.stop()
            if not self._controller.install_failed:
                self.finished.emit()
            return

        if not self._controller.install_started:
            self._controller.start_install()
            self._update_progress()
            return

        if self._controller.is_installing:
            self._update_progress()
            return

        self._controller.finish_install()
        self._update_progress()

    def start(self):
        if self._first_show:
            self._start_on_show = True
            return
        if self._controller.install_started:
            return
        self._timer.start()


def show_download_window(
    ffmpeg: bool,
    oiio: bool,
    parent: QtWidgets.QWidget | None = None,
) -> DownloadWindow:
    controller = DownloadController(ffmpeg, oiio)
    window = DownloadWindow(controller, parent=parent)
    window.show()
    window.start()
    return window


STYLE_OVERRIDES = """
ProgressBarAYFFOIIO {
    font-weight: bold;
    text-align: center;
    border-radius: 6px;
}

ProgressBarAYFFOIIO:horizontal {
    height: 20px;
}

ProgressBarAYFFOIIO:vertical {
    width: 20px;
}

ProgressBarAYFFOIIO2::chunk {
    background: qlineargradient(
        x1: 0, y1: 0.5,
        x2: 1, y2: 0.5,
        stop: 0 {palette:blue-base},
        stop: 1 {palette:green-base}
    );
}
ProgressBarAYFFOIIO::chunk {
    border: 1px solid #373D48;
    background: qlineargradient(
        x1:0, y1:0,
        x2:0, y2:1,
        stop: 0 #3d9cc7,
        stop: 0.1 #3a6dad,
        stop: 0.9 #3a6dad,
        stop:1 #101c3f);
    border-radius: 6px;
}
"""


def _get_stylesheets():
    stylesheets = style.load_stylesheet()
    stylesheets += STYLE_OVERRIDES
    return stylesheets
