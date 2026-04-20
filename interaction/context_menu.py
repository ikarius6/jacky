from PyQt6.QtWidgets import (QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QCheckBox, QSpinBox, QLineEdit, QPushButton,
                             QGroupBox, QFormLayout, QComboBox, QPlainTextEdit,
                             QTabWidget, QWidget, QGridLayout, QScrollArea,
                             QFrame, QSizePolicy, QListWidget, QInputDialog,
                             QProgressBar, QMessageBox)
from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QAction, QFont, QPixmap

import copy
import logging

from utils.config_manager import load_config, save_config
from utils.i18n import t, get_permission_defs, available_languages, current_language
from core import character as character_mod
from core.character import (get_character_names, get_character_preview,
                            reload_characters, get_writable_sprites_root)
from utils.shop import (fetch_shop_catalog, fetch_preview_bytes,
                        download_character, delete_character, needs_update,
                        ShopCharacter)
from speech.llm_provider import fetch_ollama_models
from interaction.key_binding_input import KeyBindingInput

log = logging.getLogger(__name__)


class PetContextMenu(QMenu):
    """Right-click context menu for interacting with the pet."""

    def __init__(self, pet_window):
        super().__init__()
        self._pet_window = pet_window
        self._build_menu()
        self._style_menu()

    def _style_menu(self):
        self.setStyleSheet("""
            QMenu {
                background-color: #FFF8F0;
                border: 2px solid #DDB892;
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI';
                font-size: 11pt;
                color: #5A3E2B;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
                color: #5A3E2B;
            }
            QMenu::item:selected {
                background-color: #FFDDB5;
                color: #5A3E2B;
            }
            QMenu::separator {
                height: 1px;
                background: #DDB892;
                margin: 4px 8px;
            }
        """)

    @property
    def _pet_name(self) -> str:
        return self._pet_window.pet.name

    def _build_menu(self):
        self._pet_action = QAction(t("ui.menu_pet", name=self._pet_name), self)
        self._pet_action.triggered.connect(self._pet_window.on_pet_clicked)
        self.addAction(self._pet_action)

        self._feed_action = QAction(t("ui.menu_feed"), self)
        self._feed_action.triggered.connect(self._pet_window.on_feed)
        self.addAction(self._feed_action)

        self._attack_action = QAction(t("ui.menu_attack"), self)
        self._attack_action.triggered.connect(self._pet_window.on_attack)
        self.addAction(self._attack_action)

        self.addSeparator()

        # Peer interactions submenu (dynamic, rebuilt on each show)
        self._peers_menu = QMenu(t("ui.menu_peers"), self)
        self._peers_menu.setStyleSheet(self.styleSheet())
        self._peers_action = self.addMenu(self._peers_menu)
        self._peers_action.setVisible(False)

        self.addSeparator()

        self._modes_menu = QMenu(t("ui.menu_modes"), self)
        self._modes_menu.setStyleSheet(self.styleSheet())

        self._silent_action = QAction(t("ui.menu_silent"), self)
        self._silent_action.setCheckable(True)
        self._silent_action.setChecked(self._pet_window._config.get("silent_mode", False))
        self._silent_action.triggered.connect(self._toggle_silent_mode)
        self._modes_menu.addAction(self._silent_action)

        self._gamer_action = QAction(t("ui.menu_gamer"), self)
        self._gamer_action.setCheckable(True)
        self._gamer_action.setChecked(self._pet_window._gamer_mode)
        self._gamer_action.triggered.connect(self._toggle_gamer_mode)
        self._modes_menu.addAction(self._gamer_action)

        self.addMenu(self._modes_menu)

        self.addSeparator()

        self._ask_action = QAction(t("ui.menu_ask"), self)
        self._ask_action.triggered.connect(self._open_ask_dialog)
        self._ask_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._ask_action)

        self._listen_action = QAction(t("ui.menu_listen"), self)
        self._listen_action.triggered.connect(self._pet_window.on_listen_toggle)
        self._listen_action.setEnabled(self._pet_window._llm_enabled and bool(self._pet_window._config.get("assemblyai_api_key", "").strip()))
        self.addAction(self._listen_action)

        self._look_action = QAction(t("ui.menu_look"), self)
        self._look_action.triggered.connect(self._pet_window.on_look)
        self._look_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._look_action)

        self._timers_action = QAction(t("ui.menu_timers"), self)
        self._timers_action.triggered.connect(self._open_timer_dialog)
        self.addAction(self._timers_action)

        # Routines submenu (dynamic, rebuilt on each show)
        self._routines_menu = QMenu(t("ui.menu_routines"), self)
        self._routines_menu.setStyleSheet(self.styleSheet())
        self._routines_action = self.addMenu(self._routines_menu)
        self._routines_action.setVisible(False)

        self.addSeparator()

        self._settings_action = QAction(t("ui.menu_settings"), self)
        self._settings_action.triggered.connect(self._open_settings)
        self.addAction(self._settings_action)

        self.addSeparator()

        self._quit_action = QAction(t("ui.menu_quit"), self)
        self._quit_action.triggered.connect(self._pet_window.on_quit)
        self.addAction(self._quit_action)

    def _open_ask_dialog(self):
        dlg = AskDialog(self._pet_window)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            question = dlg.get_text().strip()
            if question:
                self._pet_window.on_ask(question)

    def _open_timer_dialog(self):
        from interaction.timer_dialog import TimerDialog
        dlg = TimerDialog(self._pet_window)
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self._pet_window)
        dlg.exec()

    def _toggle_silent_mode(self, checked: bool):
        """Toggle silent mode (in-memory only for this instance)."""
        self._pet_window._config["silent_mode"] = checked
        self._pet_window._silent_mode = checked

    def _toggle_gamer_mode(self, checked: bool):
        """Toggle gamer mode — saves/restores settings via PetWindow."""
        self._pet_window.toggle_gamer_mode(checked)
        # Sync the silent checkbox since gamer mode changes it
        self._silent_action.setChecked(self._pet_window._config.get("silent_mode", False))

    def refresh_llm_state(self):
        """Update the Preguntar/Mirar actions enabled state after config reload."""
        self._ask_action.setEnabled(self._pet_window._llm_enabled)
        self._listen_action.setEnabled(self._pet_window._llm_enabled and bool(self._pet_window._config.get("assemblyai_api_key", "").strip()))
        vision_allowed = self._pet_window._perm("allow_vision")
        self._look_action.setEnabled(self._pet_window._llm_enabled)
        self._look_action.setVisible(self._pet_window._llm_enabled and vision_allowed)
        self._silent_action.setChecked(self._pet_window._config.get("silent_mode", False))
        self._gamer_action.setChecked(self._pet_window._gamer_mode)
        # Refresh all labels for current language
        self._pet_action.setText(t("ui.menu_pet", name=self._pet_name))
        self._feed_action.setText(t("ui.menu_feed"))
        self._attack_action.setText(t("ui.menu_attack"))
        self._peers_menu.setTitle(t("ui.menu_peers"))
        self._modes_menu.setTitle(t("ui.menu_modes"))
        self._routines_menu.setTitle(t("ui.menu_routines"))
        self._silent_action.setText(t("ui.menu_silent"))
        self._gamer_action.setText(t("ui.menu_gamer"))
        self._ask_action.setText(t("ui.menu_ask"))
        self._listen_action.setText(t("ui.menu_listen"))
        self._look_action.setText(t("ui.menu_look"))
        self._settings_action.setText(t("ui.menu_settings"))
        self._quit_action.setText(t("ui.menu_quit"))

    def show_at(self, pos: QPoint):
        self._rebuild_peers_menu()
        self._rebuild_routines_menu()
        self.popup(pos)

    def _rebuild_peers_menu(self):
        """Rebuild the Compañeros submenu with current live peers."""
        self._peers_menu.clear()
        pw = self._pet_window
        if not hasattr(pw, '_peer_discovery'):
            self._peers_action.setVisible(False)
            return

        peers = pw._peer_discovery.get_peers()
        if not peers:
            self._peers_action.setVisible(False)
            return

        self._peers_action.setVisible(True)
        for peer in peers:
            peer_sub = QMenu(f"🐾 {peer.display_name}", self._peers_menu)
            peer_sub.setStyleSheet(self.styleSheet())

            greet = QAction(t("ui.peer_greet"), peer_sub)
            greet.triggered.connect(lambda checked, p=peer: pw._peer_interactions.do_greet(p))
            peer_sub.addAction(greet)

            attack = QAction(t("ui.peer_attack"), peer_sub)
            attack.triggered.connect(lambda checked, p=peer: pw._peer_interactions.do_attack(p))
            peer_sub.addAction(attack)

            chase = QAction(t("ui.peer_chase"), peer_sub)
            chase.triggered.connect(lambda checked, p=peer: pw._peer_interactions.do_chase(p))
            peer_sub.addAction(chase)

            dance = QAction(t("ui.peer_dance"), peer_sub)
            dance.triggered.connect(lambda checked, p=peer: pw._peer_interactions.do_dance(p))
            peer_sub.addAction(dance)

            fight = QAction(t("ui.peer_fight"), peer_sub)
            fight.triggered.connect(lambda checked, p=peer: pw._peer_interactions.do_fight(p))
            peer_sub.addAction(fight)

            self._peers_menu.addMenu(peer_sub)

    def _rebuild_routines_menu(self):
        """Rebuild the Rutinas submenu with loaded routines."""
        self._routines_menu.clear()
        pw = self._pet_window
        if not hasattr(pw, '_routine_manager'):
            self._routines_action.setVisible(False)
            return

        items = pw._routine_manager.list_routines()
        if not items:
            self._routines_action.setVisible(False)
            return

        self._routines_action.setVisible(True)
        manual = [(r, s) for r, s in items if r.is_manual]
        auto = [(r, s) for r, s in items if r.is_automatic]

        for routine, status in manual:
            label = f"▶ {routine.title}"
            if status == "running":
                label = f"⏳ {routine.title}"
            action = QAction(label, self._routines_menu)
            if status == "running":
                action.setEnabled(False)
            else:
                rid = routine.id
                action.triggered.connect(lambda checked, _rid=rid: pw._routine_manager.run_routine(_rid))
            self._routines_menu.addAction(action)

        if manual and auto:
            self._routines_menu.addSeparator()

        for routine, status in auto:
            interval = routine.schedule.interval if routine.schedule else 0
            if interval >= 3600:
                interval_str = f"{interval // 3600}h"
            elif interval >= 60:
                interval_str = f"{interval // 60}min"
            else:
                interval_str = f"{interval}s"
            label = f"⏱ {routine.title} ({interval_str})"
            if status != "idle":
                label += f" — {status}"
            action = QAction(label, self._routines_menu)
            action.setEnabled(False)
            self._routines_menu.addAction(action)


