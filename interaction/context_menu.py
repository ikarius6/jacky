from PyQt6.QtWidgets import (QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QCheckBox, QSpinBox, QLineEdit, QPushButton,
                             QGroupBox, QFormLayout, QComboBox, QPlainTextEdit,
                             QTabWidget, QWidget, QGridLayout, QScrollArea,
                             QFrame, QSizePolicy, QListWidget, QInputDialog)
from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPixmap

import copy

from utils.config_manager import load_config, save_config
from utils.i18n import t, get_permission_defs, available_languages, current_language
from core.character import get_character_names, get_character_preview
from speech.llm_provider import fetch_ollama_models


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

        self._silent_action = QAction(t("ui.menu_silent"), self)
        self._silent_action.setCheckable(True)
        self._silent_action.setChecked(self._pet_window._config.get("silent_mode", False))
        self._silent_action.triggered.connect(self._toggle_silent_mode)
        self.addAction(self._silent_action)

        self.addSeparator()

        self._ask_action = QAction(t("ui.menu_ask"), self)
        self._ask_action.triggered.connect(self._open_ask_dialog)
        self._ask_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._ask_action)

        self._listen_action = QAction("Escuchar", self)
        self._listen_action.triggered.connect(self._pet_window.on_listen_toggle)
        self._listen_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._listen_action)

        self._look_action = QAction(t("ui.menu_look"), self)
        self._look_action.triggered.connect(self._pet_window.on_look)
        self._look_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._look_action)

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

    def _open_settings(self):
        dlg = SettingsDialog(self._pet_window)
        dlg.exec()

    def _toggle_silent_mode(self, checked: bool):
        """Toggle silent mode (in-memory only for this instance)."""
        self._pet_window._config["silent_mode"] = checked
        self._pet_window._silent_mode = checked

    def refresh_llm_state(self):
        """Update the Preguntar/Mirar actions enabled state after config reload."""
        self._ask_action.setEnabled(self._pet_window._llm_enabled)
        vision_allowed = self._pet_window._perm("allow_vision")
        self._look_action.setVisible(self._pet_window._llm_enabled and vision_allowed)
        self._silent_action.setChecked(self._pet_window._config.get("silent_mode", False))
        # Refresh all labels for current language
        self._pet_action.setText(t("ui.menu_pet", name=self._pet_name))
        self._feed_action.setText(t("ui.menu_feed"))
        self._attack_action.setText(t("ui.menu_attack"))
        self._peers_menu.setTitle(t("ui.menu_peers"))
        self._silent_action.setText(t("ui.menu_silent"))
        self._ask_action.setText(t("ui.menu_ask"))
        self._listen_action.setText("Escuchar")
        self._look_action.setText(t("ui.menu_look"))
        self._settings_action.setText(t("ui.menu_settings"))
        self._quit_action.setText(t("ui.menu_quit"))

    def show_at(self, pos: QPoint):
        self._rebuild_peers_menu()
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


class CharacterCard(QFrame):
    """Clickable card showing a character preview and name."""

    clicked = pyqtSignal(str)  # emits character name

    def __init__(self, char_name: str, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self._name = char_name
        self._selected = is_selected
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(PREVIEW_SIZE + 24, PREVIEW_SIZE + 44)
        self._build()
        self._apply_style()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Preview image
        self._img_label = QLabel()
        self._img_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        layout.addWidget(self._img_label)

        # Name label
        name_label = QLabel(self._name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 9pt; color: #5A3E2B;")
        layout.addWidget(name_label)

    def _apply_style(self):
        border = CARD_BORDER_SELECTED if self._selected else CARD_BORDER_NORMAL
        bg = "#FFF0DC" if self._selected else "#FFFFFF"
        self.setStyleSheet(f"""
            CharacterCard {{
                background-color: {bg};
                border: {border};
                border-radius: 8px;
            }}
            CharacterCard:hover {{
                background-color: #FFF0DC;
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def char_name(self) -> str:
        return self._name

    def mousePressEvent(self, event):
        self.clicked.emit(self._name)
        super().mousePressEvent(event)


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
        self._selected_char = self._config.get("character", "placeholder")
        self._char_cards: list[CharacterCard] = []
        self._perm_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_character_tab(), t("ui.tab_character"))
        tabs.addTab(self._build_settings_tab(), t("ui.tab_settings"))
        tabs.addTab(self._build_llm_tab(), t("ui.tab_llm"))
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
        """Build the visual character selection grid."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(4, 8, 4, 4)

        hint = QLabel(t("ui.select_character"))
        hint.setStyleSheet("font-size: 10pt; color: #5A3E2B; padding: 2px 4px;")
        tab_layout.addWidget(hint)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_widget)
        grid.setSpacing(10)
        grid.setContentsMargins(6, 6, 6, 6)

        names = get_character_names()
        cols = 3
        for i, name in enumerate(names):
            card = CharacterCard(name, is_selected=(name == self._selected_char))
            card.clicked.connect(self._on_card_clicked)
            grid.addWidget(card, i // cols, i % cols)
            self._char_cards.append(card)

        scroll.setWidget(grid_widget)
        tab_layout.addWidget(scroll)
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
        self._win_enabled = QCheckBox(t("ui.check_window_detect"))
        self._win_enabled.setChecked(self._config.get("window_interaction_enabled", True))
        win_form.addRow(self._win_enabled)
        self._win_push = QCheckBox(t("ui.check_window_push"))
        self._win_push.setChecked(self._config.get("window_push_enabled", True))
        win_form.addRow(self._win_push)
        win_group.setLayout(win_form)
        layout.addWidget(win_group)

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

        # Voice Settings
        voice_group = QGroupBox("Voice Settings (ElevenLabs & AssemblyAI)")
        voice_form = QFormLayout()
        
        self._response_mode = QComboBox()
        self._response_mode.addItems(["text", "voice", "both"])
        self._response_mode.setCurrentText(self._config.get("response_mode", "both"))
        voice_form.addRow("Response Mode:", self._response_mode)
        
        self._listen_shortcut = QLineEdit(self._config.get("listen_shortcut", "ctrl+shift+space"))
        voice_form.addRow("Listen Shortcut:", self._listen_shortcut)
        
        voice_group.setLayout(voice_form)
        layout.addWidget(voice_group)

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

    # ── character selection ──────────────────────────────────────────

    def _on_card_clicked(self, name: str):
        self._selected_char = name
        for card in self._char_cards:
            card.set_selected(card.char_name == name)

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
        self._config["window_interaction_enabled"] = self._win_enabled.isChecked()
        self._config["window_push_enabled"] = self._win_push.isChecked()
        self._config["llm_enabled"] = self._llm_enabled.isChecked()
        self._config["llm_provider"] = self._provider_combo.currentText()
        self._config["ollama_url"] = self._ollama_url.text().strip()
        self._config["ollama_model"] = self._ollama_model.currentText().strip()
        self._config["openrouter_api_key"] = self._or_api_key.text().strip()
        self._config["openrouter_model"] = self._or_model.text().strip()
        self._config["groq_api_keys"] = list(self._groq_api_keys)
        self._config["groq_model"] = self._groq_model.text().strip()
        self._config["debug_logging"] = self._debug_logging.isChecked()
        self._config["response_mode"] = self._response_mode.currentText()
        self._config["listen_shortcut"] = self._listen_shortcut.text().strip()
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
        self.accept()
