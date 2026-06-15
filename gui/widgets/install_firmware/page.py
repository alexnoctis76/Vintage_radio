"""Install Firmware page — layout from gui/scratch.html #firmwarePage."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u
from gui.widgets.install_firmware.device_section.device_section import DeviceSection
from gui.widgets.install_firmware.firmware_detail_panel.firmware_detail_panel import (
    FirmwareDetailPanel,
)
from gui.widgets.install_firmware.firmware_list_panel.firmware_list_panel import (
    FirmwareListPanel,
)
from gui.widgets.install_firmware.mode_tabs.mode_tabs import FirmwareModeTabs
from gui.widgets.install_firmware.panels_border_overlay import FirmwarePanelsHost


class InstallFirmwarePage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._panels_host: Optional[FirmwarePanelsHost] = None
        self._build()

    @property
    def device_section(self) -> DeviceSection:
        return self._device

    @property
    def mode_tabs(self) -> FirmwareModeTabs:
        return self._tabs

    @property
    def firmware_list(self) -> FirmwareListPanel:
        return self._software

    @property
    def detail_panel(self) -> FirmwareDetailPanel:
        return self._detail

    @property
    def action_bar(self) -> FirmwareDetailPanel:
        return self._detail

    def set_firmware_mode(self, mode: str) -> None:
        self._tabs.set_mode(mode)
        self._software.set_mode(mode)
        self._detail.set_mode(mode)

    def _build(self) -> None:
        self.setObjectName("installFirmwarePage")
        self.setStyleSheet(f"#installFirmwarePage {{ background: {t.C_BG}; }}")

        l, top, r, bot = t.LM_PAGE_MARGINS
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(l, top, r, bot)
        layout.setSpacing(t.IF_PAGE_ROW_GAP)

        self._device = DeviceSection()
        layout.addWidget(self._device)

        self._panels_host = FirmwarePanelsHost()
        self._panels_grid = QtWidgets.QGridLayout(self._panels_host)
        grid = self._panels_grid
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self._tabs = FirmwareModeTabs()
        grid.addWidget(self._tabs, 0, 0)

        self._software = FirmwareListPanel()
        grid.addWidget(self._software, 1, 0)

        self._detail = FirmwareDetailPanel()
        grid.addWidget(self._detail, 1, 1)

        grid.setColumnMinimumWidth(0, u.px_layout(t.IF_LIST_WIDTH_HINT))
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 1)

        self._panels_host.set_split_anchor(self._software)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self._panels_host)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 9)
        shadow.setColor(QtGui.QColor(75, 43, 18, 31))
        self._panels_host.setGraphicsEffect(shadow)

        layout.addWidget(self._panels_host, 1)

    def apply_ui_zoom(self) -> None:
        self.reload_theme()

    def reload_theme(self) -> None:
        self.setStyleSheet(f"#installFirmwarePage {{ background: {t.C_BG}; }}")
        if self._panels_host is not None:
            self._panels_grid.setColumnMinimumWidth(0, u.px_layout(t.IF_LIST_WIDTH_HINT))
            self._panels_host.reload_border()
        self._device.reload_theme()
        self._tabs.reload_theme()
        self._software.reload_theme()
        self._detail.reload_theme()