class AskDialog(QDialog):
    """Small dialog with a text field to ask the pet a question via LLM."""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        pet_name = pet_window.pet.name
        self.setWindowTitle(t("ui.ask_title", name=pet_name))
        self.setFixedWidth(360)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF8F0;
                font-family: 'Segoe UI';
                color: #5A3E2B;
            }
            QLabel {
                color: #5A3E2B;
            }
            QPlainTextEdit {
                border: 1px solid #DDB892;
                border-radius: 6px;
                padding: 6px;
                font-size: 11pt;
                background-color: #FFFFFF;
                color: #5A3E2B;
            }
            QPushButton {
                background-color: #FFDDB5;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                color: #5A3E2B;
            }
            QPushButton:hover {
                background-color: #FFD0A0;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        label = QLabel(t("ui.ask_label"))
        label.setStyleSheet("font-size: 11pt; color: #5A3E2B;")
        layout.addWidget(label)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText(t("ui.ask_placeholder"))
        self._text_edit.setFixedHeight(80)
        layout.addWidget(self._text_edit)

        btn_layout = QHBoxLayout()
        send_btn = QPushButton(t("ui.btn_send"))
        send_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(t("ui.btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(send_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_text(self) -> str:
        return self._text_edit.toPlainText()


PREVIEW_SIZE = 96
CARD_BORDER_NORMAL = "2px solid #DDB892"
CARD_BORDER_SELECTED = "3px solid #E8913A"
CARD_BORDER_NOT_INSTALLED = "2px dashed #C0C0C0"


# ── Background workers ──────────────────────────────────────────────────

class ShopFetchWorker(QThread):
    """Fetch the remote shop catalog in a background thread."""
    finished = pyqtSignal(list)  # list[ShopCharacter]

    def __init__(self, shop_url: str, parent=None):
        super().__init__(parent)
        self._url = shop_url

    def run(self):
        catalog = fetch_shop_catalog(self._url)
        self.finished.emit(catalog)


class PreviewFetchWorker(QThread):
    """Download a single preview image in background."""
    finished = pyqtSignal(str, bytes)  # (char_id, image_bytes)

    def __init__(self, char_id: str, url: str, parent=None):
        super().__init__(parent)
        self._char_id = char_id
        self._url = url

    def run(self):
        data = fetch_preview_bytes(self._url)
        if data:
            self.finished.emit(self._char_id, data)


class DownloadWorker(QThread):
    """Download and extract a character pack in background."""
    progress = pyqtSignal(int, int)   # (bytes_downloaded, total_bytes)
    finished = pyqtSignal(str)        # extracted path
    error = pyqtSignal(str)           # error message

    def __init__(self, shop_char: ShopCharacter, dest_dir: str, parent=None):
        super().__init__(parent)
        self._char = shop_char
        self._dest = dest_dir

    def run(self):
        try:
            path = download_character(self._char, self._dest, self._on_progress)
            self.finished.emit(path)
        except Exception as exc:
            self.error.emit(str(exc))

    def _on_progress(self, downloaded: int, total: int):
        self.progress.emit(downloaded, total)


class CharacterCard(QFrame):
    """Card showing a character preview, name, and action buttons.

    Supports three visual states:
    - **installed** (local character, selectable)
    - **not_installed** (from shop, shows download button)
    - **update_available** (installed but shop has newer version)
    """

    clicked = pyqtSignal(str)           # emits character name (select)
    download_requested = pyqtSignal(object)  # emits ShopCharacter
    delete_requested = pyqtSignal(str)  # emits character name

    def __init__(self, char_name: str, *,
                 is_selected: bool = False,
                 installed: bool = True,
                 shop_char: ShopCharacter | None = None,
                 update_available: bool = False,
                 source: str = "bundled",
                 parent=None):
        super().__init__(parent)
        self._name = char_name
        self._selected = is_selected
        self._installed = installed
        self._shop_char = shop_char
        self._update_available = update_available
        self._source = source
        self._downloading = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(PREVIEW_SIZE + 28, PREVIEW_SIZE + 90)
        self._build()
        self._apply_style()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Preview image
        self._img_label = QLabel()
        self._img_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self._installed:
            preview_path = get_character_preview(self._name)
            if preview_path:
                pix = QPixmap(preview_path)
                if not pix.isNull():
                    pix = pix.scaled(
                        QSize(PREVIEW_SIZE, PREVIEW_SIZE),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                self._img_label.setPixmap(pix)
            else:
                self._img_label.setText("?")
                self._img_label.setStyleSheet("font-size: 32pt; color: #B0B0B0;")
        else:
            # Placeholder — will be replaced by shop preview if loaded
            self._img_label.setText("?")
            self._img_label.setStyleSheet("font-size: 32pt; color: #B0B0B0;")
        layout.addWidget(self._img_label)

        # Name label
        name_label = QLabel(self._name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 8pt; color: #5A3E2B;")
        name_label.setFixedHeight(20)
        layout.addWidget(name_label)

        # Action area (button or progress bar)
        self._action_widget = QWidget()
        self._action_layout = QVBoxLayout(self._action_widget)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(0)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar { border: 1px solid #DDB892; border-radius: 3px; background: #FFF8F0; }
            QProgressBar::chunk { background: #E8913A; border-radius: 2px; }
        """)
        self._progress.hide()
        self._action_layout.addWidget(self._progress)

        self._action_btn = QPushButton()
        self._action_btn.setFixedHeight(22)
        self._action_btn.setStyleSheet("""
            QPushButton { font-size: 8pt; padding: 1px 4px; background: #FFDDB5;
                          border: 1px solid #DDB892; border-radius: 3px; color: #5A3E2B; }
            QPushButton:hover { background: #FFD0A0; }
        """)

        if not self._installed and self._shop_char:
            size = self._shop_char.size_mb
            self._action_btn.setText(t("ui.btn_download", size=f"{size:.1f}"))
            self._action_btn.clicked.connect(self._on_download_click)
        elif self._update_available:
            self._action_btn.setText(t("ui.btn_update"))
            self._action_btn.setStyleSheet("""
                QPushButton { font-size: 8pt; padding: 1px 4px; background: #D4EDDA;
                              border: 1px solid #A3D9A5; border-radius: 3px; color: #155724; }
                QPushButton:hover { background: #C3E6CB; }
            """)
            self._action_btn.clicked.connect(self._on_download_click)
        else:
            self._action_btn.hide()

        self._action_layout.addWidget(self._action_btn)

        # Delete button (downloaded characters only)
        self._delete_btn = QPushButton(t("ui.btn_delete"))
        self._delete_btn.setFixedHeight(22)
        self._delete_btn.setStyleSheet("""
            QPushButton { font-size: 8pt; padding: 1px 4px; background: #F8D7DA;
                          border: 1px solid #F5C6CB; border-radius: 3px; color: #721C24; }
            QPushButton:hover { background: #F5C6CB; }
        """)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        self._delete_btn.hide()
        if self._installed and self._source == "downloaded":
            self._delete_btn.show()
        self._action_layout.addWidget(self._delete_btn)

        layout.addWidget(self._action_widget)

    def _apply_style(self):
        if not self._installed:
            border = CARD_BORDER_NOT_INSTALLED
            bg = "#F5F5F5"
            hover_bg = "#EEEEEE"
        elif self._selected:
            border = CARD_BORDER_SELECTED
            bg = "#FFF0DC"
            hover_bg = "#FFF0DC"
        else:
            border = CARD_BORDER_NORMAL
            bg = "#FFFFFF"
            hover_bg = "#FFF0DC"
        self.setStyleSheet(f"""
            CharacterCard {{
                background-color: {bg};
                border: {border};
                border-radius: 8px;
            }}
            CharacterCard:hover {{
                background-color: {hover_bg};
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def set_preview_pixmap(self, pixmap: QPixmap):
        """Set the preview image (used for shop previews loaded async)."""
        if not pixmap.isNull():
            pix = pixmap.scaled(
                QSize(PREVIEW_SIZE, PREVIEW_SIZE),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_label.setPixmap(pix)
            self._img_label.setStyleSheet("")

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def char_name(self) -> str:
        return self._name

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def source(self) -> str:
        return self._source

    @property
    def shop_char(self) -> ShopCharacter | None:
        return self._shop_char

    def mousePressEvent(self, event):
        if self._installed and not self._downloading:
            self.clicked.emit(self._name)
        super().mousePressEvent(event)

    # ── download / progress ──────────────────────────────────────────

    def _on_download_click(self):
        if self._shop_char:
            self.download_requested.emit(self._shop_char)

    def start_download_ui(self):
        """Switch card to downloading state."""
        self._downloading = True
        self._delete_btn.hide()
        self._action_btn.hide()
        self._progress.setValue(0)
        self._progress.show()

    def update_progress(self, downloaded: int, total: int):
        if total > 0:
            self._progress.setMaximum(100)
            self._progress.setValue(int(downloaded * 100 / total))
        else:
            self._progress.setMaximum(0)  # indeterminate

    def download_finished(self):
        """Switch card to installed state after successful download."""
        self._downloading = False
        self._installed = True
        self._update_available = False
        self._progress.hide()
        self._delete_btn.show()
        self._action_btn.hide()
        self._apply_style()
        # Refresh preview from local files
        preview_path = get_character_preview(self._name)
        if preview_path:
            pix = QPixmap(preview_path)
            if not pix.isNull():
                pix = pix.scaled(
                    QSize(PREVIEW_SIZE, PREVIEW_SIZE),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._img_label.setPixmap(pix)
                self._img_label.setStyleSheet("")

    def download_failed(self, error: str):
        """Show error and restore button."""
        self._downloading = False
        self._progress.hide()
        self._action_btn.show()
        self._action_btn.setText(t("ui.download_error", error=error[:30]))
        self._action_btn.setStyleSheet("""
            QPushButton { font-size: 7pt; padding: 1px 4px; background: #F8D7DA;
                          border: 1px solid #F5C6CB; border-radius: 3px; color: #721C24; }
        """)


# Permission definitions: (config_key, group)
# Labels and descriptions are loaded from i18n at runtime.
# group: "observe" = non-destructive, "destructive" = modifies windows
_PERMISSION_KEYS = [
    ("allow_comment",  "observe"),
    ("allow_peek",     "observe"),
    ("allow_sit",      "observe"),
    ("allow_vision",   "observe"),
    ("allow_push",     "destructive"),
    ("allow_shake",    "destructive"),
    ("allow_minimize", "destructive"),
    ("allow_resize",   "destructive"),
    ("allow_knock",    "destructive"),
    ("allow_drag",     "destructive"),
    ("allow_tidy",     "destructive"),
    ("allow_topple",   "destructive"),
    ("allow_screen_interact", "destructive"),
    ("allow_cache",    "observe"),
]


def _build_permission_defs() -> list[tuple]:
    """Build PERMISSION_DEFS from i18n data.

    Returns list of (config_key, label, description, group) tuples.
    """
    perm_i18n = get_permission_defs()
    result = []
    for key, group in _PERMISSION_KEYS:
        info = perm_i18n.get(key, {})
        label = info.get("label", key)
        desc = info.get("desc", "")
        result.append((key, label, desc, group))
    return result


# Keep module-level references for backward compatibility (used by pet_window.py)
PERMISSION_DEFS = _build_permission_defs()
DEFAULT_PERMISSIONS = {p[0]: True for p in PERMISSION_DEFS}
DEFAULT_PERMISSIONS["allow_screen_interact"] = False  # opt-in: cursor control is intrusive


class SettingsDialog(QDialog):
    """Settings dialog for configuring the pet."""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        self.setWindowTitle(t("ui.settings_title", name=pet_window.pet.name))
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF8F0;
                font-family: 'Segoe UI';
                color: #5A3E2B;
            }
            QLabel {
                color: #5A3E2B;
            }
            QCheckBox {
                color: #5A3E2B;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #DDB892;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
                color: #5A3E2B;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 6px;
                color: #5A3E2B;
            }
            QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
                background-color: #FFFFFF;
                color: #5A3E2B;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QPushButton {
                background-color: #FFDDB5;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                color: #5A3E2B;
            }
            QPushButton:hover {
                background-color: #FFD0A0;
            }
            QTabWidget::pane {
                border: 1px solid #DDB892;
                border-radius: 6px;
                background-color: #FFF8F0;
            }
            QTabBar::tab {
                background-color: #FFE8CC;
                border: 1px solid #DDB892;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                color: #5A3E2B;
            }
            QTabBar::tab:selected {
                background-color: #FFF8F0;
            }
            QTabBar::tab:!selected {
                margin-top: 2px;
            }
            QScrollArea {
                background: transparent;
            }
            QTabWidget > QWidget {
                background-color: #FFF8F0;
            }
            QToolTip {
                background-color: #FFF8F0;
                color: #5A3E2B;
                border: 1px solid #DDB892;
            }
        """)
        self._config = copy.deepcopy(pet_window._config)
        self._selected_char = self._config.get("character", "Forest Ranger 3")
        self._char_cards: list[CharacterCard] = []
        self._shop_catalog: list[ShopCharacter] = []
        self._active_workers: list[QThread] = []
        self._perm_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_character_tab(), t("ui.tab_character"))
        tabs.addTab(self._build_settings_tab(), t("ui.tab_settings"))
        tabs.addTab(self._build_llm_tab(), t("ui.tab_llm"))
        tabs.addTab(self._build_voice_tab(), t("ui.tab_voice"))
        tabs.addTab(self._build_permissions_tab(), t("ui.tab_permissions"))
        layout.addWidget(tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton(t("ui.btn_save"))
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton(t("ui.btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _build_character_tab(self) -> QWidget:
        """Build the visual character selection grid with shop integration."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(4, 8, 4, 4)

        # Header row: hint + refresh button
        header = QHBoxLayout()
        hint = QLabel(t("ui.select_character"))
        hint.setStyleSheet("font-size: 10pt; color: #5A3E2B; padding: 2px 4px;")
        header.addWidget(hint)
        header.addStretch()

        self._shop_status = QLabel()
        self._shop_status.setStyleSheet("font-size: 8pt; color: #999; padding: 2px 4px;")
        header.addWidget(self._shop_status)

        refresh_btn = QPushButton(t("ui.shop_refresh"))
        refresh_btn.setFixedHeight(24)
        refresh_btn.setStyleSheet("""
            QPushButton { font-size: 8pt; padding: 2px 8px; background: #FFDDB5;
                          border: 1px solid #DDB892; border-radius: 3px; color: #5A3E2B; }
            QPushButton:hover { background: #FFD0A0; }
        """)
        refresh_btn.clicked.connect(self._fetch_shop_catalog)
        header.addWidget(refresh_btn)
        tab_layout.addLayout(header)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(10)
        self._grid.setContentsMargins(6, 6, 6, 6)

        # Build initial grid with local characters only
        self._populate_grid()

        scroll.setWidget(self._grid_widget)
        tab_layout.addWidget(scroll)

        # Start fetching shop catalog in background
        self._fetch_shop_catalog()

        return tab

    def _build_settings_tab(self) -> QWidget:
        """Build the general settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Language selector
        lang_group = QGroupBox(t("ui.label_language").rstrip(":"))
        lang_form = QFormLayout()
        self._lang_combo = QComboBox()
        langs = available_languages()
        current_lang = self._config.get("language", "es")
        for code, name in langs:
            self._lang_combo.addItem(name, code)
        idx = self._lang_combo.findData(current_lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        lang_form.addRow(t("ui.label_language"), self._lang_combo)
        lang_group.setLayout(lang_form)
        layout.addWidget(lang_group)

        # Pet name group
        name_group = QGroupBox(t("ui.group_pet"))
        name_form = QFormLayout()
        self._pet_name_edit = QLineEdit(self._config.get("pet_name", "Jacky"))
        self._pet_name_edit.setMaxLength(30)
        self._pet_name_edit.setPlaceholderText(t("ui.placeholder_name"))
        name_form.addRow(t("ui.label_name"), self._pet_name_edit)
        name_group.setLayout(name_form)
        layout.addWidget(name_group)

        # Movement group
        move_group = QGroupBox(t("ui.group_movement"))
        move_form = QFormLayout()
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(1, 10)
        self._speed_spin.setValue(self._config.get("movement_speed", 3))
        move_form.addRow(t("ui.label_speed"), self._speed_spin)
        move_group.setLayout(move_form)
        layout.addWidget(move_group)

        # Intervals group
        interval_group = QGroupBox(t("ui.group_intervals"))
        interval_form = QFormLayout()

        self._idle_min = QSpinBox()
        self._idle_min.setRange(1, 300)
        self._idle_max = QSpinBox()
        self._idle_max.setRange(1, 300)
        idle_iv = self._config.get("idle_interval", [5, 15])
        self._idle_min.setValue(idle_iv[0])
        self._idle_max.setValue(idle_iv[1])
        idle_layout = QHBoxLayout()
        idle_layout.addWidget(self._idle_min)
        idle_layout.addWidget(QLabel("–"))
        idle_layout.addWidget(self._idle_max)
        interval_form.addRow(t("ui.label_idle"), idle_layout)

        self._chat_min = QSpinBox()
        self._chat_min.setRange(1, 600)
        self._chat_max = QSpinBox()
        self._chat_max.setRange(1, 600)
        chat_iv = self._config.get("chat_interval", [20, 60])
        self._chat_min.setValue(chat_iv[0])
        self._chat_max.setValue(chat_iv[1])
        chat_layout = QHBoxLayout()
        chat_layout.addWidget(self._chat_min)
        chat_layout.addWidget(QLabel("–"))
        chat_layout.addWidget(self._chat_max)
        interval_form.addRow(t("ui.label_chat"), chat_layout)

        self._winchk_min = QSpinBox()
        self._winchk_min.setRange(1, 300)
        self._winchk_max = QSpinBox()
        self._winchk_max.setRange(1, 300)
        winchk_iv = self._config.get("window_check_interval", [10, 30])
        self._winchk_min.setValue(winchk_iv[0])
        self._winchk_max.setValue(winchk_iv[1])
        winchk_layout = QHBoxLayout()
        winchk_layout.addWidget(self._winchk_min)
        winchk_layout.addWidget(QLabel("–"))
        winchk_layout.addWidget(self._winchk_max)
        interval_form.addRow(t("ui.label_wincheck"), winchk_layout)

        interval_group.setLayout(interval_form)
        layout.addWidget(interval_group)

        # Window interaction group
        win_group = QGroupBox(t("ui.group_window"))
        win_form = QFormLayout()
        self._always_on_top = QCheckBox(t("ui.check_always_on_top"))
        self._always_on_top.setChecked(self._config.get("always_on_top", True))
        win_form.addRow(self._always_on_top)
        self._win_enabled = QCheckBox(t("ui.check_window_detect"))
        self._win_enabled.setChecked(self._config.get("window_interaction_enabled", True))
        win_form.addRow(self._win_enabled)
        self._win_push = QCheckBox(t("ui.check_window_push"))
        self._win_push.setChecked(self._config.get("window_push_enabled", True))
        win_form.addRow(self._win_push)
        self._gravity = QCheckBox(t("ui.check_gravity"))
        self._gravity.setChecked(self._config.get("gravity", False))
        win_form.addRow(self._gravity)
        win_group.setLayout(win_form)
        layout.addWidget(win_group)

        # Shop URL
        shop_group = QGroupBox(t("ui.label_shop_url").rstrip(":"))
        shop_form = QFormLayout()
        self._shop_url = QLineEdit(self._config.get("shop_url", "https://hackers.army/jacky/shop.json"))
        self._shop_url.setPlaceholderText("https://hackers.army/jacky/shop.json")
        shop_form.addRow(t("ui.label_shop_url"), self._shop_url)
        shop_group.setLayout(shop_form)
        layout.addWidget(shop_group)

        # Debug group
        debug_group = QGroupBox(t("ui.group_debug"))
        debug_form = QFormLayout()
        self._debug_logging = QCheckBox(t("ui.check_debug_log"))
        self._debug_logging.setChecked(self._config.get("debug_logging", False))
        debug_form.addRow(self._debug_logging)
        debug_group.setLayout(debug_form)
        layout.addWidget(debug_group)

        layout.addStretch()
        return tab

    def _build_llm_tab(self) -> QWidget:
        """Build the LLM configuration tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._llm_enabled = QCheckBox(t("ui.check_llm_enable"))
        self._llm_enabled.setChecked(self._config.get("llm_enabled", False))
        layout.addWidget(self._llm_enabled)

        # Provider selector
        provider_group = QGroupBox(t("ui.group_provider"))
        provider_form = QFormLayout()
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["ollama", "openrouter", "groq"])
        current_provider = self._config.get("llm_provider", "ollama")
        idx = self._provider_combo.findText(current_provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        provider_form.addRow(t("ui.label_provider"), self._provider_combo)
        provider_group.setLayout(provider_form)
        layout.addWidget(provider_group)

        # --- Ollama fields ---
        self._ollama_group = QGroupBox("Ollama")
        ollama_form = QFormLayout()
        self._ollama_url = QLineEdit(self._config.get("ollama_url", "http://localhost:11434"))
        ollama_form.addRow(t("ui.label_url"), self._ollama_url)
        model_layout = QHBoxLayout()
        self._ollama_model = QComboBox()
        self._ollama_model.setEditable(True)
        self._refresh_models_btn = QPushButton("🔄")
        self._refresh_models_btn.setFixedWidth(50)
        self._refresh_models_btn.setToolTip(t("ui.tooltip_refresh"))
        self._refresh_models_btn.clicked.connect(self._refresh_models)
        model_layout.addWidget(self._ollama_model)
        model_layout.addWidget(self._refresh_models_btn)
        ollama_form.addRow(t("ui.label_model"), model_layout)
        self._ollama_group.setLayout(ollama_form)
        layout.addWidget(self._ollama_group)
        if current_provider == "ollama":
            self._refresh_models()

        # --- OpenRouter fields ---
        self._or_group = QGroupBox("OpenRouter")
        or_form = QFormLayout()
        self._or_api_key = QLineEdit(self._config.get("openrouter_api_key", ""))
        self._or_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_api_key.setPlaceholderText("sk-or-...")
        or_form.addRow(t("ui.label_apikey"), self._or_api_key)
        
        or_hint = QLabel(t("ui.label_get_apikey", url="https://openrouter.ai/keys", name="OpenRouter"))
        or_hint.setOpenExternalLinks(True)
        or_hint.setStyleSheet("font-size: 9pt;")
        or_form.addRow("", or_hint)
        
        self._or_model = QLineEdit(self._config.get("openrouter_model", "google/gemma-4-26b-a4b-it:free"))
        self._or_model.setPlaceholderText("google/gemma-4-26b-a4b-it:free")
        or_form.addRow(t("ui.label_model"), self._or_model)
        self._or_group.setLayout(or_form)
        layout.addWidget(self._or_group)

        # --- Groq fields ---
        self._groq_group = QGroupBox("Groq")
        groq_form = QFormLayout()

        # API keys list
        self._groq_keys_list = QListWidget()
        self._groq_keys_list.setFixedHeight(90)
        self._groq_keys_list.setStyleSheet(
            "QListWidget { font-size: 10pt; }"
            "QListWidget::item { padding: 2px 4px; }"
        )
        self._groq_api_keys: list[str] = list(self._config.get("groq_api_keys", []))
        for k in self._groq_api_keys:
            self._groq_keys_list.addItem(self._mask_key(k))

        keys_btn_layout = QHBoxLayout()
        keys_btn_layout.setContentsMargins(0, 0, 0, 0)
        groq_add_btn = QPushButton(t("ui.btn_add"))
        groq_add_btn.setToolTip(t("ui.tooltip_add_key"))
        groq_add_btn.clicked.connect(self._groq_add_key)
        groq_del_btn = QPushButton(t("ui.btn_remove"))
        groq_del_btn.setToolTip(t("ui.tooltip_del_key"))
        groq_del_btn.clicked.connect(self._groq_del_key)
        keys_btn_layout.addWidget(groq_add_btn)
        keys_btn_layout.addWidget(groq_del_btn)
        keys_btn_layout.addStretch()

        keys_layout = QVBoxLayout()
        keys_layout.setSpacing(4)
        keys_layout.addWidget(self._groq_keys_list)
        keys_layout.addLayout(keys_btn_layout)
        
        groq_hint = QLabel(t("ui.label_get_apikey", url="https://console.groq.com/keys", name="Groq"))
        groq_hint.setOpenExternalLinks(True)
        groq_hint.setStyleSheet("font-size: 9pt;")
        keys_layout.addWidget(groq_hint)
        
        groq_form.addRow(t("ui.label_apikeys"), keys_layout)

        self._groq_model = QLineEdit(
            self._config.get("groq_model", "meta-llama/llama-4-scout-17b-16e-instruct"))
        self._groq_model.setPlaceholderText("meta-llama/llama-4-scout-17b-16e-instruct")
        groq_form.addRow(t("ui.label_model"), self._groq_model)
        self._groq_group.setLayout(groq_form)
        layout.addWidget(self._groq_group)

        # Show/hide the right fields for current provider
        self._on_provider_changed(current_provider)

        layout.addStretch()
        return tab

    def _build_voice_tab(self) -> QWidget:
        """Build the Voice / STT / TTS configuration tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # General Voice Settings
        gen_group = QGroupBox(t("ui.group_voice_general"))
        gen_form = QFormLayout()
        
        self._response_mode = QComboBox()
        self._response_mode.addItem(t("ui.mode_text"), "text")
        self._response_mode.addItem(t("ui.mode_voice"), "voice")
        self._response_mode.addItem(t("ui.mode_both"), "both")
        current_mode = self._config.get("response_mode", "both")
        idx = self._response_mode.findData(current_mode)
        if idx >= 0:
            self._response_mode.setCurrentIndex(idx)
        gen_form.addRow(t("ui.label_response_mode"), self._response_mode)
        
        self._listen_shortcut = KeyBindingInput()
        self._listen_shortcut.set_shortcut(self._config.get("listen_shortcut", "ctrl+shift+space"))
        gen_form.addRow(t("ui.label_listen_shortcut"), self._listen_shortcut)
        
        gen_group.setLayout(gen_form)
        layout.addWidget(gen_group)
        
        # AssemblyAI (STT) Settings
        aai_group = QGroupBox(t("ui.group_assemblyai"))
        aai_form = QFormLayout()
        
        aai_desc = QLabel(t("ui.desc_assemblyai"))
        aai_desc.setWordWrap(True)
        aai_desc.setStyleSheet("font-size: 9pt; padding-bottom: 4px;")
        aai_form.addRow(aai_desc)
        
        self._aai_api_key = QLineEdit(self._config.get("assemblyai_api_key", ""))
        self._aai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._aai_api_key.setPlaceholderText(t("ui.placeholder_apikey"))
        aai_form.addRow(t("ui.label_apikey"), self._aai_api_key)
        
        aai_hint = QLabel(t("ui.label_get_apikey", url="https://www.assemblyai.com/", name="AssemblyAI"))
        aai_hint.setOpenExternalLinks(True)
        aai_hint.setStyleSheet("font-size: 9pt;")
        aai_form.addRow("", aai_hint)
        
        self._aai_model = QLineEdit(self._config.get("assemblyai_model", "universal-streaming-multilingual"))
        aai_form.addRow(t("ui.label_model"), self._aai_model)
        
        aai_group.setLayout(aai_form)
        layout.addWidget(aai_group)
        
        # ElevenLabs (TTS) Settings
        el_group = QGroupBox(t("ui.group_elevenlabs"))
        el_form = QFormLayout()
        
        el_desc = QLabel(t("ui.desc_elevenlabs"))
        el_desc.setWordWrap(True)
        el_desc.setStyleSheet("font-size: 9pt; padding-bottom: 4px;")
        el_form.addRow(el_desc)
        
        self._el_api_key = QLineEdit(self._config.get("elevenlabs_api_key", ""))
        self._el_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._el_api_key.setPlaceholderText(t("ui.placeholder_apikey"))
        el_form.addRow(t("ui.label_apikey"), self._el_api_key)
        
        el_hint = QLabel(t("ui.label_get_apikey", url="https://elevenlabs.io/", name="ElevenLabs"))
        el_hint.setOpenExternalLinks(True)
        el_hint.setStyleSheet("font-size: 9pt;")
        el_form.addRow("", el_hint)
        
        self._el_voice_id = QLineEdit(self._config.get("elevenlabs_voice_id", "U0W3edavfdI8ibPeeteQ"))
        el_form.addRow(t("ui.label_voice_id"), self._el_voice_id)
        
        self._el_model = QLineEdit(self._config.get("elevenlabs_model", "eleven_flash_v2_5"))
        el_form.addRow(t("ui.label_model"), self._el_model)
        
        el_group.setLayout(el_form)
        layout.addWidget(el_group)
        
        layout.addStretch()
        return tab

    def _build_permissions_tab(self) -> QWidget:
        """Build the granular permissions tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        hint = QLabel(t("ui.perm_hint"))
        hint.setStyleSheet("font-size: 10pt; color: #5A3E2B; padding: 2px 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        perms = self._config.get("permissions", DEFAULT_PERMISSIONS)
        perm_defs = _build_permission_defs()

        # Toggle-all buttons
        toggle_layout = QHBoxLayout()
        enable_all_btn = QPushButton(t("ui.btn_enable_all"))
        enable_all_btn.clicked.connect(lambda: self._set_all_perms(True))
        disable_all_btn = QPushButton(t("ui.btn_disable_all"))
        disable_all_btn.clicked.connect(lambda: self._set_all_perms(False))
        toggle_layout.addWidget(enable_all_btn)
        toggle_layout.addWidget(disable_all_btn)
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)

        # Non-destructive group
        obs_group = QGroupBox(t("ui.group_observe"))
        obs_form = QVBoxLayout()
        for key, label, desc, group in perm_defs:
            if group != "observe":
                continue
            cb = QCheckBox(label)
            cb.setChecked(perms.get(key, True))
            cb.setToolTip(desc)
            cb.setStyleSheet("font-size: 10pt; padding: 2px 0px;")
            obs_form.addWidget(cb)
            self._perm_checks[key] = cb
        obs_group.setLayout(obs_form)
        layout.addWidget(obs_group)

        # Destructive group
        dest_group = QGroupBox(t("ui.group_destructive"))
        dest_form = QVBoxLayout()
        for key, label, desc, group in perm_defs:
            if group != "destructive":
                continue
            cb = QCheckBox(label)
            cb.setChecked(perms.get(key, True))
            cb.setToolTip(desc)
            cb.setStyleSheet("font-size: 10pt; padding: 2px 0px;")
            dest_form.addWidget(cb)
            self._perm_checks[key] = cb
        dest_group.setLayout(dest_form)
        layout.addWidget(dest_group)

        layout.addStretch()
        return tab

    def _set_all_perms(self, checked: bool):
        """Toggle all permission checkboxes."""
        for cb in self._perm_checks.values():
            cb.setChecked(checked)

    # ── character grid / shop ────────────────────────────────────────

    def _populate_grid(self):
        """Build the character card grid from local + shop data."""
        # Clear existing cards
        for card in self._char_cards:
            card.setParent(None)
            card.deleteLater()
        self._char_cards.clear()

        # Build merged list: local characters first, then shop-only
        local_names = get_character_names()
        # Map shop entries by name for lookup
        shop_by_name: dict[str, ShopCharacter] = {
            sc.name: sc for sc in self._shop_catalog
        }

        cols = 3
        idx = 0

        # 1. Local (installed) characters
        for name in local_names:
            char_info = character_mod.CHARACTERS.get(name, {})
            sc = shop_by_name.pop(name, None)
            update_avail = False
            if sc and char_info.get("version"):
                update_avail = needs_update(char_info["version"], sc.version)

            card = CharacterCard(
                name,
                is_selected=(name == self._selected_char),
                installed=True,
                shop_char=sc,
                update_available=update_avail,
                source=char_info.get("source", "bundled"),
            )
            card.clicked.connect(self._on_card_clicked)
            card.download_requested.connect(self._on_download_requested)
            card.delete_requested.connect(self._on_delete_requested)
            self._grid.addWidget(card, idx // cols, idx % cols)
            self._char_cards.append(card)
            idx += 1

        # 2. Shop-only (not installed) characters
        for sc in shop_by_name.values():
            card = CharacterCard(
                sc.name,
                is_selected=False,
                installed=False,
                shop_char=sc,
                source="shop",
            )
            card.download_requested.connect(self._on_download_requested)
            self._grid.addWidget(card, idx // cols, idx % cols)
            self._char_cards.append(card)
            idx += 1

            # Fetch preview image async
            if sc.preview_url:
                worker = PreviewFetchWorker(sc.id, sc.preview_url, parent=self)
                worker.finished.connect(self._on_preview_loaded)
                self._active_workers.append(worker)
                worker.start()

    def _fetch_shop_catalog(self):
        """Start a background fetch of the shop catalog."""
        shop_url = self._config.get("shop_url", "")
        if not shop_url:
            return
        self._shop_status.setText(t("ui.shop_loading"))
        worker = ShopFetchWorker(shop_url, parent=self)
        worker.finished.connect(self._on_shop_fetched)
        self._active_workers.append(worker)
        worker.start()

    def _on_shop_fetched(self, catalog: list):
        """Handle shop catalog response — merge with local and rebuild grid."""
        self._shop_catalog = catalog
        if catalog:
            self._shop_status.setText("")
        else:
            self._shop_status.setText(t("ui.shop_error"))
        self._populate_grid()

    def _on_preview_loaded(self, char_id: str, data: bytes):
        """Set the preview pixmap on the matching card."""
        pix = QPixmap()
        pix.loadFromData(data)
        if pix.isNull():
            return
        for card in self._char_cards:
            sc = card.shop_char
            if sc and sc.id == char_id:
                card.set_preview_pixmap(pix)
                break

    def _on_card_clicked(self, name: str):
        self._selected_char = name
        for card in self._char_cards:
            card.set_selected(card.char_name == name)

    def _on_download_requested(self, shop_char: ShopCharacter):
        """Start downloading a character pack."""
        # Find the card
        card = None
        for c in self._char_cards:
            if c.shop_char and c.shop_char.id == shop_char.id:
                card = c
                break
        if not card:
            return

        card.start_download_ui()
        dest = get_writable_sprites_root()
        worker = DownloadWorker(shop_char, dest, parent=self)
        worker.progress.connect(card.update_progress)
        worker.finished.connect(lambda path, c=card, sc=shop_char: self._on_download_done(c, sc))
        worker.error.connect(lambda err, c=card: c.download_failed(err))
        self._active_workers.append(worker)
        worker.start()

    def _on_download_done(self, card: CharacterCard, shop_char: ShopCharacter):
        """Handle successful download: reload characters and update card."""
        reload_characters()
        self._populate_grid()
        # Re-select the previously selected character
        for c in self._char_cards:
            if c.char_name == self._selected_char:
                c.set_selected(True)
        log.info("Character '%s' downloaded and installed.", shop_char.name)

    def _on_delete_requested(self, name: str):
        """Confirm and delete a downloaded character."""
        reply = QMessageBox.question(
            self,
            t("ui.delete_confirm_title"),
            t("ui.delete_confirm_msg", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Find folder_id from CHARACTERS
        char_info = character_mod.CHARACTERS.get(name)
        if not char_info or char_info.get("source") != "downloaded":
            return
        folder_id = char_info.get("folder_id", "")
        if not folder_id:
            return

        dest = get_writable_sprites_root()
        if delete_character(folder_id, dest):
            reload_characters()
            # If we deleted the selected character, fallback
            if self._selected_char == name:
                names = get_character_names()
                self._selected_char = names[0] if names else "Forest Ranger 3"
            self._populate_grid()

    # ── models / save ───────────────────────────────────────────────

    @staticmethod
    def _mask_key(key: str) -> str:
        """Show first 6 and last 4 chars of an API key."""
        if len(key) <= 12:
            return "*" * len(key)
        return f"{key[:6]}...{key[-4:]}"

    def _groq_add_key(self):
        """Prompt for a new Groq API key and add it to the list."""
        key, ok = QInputDialog.getText(self, t("ui.dlg_add_groq_title"),
                                       t("ui.dlg_add_groq_label"))
        key = key.strip() if ok else ""
        if key:
            self._groq_api_keys.append(key)
            self._groq_keys_list.addItem(self._mask_key(key))

    def _groq_del_key(self):
        """Remove the selected Groq API key from the list."""
        row = self._groq_keys_list.currentRow()
        if row >= 0:
            self._groq_keys_list.takeItem(row)
            self._groq_api_keys.pop(row)

    def _on_provider_changed(self, provider: str):
        """Show/hide fields depending on the selected LLM provider."""
        self._ollama_group.setVisible(provider == "ollama")
        self._or_group.setVisible(provider == "openrouter")
        self._groq_group.setVisible(provider == "groq")

    def _refresh_models(self):
        """Fetch available models from the Ollama instance and populate the combo."""
        if self._provider_combo.currentText() != "ollama":
            return
        url = self._ollama_url.text().strip()
        current = self._config.get("ollama_model", "llama3")
        models = fetch_ollama_models(url)
        self._ollama_model.clear()
        if models:
            self._ollama_model.addItems(models)
            idx = self._ollama_model.findText(current)
            if idx >= 0:
                self._ollama_model.setCurrentIndex(idx)
            else:
                self._ollama_model.setCurrentText(current)
        else:
            self._ollama_model.setCurrentText(current)

    def _save(self):
        new_name = self._pet_name_edit.text().strip()
        if new_name:
            self._config["pet_name"] = new_name
        self._config["language"] = self._lang_combo.currentData()
        self._config["character"] = self._selected_char
        self._config["movement_speed"] = self._speed_spin.value()
        self._config["always_on_top"] = self._always_on_top.isChecked()
        self._config["window_interaction_enabled"] = self._win_enabled.isChecked()
        self._config["window_push_enabled"] = self._win_push.isChecked()
        self._config["gravity"] = self._gravity.isChecked()
        self._config["llm_enabled"] = self._llm_enabled.isChecked()
        self._config["llm_provider"] = self._provider_combo.currentText()
        self._config["ollama_url"] = self._ollama_url.text().strip()
        self._config["ollama_model"] = self._ollama_model.currentText().strip()
        self._config["openrouter_api_key"] = self._or_api_key.text().strip()
        self._config["openrouter_model"] = self._or_model.text().strip()
        self._config["groq_api_keys"] = list(self._groq_api_keys)
        self._config["groq_model"] = self._groq_model.text().strip()
        self._config["shop_url"] = self._shop_url.text().strip()
        self._config["debug_logging"] = self._debug_logging.isChecked()
        self._config["response_mode"] = self._response_mode.currentData()
        shortcut_val = self._listen_shortcut.shortcut_config_string()
        self._config["listen_shortcut"] = shortcut_val if shortcut_val else "ctrl+shift+space"
        self._config["assemblyai_api_key"] = self._aai_api_key.text().strip()
        self._config["assemblyai_model"] = self._aai_model.text().strip()
        self._config["elevenlabs_api_key"] = self._el_api_key.text().strip()
        self._config["elevenlabs_voice_id"] = self._el_voice_id.text().strip()
        self._config["elevenlabs_model"] = self._el_model.text().strip()
        idle_lo = self._idle_min.value()
        idle_hi = max(idle_lo, self._idle_max.value())
        self._config["idle_interval"] = [idle_lo, idle_hi]
        chat_lo = self._chat_min.value()
        chat_hi = max(chat_lo, self._chat_max.value())
        self._config["chat_interval"] = [chat_lo, chat_hi]
        winchk_lo = self._winchk_min.value()
        winchk_hi = max(winchk_lo, self._winchk_max.value())
        self._config["window_check_interval"] = [winchk_lo, winchk_hi]
        self._config["permissions"] = {
            key: self._perm_checks[key].isChecked()
            for key in self._perm_checks
        }
        save_config(self._config)
        self._pet_window._config = self._config
        self._pet_window.reload_config()
        self._cleanup_workers()
        self.accept()

    def reject(self):
        self._cleanup_workers()
        super().reject()

    def _cleanup_workers(self):
        """Stop and clean up any background workers."""
        for worker in self._active_workers:
            if worker.isRunning():
                worker.quit()
                worker.wait()
        self._active_workers.clear()
