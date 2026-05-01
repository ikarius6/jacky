"""Dialog for creating and managing timers, reminders, and alarms."""

import logging
from datetime import datetime, time as dt_time

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QSpinBox, QTimeEdit, QLineEdit,
                             QPushButton, QCheckBox,
                             QStackedWidget, QWidget, QFormLayout, QDateEdit,
                             QScrollArea, QFrame, QSizePolicy)
from PyQt6.QtCore import Qt, QTime, QDate
from PyQt6.QtWidgets import QAbstractSpinBox
from PyQt6.QtGui import QFont

from utils.i18n import t
from core.timer_manager import TimerManager, _format_duration, _parse_iso

log = logging.getLogger("timer_dialog")

# ── Colours ──────────────────────────────────────────────────────
_BG           = "#FFF8F0"
_CARD_BG      = "#FFFFFF"
_TEXT          = "#5A3E2B"
_TEXT_SEC      = "#8B7355"
_BORDER       = "#E8D5C4"
_ACCENT        = "#F4A261"
_ACCENT_HOVER  = "#E8934E"
_ACCENT_LIGHT  = "#FFF0E0"
_DANGER        = "#E76F51"
_DANGER_HOVER  = "#D45B3E"

_STYLE = f"""
    QDialog {{
        background-color: {_BG};
        font-family: 'Segoe UI', system-ui, sans-serif;
        color: {_TEXT};
    }}
    QLabel {{
        color: {_TEXT};
        border: none;
        background: transparent;
    }}

    /* ── Inputs ── */
    QSpinBox, QTimeEdit, QDateEdit, QLineEdit {{
        border: 1.5px solid {_BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 10pt;
        background-color: {_CARD_BG};
        color: {_TEXT};
        selection-background-color: {_ACCENT_LIGHT};
    }}
    QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus, QLineEdit:focus {{
        border-color: {_ACCENT};
    }}
    QTimeEdit::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 18px;
        border-left: 1.5px solid {_BORDER};
        border-bottom: 1px solid {_BORDER};
        background: {_CARD_BG};
        border-top-right-radius: 7px;
    }}
    QTimeEdit::up-button:hover {{ background: {_ACCENT_LIGHT}; }}
    QTimeEdit::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 18px;
        border-left: 1.5px solid {_BORDER};
        background: {_CARD_BG};
        border-bottom-right-radius: 7px;
    }}
    QTimeEdit::down-button:hover {{ background: {_ACCENT_LIGHT}; }}
    QTimeEdit::up-arrow {{
        image: url(assets/arrow_up.svg);
        width: 7px; height: 5px;
    }}
    QTimeEdit::down-arrow {{
        image: url(assets/arrow_down.svg);
        width: 7px; height: 5px;
    }}
    QDateEdit::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 24px;
        border: none;
    }}
    QCheckBox {{
        color: {_TEXT};
        font-size: 10pt;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border: 1.5px solid {_BORDER};
        border-radius: 4px;
        background: {_CARD_BG};
    }}
    QCheckBox::indicator:checked {{
        background: {_ACCENT};
        border-color: {_ACCENT};
    }}

    /* ── Scroll area ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 6px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        background: {_BORDER};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
"""


class _SegmentedButton(QWidget):
    """Horizontal segmented tab selector."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._current = 0
        self._callback = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for i, (icon, label) in enumerate(items):
            btn = QPushButton(f" {icon}  {label}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            btn.setFixedHeight(38)
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            self._buttons.append(btn)
            layout.addWidget(btn)
        self._apply_styles()
        self._buttons[0].setChecked(True)

    def on_change(self, callback):
        self._callback = callback

    def _select(self, index):
        if index == self._current:
            self._buttons[index].setChecked(True)
            return
        self._current = index
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
        self._apply_styles()
        if self._callback:
            self._callback(index)

    def _apply_styles(self):
        n = len(self._buttons)
        for i, btn in enumerate(self._buttons):
            if i == 0:
                radius = "8px 0 0 8px"
            elif i == n - 1:
                radius = "0 8px 8px 0"
            else:
                radius = "0"
            border_l = f"1.5px solid {_BORDER}" if i > 0 else f"1.5px solid {_BORDER}"
            if btn.isChecked():
                bg, fg, brd, weight = _ACCENT, "#FFFFFF", _ACCENT, "bold"
            else:
                bg, fg, brd, weight = _CARD_BG, _TEXT, _BORDER, "normal"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {bg}; color: {fg};
                    border: 1.5px solid {brd};
                    border-radius: {radius};
                    font-size: 10pt; font-weight: {weight};
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background: {_ACCENT_HOVER if btn.isChecked() else _ACCENT_LIGHT};
                }}
            """)


