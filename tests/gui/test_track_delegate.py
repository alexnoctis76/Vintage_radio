"""TrackItemDelegate — title/artist layout and default-text suppression."""

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

from gui.widgets.common.delegates import (
    TrackItemDelegate,
    TRACK_ARTIST_ROLE,
    TRACK_TITLE_ROLE,
    configure_track_title_item,
    track_artist_text,
    track_title_text,
)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_track_delegate_clears_default_item_text(qapp) -> None:
    """Qt must not paint centered title text over the artist sub-line."""
    table = QtWidgets.QTableWidget(1, 4)
    item = QtWidgets.QTableWidgetItem()
    configure_track_title_item(item, "Song Title", artist="Artist Name")
    table.setItem(0, 0, item)
    table.setItem(0, 1, QtWidgets.QTableWidgetItem("Artist Name"))
    delegate = TrackItemDelegate(table)
    index = table.model().index(0, 0)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == ""


def test_track_delegate_reads_artist_from_title_item(qapp) -> None:
    table = QtWidgets.QTableWidget(2, 4)
    table.setColumnHidden(1, True)
    for row, (title, artist) in enumerate((("A", "Artist A"), ("B", "Artist B"))):
        ti = QtWidgets.QTableWidgetItem()
        configure_track_title_item(ti, title, artist=artist)
        table.setItem(row, 0, ti)
        table.setItem(row, 1, QtWidgets.QTableWidgetItem(artist))
    delegate = TrackItemDelegate(table)
    option = QStyleOptionViewItem()
    option.widget = table
    idx = table.model().index(1, 0)
    assert delegate._artist_for_row(option, idx) == "Artist B"


def test_configure_track_title_item_hides_native_text(qapp) -> None:
    item = QtWidgets.QTableWidgetItem()
    configure_track_title_item(item, "Song Title", artist="Artist Name")
    assert item.text() == ""
    assert track_title_text(item) == "Song Title"
    assert track_artist_text(item) == "Artist Name"
    assert item.data(TRACK_TITLE_ROLE) == "Song Title"
    assert item.data(TRACK_ARTIST_ROLE) == "Artist Name"
    brush = item.foreground()
    assert brush.color().alpha() == 0


def test_delegate_paints_artist_for_every_row(qapp) -> None:
    """Regression: artist sub-line must render for all rows, not only the first."""
    import gui.theme as t
    from gui import ui_scale as u

    table = QtWidgets.QTableWidget(5, 4)
    table.setColumnHidden(1, True)
    titles = ["Azahar", "Ballad of the Lady", "Beauty Hurts", "Bloom", "breakfast"]
    artists = ["Juan Rios", "moow", "Jack Be", "j^p^n", "potsu"]
    for row, (title, artist) in enumerate(zip(titles, artists)):
        ti = QtWidgets.QTableWidgetItem()
        configure_track_title_item(ti, title, artist=artist)
        table.setItem(row, 0, ti)
        table.setItem(row, 1, QtWidgets.QTableWidgetItem(artist))

    delegate = TrackItemDelegate(table)
    row_h = u.px(t.TRACK_ROW_H)
    missing = []
    for row in range(5):
        idx = table.model().index(row, 0)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 500, row_h)
        opt.state = QStyle.StateFlag.State_Enabled
        opt.widget = table
        delegate.initStyleOption(opt, idx)
        img = QtGui.QImage(500, row_h, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtGui.QColor(t.TRACK_BG))
        painter = QtGui.QPainter(img)
        delegate.paint(painter, opt, idx)
        painter.end()
        hits = 0
        for y in range(int(row_h * 0.55), row_h - 2):
            for x in range(80, 300):
                c = img.pixelColor(x, y)
                if c.alpha() > 0 and (c.red() + c.green() + c.blue()) < 700:
                    hits += 1
        if hits < 20:
            missing.append((row, artists[row], hits))
    assert not missing, f"artist line not painted: {missing}"
