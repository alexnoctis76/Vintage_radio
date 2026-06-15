"""TrackItemDelegate — title/artist layout and default-text suppression."""

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from gui.widgets.common.delegates import TrackItemDelegate, configure_track_title_item


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_track_delegate_clears_default_item_text(qapp) -> None:
    """Qt must not paint centered title text over the artist sub-line."""
    table = QtWidgets.QTableWidget(1, 4)
    table.setItem(0, 0, QtWidgets.QTableWidgetItem("Song Title"))
    table.setItem(0, 1, QtWidgets.QTableWidgetItem("Artist Name"))
    delegate = TrackItemDelegate(table)
    index = table.model().index(0, 0)
    option = QtWidgets.QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == ""


def test_track_delegate_reads_artist_from_hidden_column(qapp) -> None:
    table = QtWidgets.QTableWidget(2, 4)
    table.setColumnHidden(1, True)
    table.setItem(0, 0, QtWidgets.QTableWidgetItem("A"))
    table.setItem(0, 1, QtWidgets.QTableWidgetItem("Artist A"))
    table.setItem(1, 0, QtWidgets.QTableWidgetItem("B"))
    table.setItem(1, 1, QtWidgets.QTableWidgetItem("Artist B"))
    delegate = TrackItemDelegate(table)
    option = QtWidgets.QStyleOptionViewItem()
    option.widget = table
    idx = table.model().index(1, 0)
    assert delegate._artist_for_row(option, idx) == "Artist B"


def test_configure_track_title_item_hides_native_text(qapp) -> None:
    item = QtWidgets.QTableWidgetItem("Song Title")
    configure_track_title_item(item)
    brush = item.foreground()
    assert brush.color().alpha() == 0
