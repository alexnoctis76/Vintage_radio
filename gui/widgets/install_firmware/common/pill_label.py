"""Rounded pill labels for the Install Firmware page — colours/sizes from gui.theme."""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

import gui.theme as t
from gui import ui_scale as u

PillVariant = Literal[
    "badge_official",
    "badge_soft",
    "notes_readonly",
    "notes_editable",
    "status_on",
    "status_off",
    "card_tag_selected",
    "card_tag_idle",
]


def _pill_height(variant: PillVariant, fixed_height: Optional[int]) -> int:
    if fixed_height is not None:
        return u.px(fixed_height)
    if variant in ("badge_official", "badge_soft"):
        return u.px(t.IF_SW_BADGE_H)
    if variant in ("notes_readonly", "notes_editable"):
        return u.px(t.IF_NOTES_PILL_H)
    if variant in ("status_on", "status_off"):
        return u.px(t.IF_STATUS_PILL_H)
    if variant in ("card_tag_selected", "card_tag_idle"):
        return u.px(t.IF_CARD_TAG_H)
    return u.px(20)


def _fs(base: float) -> str:
    return f"{u.px(base)}px"


def pill_stylesheet(variant: PillVariant, *, height_px: int) -> str:
    radius = t.if_pill_radius(height_px)
    if variant == "badge_official":
        return (
            f"color:{t.IF_SW_BADGE_FG}; font-size:{_fs(t.IF_SW_BADGE_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t.IF_SW_BADGE_TOP}, stop:1 {t.IF_SW_BADGE_BOT});"
            f"border-radius:{radius}px; padding:{u.px(t.IF_SW_BADGE_PAD_V)}px {u.px(t.IF_SW_BADGE_PAD_H)}px;"
        )
    if variant == "badge_soft":
        return (
            f"color:{t.IF_SW_BADGE_FG}; font-size:{_fs(t.IF_SW_BADGE_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t.IF_SW_BADGE_SOFT_TOP}, stop:1 {t.IF_SW_BADGE_SOFT_BOT});"
            f"border-radius:{radius}px; padding:{u.px(t.IF_SW_BADGE_PAD_V)}px {u.px(t.IF_SW_BADGE_PAD_H)}px;"
        )
    if variant == "notes_editable":
        return (
            f"color:{t.IF_NOTES_PILL_FG}; font-size:{_fs(t.IF_NOTES_PILL_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t.IF_NOTES_PILL_EDIT_TOP}, stop:1 {t.IF_NOTES_PILL_EDIT_BOT});"
            f"border-radius:{radius}px; padding:{u.px(t.IF_NOTES_PILL_PAD_V)}px {u.px(t.IF_NOTES_PILL_PAD_H)}px;"
        )
    if variant == "notes_readonly":
        return (
            f"color:{t.IF_NOTES_PILL_FG}; font-size:{_fs(t.IF_NOTES_PILL_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:{t.IF_NOTES_PILL_BG}; border-radius:{radius}px;"
            f"padding:{u.px(t.IF_NOTES_PILL_PAD_V)}px {u.px(t.IF_NOTES_PILL_PAD_H)}px;"
        )
    if variant == "status_on":
        return (
            f"color:{t.IF_STATUS_PILL_FG}; font-size:{_fs(t.IF_STATUS_PILL_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t.IF_STATUS_PILL_ON_TOP}, stop:1 {t.IF_STATUS_PILL_ON_BOT});"
            f"border-radius:{radius}px; padding:{u.px(t.IF_STATUS_PILL_PAD_V)}px {u.px(t.IF_STATUS_PILL_PAD_H)}px;"
        )
    if variant == "status_off":
        return (
            f"color:{t.IF_STATUS_PILL_FG}; font-size:{_fs(t.IF_STATUS_PILL_FONT)}; "
            f"font-weight:{u.qss_weight(900)};"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t.IF_STATUS_PILL_OFF_TOP}, stop:1 {t.IF_STATUS_PILL_OFF_BOT});"
            f"border-radius:{radius}px; padding:{u.px(t.IF_STATUS_PILL_PAD_V)}px {u.px(t.IF_STATUS_PILL_PAD_H)}px;"
        )
    if variant == "card_tag_selected":
        return (
            f"color:{t.IF_CARD_TAG_FG_SEL}; font-size:{_fs(t.IF_CARD_TAG_PX)}; "
            f"font-weight:{u.qss_weight(800)};"
            f"background:{t.IF_CARD_TAG_BG_SEL}; border-radius:{radius}px;"
            f"padding:0;"
        )
    return (
        f"color:{t.IF_CARD_TAG_FG_IDLE}; font-size:{_fs(t.IF_CARD_TAG_PX)}; "
        f"font-weight:{u.qss_weight(800)};"
        f"background:{t.IF_CARD_TAG_BG_IDLE}; border-radius:{radius}px;"
        f"padding:0;"
    )


class PillLabel(QtWidgets.QLabel):
    """Fixed-size horizontal pill; does not stretch with parent layout."""

    def __init__(
        self,
        text: str = "",
        *,
        variant: PillVariant = "notes_readonly",
        fixed_width: Optional[int] = None,
        fixed_height: Optional[int] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self._fixed_height = fixed_height
        self.setObjectName("ifPillLabel")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        h = _pill_height(variant, fixed_height)
        self._fixed_height = h
        self.setFixedHeight(h)
        if fixed_width is not None:
            self.setFixedWidth(fixed_width)
        elif variant in ("notes_readonly", "notes_editable"):
            self.setFixedWidth(u.px(t.IF_NOTES_PILL_W))
        self.apply_variant(variant)

    def reload_theme(self) -> None:
        """Re-apply pill sizing after UI zoom / theme reload."""
        self.apply_variant(self._variant)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API
        super().setText(text)
        if self._variant in ("badge_official", "badge_soft"):
            self._sync_badge_geometry()

    def _sync_badge_geometry(self) -> None:
        """Re-measure after text or stylesheet changes (badge labels only)."""
        fm = self.fontMetrics()
        text = self.text()
        w = fm.horizontalAdvance(text) + 2 * u.px(t.IF_SW_BADGE_PAD_H) + u.px(4)
        self.setFixedWidth(max(w, u.px(t.IF_SW_BADGE_MIN_W)))
        h = max(u.px(t.IF_SW_BADGE_H), fm.height() + 2 * u.px(t.IF_SW_BADGE_PAD_V))
        self.setFixedHeight(h)
        radius = t.if_pill_radius(h)
        self.setStyleSheet(
            f"QLabel#ifPillLabel {{ {pill_stylesheet(self._variant, height_px=h)} "
            f"min-height:{h}px; max-height:{h}px; border-radius:{radius}px; }}"
        )

    def apply_variant(self, variant: PillVariant) -> None:
        self._variant = variant
        h = _pill_height(variant, self._fixed_height)
        radius = t.if_pill_radius(h)
        self.setStyleSheet(
            f"QLabel#ifPillLabel {{ {pill_stylesheet(variant, height_px=h)} "
            f"min-height:{h}px; max-height:{h}px; border-radius:{radius}px; }}"
        )
        if variant in ("badge_official", "badge_soft"):
            self._sync_badge_geometry()
