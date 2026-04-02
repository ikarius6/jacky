from PyQt6.QtWidgets import QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QLineEdit, QPushButton, QGroupBox, QFormLayout, QComboBox, QPlainTextEdit
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QAction, QFont

from utils.config_manager import load_config, save_config
from core.character import get_character_names


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


class SettingsDialog(QDialog):
    """Settings dialog for configuring Jacky."""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet_window = pet_window
        self.setWindowTitle("Ajustes de Jacky")
        self.setFixedWidth(380)
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
        """)
        self._config = load_config()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Character group
        char_group = QGroupBox("Personaje")
        char_form = QFormLayout()
        self._char_combo = QComboBox()
        self._char_combo.addItems(get_character_names())
        current_char = self._config.get("character", "placeholder")
        idx = self._char_combo.findText(current_char)
        if idx >= 0:
            self._char_combo.setCurrentIndex(idx)
        char_form.addRow("Pack de sprites:", self._char_combo)
        char_group.setLayout(char_form)
        layout.addWidget(char_group)

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
        self._ollama_model = QLineEdit(self._config.get("ollama_model", "llama3"))
        llm_form.addRow("Modelo:", self._ollama_model)
        llm_group.setLayout(llm_form)
        layout.addWidget(llm_group)

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

    def _save(self):
        self._config["character"] = self._char_combo.currentText()
        self._config["movement_speed"] = self._speed_spin.value()
        self._config["window_interaction_enabled"] = self._win_enabled.isChecked()
        self._config["window_push_enabled"] = self._win_push.isChecked()
        self._config["llm_enabled"] = self._llm_enabled.isChecked()
        self._config["ollama_url"] = self._ollama_url.text().strip()
        self._config["ollama_model"] = self._ollama_model.text().strip()
        save_config(self._config)
        self._pet_window.reload_config()
        self.accept()