class _TimerCard(QFrame):
    """Card widget for a single active timer/reminder/alarm entry."""

    def __init__(self, entry, on_cancel, parent=None):
        super().__init__(parent)
        self._entry = entry
        self.setObjectName("timerCard")
        self.setStyleSheet(f"""
            QFrame#timerCard {{
                background: {_CARD_BG};
                border: 1.5px solid {_BORDER};
                border-radius: 10px;
            }}
            QFrame#timerCard:hover {{
                border-color: {_ACCENT};
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)

        # Icon
        kind_icons = {"timer": "\u23F1", "reminder": "\U0001F4CB", "alarm": "\u23F0"}
        icon_lbl = QLabel(kind_icons.get(entry.kind, "\u23F1"))
        icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
        icon_lbl.setFixedWidth(32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # Title line
        kind_labels = {
            "timer": t("ui.timer_type_timer"),
            "reminder": t("ui.timer_type_reminder"),
            "alarm": t("ui.timer_type_alarm"),
        }
        title_parts = [kind_labels.get(entry.kind, entry.kind)]
        if entry.kind == "timer" and entry.original_seconds > 0:
            title_parts.append(f"({_format_duration(entry.original_seconds)})")
        title_lbl = QLabel(" ".join(title_parts))
        title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet(f"color: {_TEXT};")
        info_layout.addWidget(title_lbl)

        # Subtitle — fire time
        fire_dt = _parse_iso(entry.fire_at)
        if fire_dt:
            if entry.kind == "timer":
                fire_text = fire_dt.strftime("%H:%M:%S")
            else:
                fire_text = fire_dt.strftime("%d/%m/%Y  %H:%M")
            if entry.repeat == "daily":
                fire_text += "  \U0001F501"
        else:
            fire_text = entry.fire_at
        sub_lbl = QLabel(fire_text)
        sub_lbl.setFont(QFont("Segoe UI", 9))
        sub_lbl.setStyleSheet(f"color: {_TEXT_SEC};")
        info_layout.addWidget(sub_lbl)

        # Label (if any)
        if entry.label:
            note_lbl = QLabel(entry.label)
            note_lbl.setFont(QFont("Segoe UI", 9))
            note_lbl.setStyleSheet(f"color: {_TEXT_SEC}; font-style: italic;")
            note_lbl.setWordWrap(True)
            info_layout.addWidget(note_lbl)

        layout.addLayout(info_layout, 1)

        # Cancel button
        cancel_btn = QPushButton("\u2715")
        cancel_btn.setFixedSize(30, 30)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setToolTip(t("ui.timer_btn_cancel"))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1.5px solid {_BORDER};
                border-radius: 15px;
                font-size: 12pt;
                color: {_TEXT_SEC};
            }}
            QPushButton:hover {{
                background: {_DANGER};
                border-color: {_DANGER};
                color: #FFFFFF;
            }}
        """)
        cancel_btn.clicked.connect(lambda: on_cancel(entry.id))
        layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignVCenter)


