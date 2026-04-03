from PyQt6.QtWidgets import (QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QCheckBox, QSpinBox, QLineEdit, QPushButton,
                             QGroupBox, QFormLayout, QComboBox, QPlainTextEdit,
                             QTabWidget, QWidget, QGridLayout, QScrollArea,
                             QFrame, QSizePolicy)
from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPixmap

from utils.config_manager import load_config, save_config
from core.character import get_character_names, get_character_preview
from speech.llm_provider import fetch_ollama_models


class PetContextMenu(QMenu):
    """Right-click context menu for interacting with Jacky."""

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
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
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

    def _build_menu(self):
        pet_action = QAction("🤗 Acariciar a Jacky", self)
        pet_action.triggered.connect(self._pet_window.on_pet_clicked)
        self.addAction(pet_action)

        feed_action = QAction("🍔 Alimentar", self)
        feed_action.triggered.connect(self._pet_window.on_feed)
        self.addAction(feed_action)

        attack_action = QAction("⚔️ Atacar", self)
        attack_action.triggered.connect(self._pet_window.on_attack)
        self.addAction(attack_action)

        self.addSeparator()

        self._ask_action = QAction("💬 Preguntar", self)
        self._ask_action.triggered.connect(self._open_ask_dialog)
        self._ask_action.setEnabled(self._pet_window._llm_enabled)
        self.addAction(self._ask_action)

        self.addSeparator()

        settings_action = QAction("⚙️ Ajustes", self)
        settings_action.triggered.connect(self._open_settings)
        self.addAction(settings_action)

        self.addSeparator()

        quit_action = QAction("👋 Salir", self)
        quit_action.triggered.connect(self._pet_window.on_quit)
        self.addAction(quit_action)

    def _open_ask_dialog(self):
        dlg = AskDialog(self._pet_window)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            question = dlg.get_text().strip()
            if question:
                self._pet_window.on_ask(question)

    def _open_settings(self):
        dlg = SettingsDialog(self._pet_window)
        dlg.exec()

    def refresh_llm_state(self):
        """Update the Preguntar action enabled state after config reload."""
        self._ask_action.setEnabled(self._pet_window._llm_enabled)

    def show_at(self, pos: QPoint):
        self.popup(pos)


class AskDialog(QDialog):
    """Small dialog with a text field to ask Jacky a question via LLM."""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        self.setWindowTitle("Preguntarle a Jacky")
        self.setFixedWidth(360)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF8F0;
                font-family: 'Segoe UI';
            }
            QPlainTextEdit {
                border: 1px solid #DDB892;
                border-radius: 6px;
                padding: 6px;
                font-size: 11pt;
                background-color: #FFFFFF;
            }
            QPushButton {
                background-color: #FFDDB5;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FFD0A0;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        label = QLabel("Escribe tu pregunta:")
        label.setStyleSheet("font-size: 11pt; color: #5A3E2B;")
        layout.addWidget(label)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("Ej: ¿Qué opinas de mi escritorio?")
        self._text_edit.setFixedHeight(80)
        layout.addWidget(self._text_edit)

        btn_layout = QHBoxLayout()
        send_btn = QPushButton("Enviar")
        send_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancelar")
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


class SettingsDialog(QDialog):
    """Settings dialog for configuring Jacky."""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        self.setWindowTitle("Ajustes de Jacky")
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF8F0;
                font-family: 'Segoe UI';
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #DDB892;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 6px;
            }
            QPushButton {
                background-color: #FFDDB5;
                border: 1px solid #DDB892;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
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
        """)
        self._config = load_config()
        self._selected_char = self._config.get("character", "placeholder")
        self._char_cards: list[CharacterCard] = []
        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_character_tab(), "Personaje")
        tabs.addTab(self._build_settings_tab(), "Ajustes")
        layout.addWidget(tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancelar")
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

        hint = QLabel("Selecciona un personaje:")
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

        # Movement group
        move_group = QGroupBox("Movimiento")
        move_form = QFormLayout()
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(1, 10)
        self._speed_spin.setValue(self._config.get("movement_speed", 3))
        move_form.addRow("Velocidad:", self._speed_spin)
        move_group.setLayout(move_form)
        layout.addWidget(move_group)

        # Window interaction group
        win_group = QGroupBox("Interacción con ventanas")
        win_form = QFormLayout()
        self._win_enabled = QCheckBox("Activar detección de ventanas")
        self._win_enabled.setChecked(self._config.get("window_interaction_enabled", True))
        win_form.addRow(self._win_enabled)
        self._win_push = QCheckBox("Permitir empujar ventanas")
        self._win_push.setChecked(self._config.get("window_push_enabled", True))
        win_form.addRow(self._win_push)
        win_group.setLayout(win_form)
        layout.addWidget(win_group)

        # LLM group
        llm_group = QGroupBox("Ollama LLM")
        llm_form = QFormLayout()
        self._llm_enabled = QCheckBox("Activar diálogo LLM")
        self._llm_enabled.setChecked(self._config.get("llm_enabled", False))
        llm_form.addRow(self._llm_enabled)
        self._ollama_url = QLineEdit(self._config.get("ollama_url", "http://localhost:11434"))
        llm_form.addRow("URL:", self._ollama_url)
        model_layout = QHBoxLayout()
        self._ollama_model = QComboBox()
        self._ollama_model.setEditable(True)
        self._refresh_models_btn = QPushButton("🔄")
        self._refresh_models_btn.setFixedWidth(50)
        self._refresh_models_btn.setToolTip("Actualizar lista de modelos")
        self._refresh_models_btn.clicked.connect(self._refresh_models)
        model_layout.addWidget(self._ollama_model)
        model_layout.addWidget(self._refresh_models_btn)
        llm_form.addRow("Modelo:", model_layout)
        self._refresh_models()
        llm_group.setLayout(llm_form)
        layout.addWidget(llm_group)

        # Debug group
        debug_group = QGroupBox("Depuración")
        debug_form = QFormLayout()
        self._debug_logging = QCheckBox("Activar logging de depuración")
        self._debug_logging.setChecked(self._config.get("debug_logging", False))
        debug_form.addRow(self._debug_logging)
        debug_group.setLayout(debug_form)
        layout.addWidget(debug_group)

        layout.addStretch()
        return tab

    # ── character selection ──────────────────────────────────────────

    def _on_card_clicked(self, name: str):
        self._selected_char = name
        for card in self._char_cards:
            card.set_selected(card.char_name == name)

    # ── models / save ───────────────────────────────────────────────

    def _refresh_models(self):
        """Fetch available models from the Ollama instance and populate the combo."""
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
        self._config["character"] = self._selected_char
        self._config["movement_speed"] = self._speed_spin.value()
        self._config["window_interaction_enabled"] = self._win_enabled.isChecked()
        self._config["window_push_enabled"] = self._win_push.isChecked()
        self._config["llm_enabled"] = self._llm_enabled.isChecked()
        self._config["ollama_url"] = self._ollama_url.text().strip()
        self._config["ollama_model"] = self._ollama_model.currentText().strip()
        self._config["debug_logging"] = self._debug_logging.isChecked()
        save_config(self._config)
        self._pet_window.reload_config()
        self.accept()