class TimerDialog(QDialog):
    """Dialog for creating and managing timers, reminders, and alarms."""

    _PRESETS = [(60, "1 min"), (180, "3 min"), (300, "5 min"),
                (600, "10 min"), (900, "15 min"), (1800, "30 min"),
                (3600, "1 h")]

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        self._timer_manager: TimerManager = pet_window._timer_manager
        self.setWindowTitle(t("ui.timer_dialog_title"))
        self.setFixedWidth(420)
        self.setMinimumHeight(460)
        self.setStyleSheet(_STYLE)
        self._build_ui()
        self._refresh_list()

    # ── Build UI ─────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(14)

        # --- Segmented type selector ---
        self._tabs = _SegmentedButton([
            ("\u23F1", t("ui.timer_type_timer")),
            ("\U0001F4CB", t("ui.timer_type_reminder")),
            ("\u23F0", t("ui.timer_type_alarm")),
        ])
        self._tabs.on_change(self._on_type_changed)
        root.addWidget(self._tabs)

        # --- Stacked input panels ---
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_timer_panel())
        self._stack.addWidget(self._build_reminder_panel())
        self._stack.addWidget(self._build_alarm_panel())
        root.addWidget(self._stack)

        # --- Create button ---
        create_btn = QPushButton(f"  +  {t('ui.timer_btn_create')}")
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setFixedHeight(40)
        create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_ACCENT};
                border: none;
                border-radius: 10px;
                font-size: 11pt;
                font-weight: bold;
                color: #FFFFFF;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: {_ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: #D4823A; }}
        """)
        create_btn.clicked.connect(self._on_create)
        root.addWidget(create_btn)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_BORDER};")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # --- Active timers header ---
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        self._active_label = QLabel()
        self._active_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self._active_label.setStyleSheet(f"color: {_TEXT_SEC};")
        header_row.addWidget(self._active_label)
        header_row.addStretch()
        root.addLayout(header_row)

        # --- Scrollable card list ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        root.addWidget(scroll, 1)

    # ── Panel builders ───────────────────────────────────────────

    def _build_timer_panel(self):
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 4, 0, 0)
        vbox.setSpacing(10)

        # Quick presets
        presets_layout = QHBoxLayout()
        presets_layout.setSpacing(6)
        for seconds, label in self._PRESETS:
            chip = QPushButton(label)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(30)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background: {_ACCENT_LIGHT};
                    border: 1.5px solid {_BORDER};
                    border-radius: 15px;
                    padding: 0 10px;
                    font-size: 9pt;
                    color: {_TEXT};
                }}
                QPushButton:hover {{
                    background: {_ACCENT};
                    border-color: {_ACCENT};
                    color: #FFFFFF;
                }}
            """)
            chip.clicked.connect(
                lambda _, s=seconds: self._apply_preset(s))
            presets_layout.addWidget(chip)
        presets_layout.addStretch()
        vbox.addLayout(presets_layout)

        # Duration inputs
        dur_layout = QHBoxLayout()
        dur_layout.setSpacing(8)
        self._hours_spin = self._make_time_spin(0, 99, t("ui.timer_hours"))
        self._minutes_spin = self._make_time_spin(0, 59, t("ui.timer_minutes"))
        self._minutes_spin.setValue(5)
        self._seconds_spin = self._make_time_spin(0, 59, t("ui.timer_seconds"))
        dur_layout.addWidget(self._hours_spin)
        dur_layout.addWidget(self._minutes_spin)
        dur_layout.addWidget(self._seconds_spin)
        vbox.addLayout(dur_layout)

        # Note
        self._timer_label_edit = QLineEdit()
        self._timer_label_edit.setPlaceholderText(
            f"\U0001F4DD  {t('ui.timer_label_label')}")
        self._timer_label_edit.setFixedHeight(36)
        vbox.addWidget(self._timer_label_edit)

        return panel

    def _build_reminder_panel(self):
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 4, 0, 0)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._reminder_time = QTimeEdit()
        self._reminder_time.setDisplayFormat("HH:mm")
        self._reminder_time.setTime(QTime.currentTime().addSecs(3600))
        self._reminder_time.setFixedHeight(36)
        form.addRow(self._form_label(t("ui.timer_label_time")),
                    self._reminder_time)

        self._reminder_date = QDateEdit()
        self._reminder_date.setCalendarPopup(True)
        self._reminder_date.setDate(QDate.currentDate())
        self._reminder_date.setMinimumDate(QDate.currentDate())
        self._reminder_date.setFixedHeight(36)
        self._reminder_date.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        form.addRow(self._form_label(t("ui.timer_label_date")),
                    self._reminder_date)

        self._reminder_label_edit = QLineEdit()
        self._reminder_label_edit.setPlaceholderText(
            f"\U0001F4DD  {t('ui.timer_label_label')}")
        self._reminder_label_edit.setFixedHeight(36)
        form.addRow(self._form_label(t("ui.timer_label_label")),
                    self._reminder_label_edit)
        return panel

    def _build_alarm_panel(self):
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 4, 0, 0)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._alarm_time = QTimeEdit()
        self._alarm_time.setDisplayFormat("HH:mm")
        self._alarm_time.setTime(QTime(7, 0))
        self._alarm_time.setFixedHeight(36)
        form.addRow(self._form_label(t("ui.timer_label_time")),
                    self._alarm_time)

        self._alarm_repeat = QCheckBox(t("ui.timer_label_repeat"))
        self._alarm_repeat.setChecked(True)
        form.addRow("", self._alarm_repeat)

        self._alarm_label_edit = QLineEdit()
        self._alarm_label_edit.setPlaceholderText(
            f"\U0001F4DD  {t('ui.timer_label_label')}")
        self._alarm_label_edit.setFixedHeight(36)
        form.addRow(self._form_label(t("ui.timer_label_label")),
                    self._alarm_label_edit)
        return panel

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _make_time_spin(lo, hi, suffix):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSuffix(f" {suffix}")
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin.setFixedHeight(42)
        spin.setFont(QFont("Segoe UI", 14))
        spin.setStyleSheet(f"""
            QSpinBox {{
                border: 1.5px solid {_BORDER};
                border-radius: 10px;
                padding: 4px 8px;
                background: {_CARD_BG};
                color: {_TEXT};
                font-size: 14pt;
            }}
            QSpinBox:focus {{
                border-color: {_ACCENT};
            }}
            QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1.5px solid {_BORDER};
                border-bottom: 1px solid {_BORDER};
                background: {_CARD_BG};
                border-top-right-radius: 9px;
            }}
            QSpinBox::up-button:hover {{ background: {_ACCENT_LIGHT}; }}
            QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 22px;
                border-left: 1.5px solid {_BORDER};
                background: {_CARD_BG};
                border-bottom-right-radius: 9px;
            }}
            QSpinBox::down-button:hover {{ background: {_ACCENT_LIGHT}; }}
            QSpinBox::up-arrow {{
                image: url(assets/arrow_up.svg);
                width: 8px; height: 6px;
            }}
            QSpinBox::down-arrow {{
                image: url(assets/arrow_down.svg);
                width: 8px; height: 6px;
            }}
        """)
        return spin

    @staticmethod
    def _form_label(text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setStyleSheet(f"color: {_TEXT_SEC};")
        return lbl

    def _apply_preset(self, seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        self._hours_spin.setValue(h)
        self._minutes_spin.setValue(m)
        self._seconds_spin.setValue(s)

    # ── Events ───────────────────────────────────────────────────

    def _on_type_changed(self, index: int):
        self._stack.setCurrentIndex(index)

    def _on_create(self):
        kind_map = {0: "timer", 1: "reminder", 2: "alarm"}
        kind = kind_map.get(self._stack.currentIndex(), "timer")

        if kind == "timer":
            seconds = (self._hours_spin.value() * 3600 +
                       self._minutes_spin.value() * 60 +
                       self._seconds_spin.value())
            if seconds <= 0:
                return
            label = self._timer_label_edit.text().strip()
            entry = self._timer_manager.create_timer(seconds, label)
            if entry:
                from speech.dialogue import get_line
                duration_str = _format_duration(seconds, spoken=True)
                ack = get_line("timer_ack", self._pet_window.pet.name,
                               duration=duration_str)
                self._pet_window._say(ack, force=True)

        elif kind == "reminder":
            qt_time = self._reminder_time.time()
            qt_date = self._reminder_date.date()
            target_time = dt_time(qt_time.hour(), qt_time.minute())
            target_date = datetime(qt_date.year(), qt_date.month(), qt_date.day())
            fire_dt = datetime.combine(target_date.date(), target_time)
            label = self._reminder_label_edit.text().strip()
            entry = self._timer_manager.create_reminder(fire_dt, label)
            if entry:
                from speech.dialogue import get_line
                fire_parsed = _parse_iso(entry.fire_at)
                time_display = fire_parsed.strftime("%H:%M") if fire_parsed else ""
                ack = get_line("reminder_ack", self._pet_window.pet.name,
                               time=time_display, label=label)
                self._pet_window._say(ack, force=True)

        elif kind == "alarm":
            qt_time = self._alarm_time.time()
            target_time = dt_time(qt_time.hour(), qt_time.minute())
            label = self._alarm_label_edit.text().strip()
            repeat = "daily" if self._alarm_repeat.isChecked() else "none"
            entry = self._timer_manager.create_alarm(target_time, label, repeat)
            if entry:
                from speech.dialogue import get_line
                fire_parsed = _parse_iso(entry.fire_at)
                time_display = fire_parsed.strftime("%H:%M") if fire_parsed else ""
                ack = get_line("alarm_ack", self._pet_window.pet.name,
                               time=time_display)
                self._pet_window._say(ack, force=True)

        self._refresh_list()

    def _refresh_list(self):
        # Clear existing cards
        while self._list_layout.count() > 1:  # keep trailing stretch
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries = self._timer_manager.list_active()
        self._active_label.setText(
            f"{t('ui.timer_col_type')}  —  {len(entries)}" if entries
            else t("ui.timer_empty"))

        if not entries:
            empty = QLabel(t("ui.timer_empty"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setFont(QFont("Segoe UI", 10))
            empty.setStyleSheet(f"color: {_TEXT_SEC}; padding: 24px;")
            self._list_layout.insertWidget(0, empty)
            return

        for entry in entries:
            card = _TimerCard(entry, self._on_cancel)
            self._list_layout.insertWidget(
                self._list_layout.count() - 1, card)

    def _on_cancel(self, entry_id: str):
        self._timer_manager.cancel(entry_id)
        from speech.dialogue import get_line
        ack = get_line("timer_cancelled", self._pet_window.pet.name)
        if ack:
            self._pet_window._say(ack, force=True)
        self._refresh_list()
