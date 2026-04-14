import sys
import os
import logging

# Ensure the project root is on the path
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from utils.paths import get_data_dir, get_config_dir

def main():
    # Configure logging — file + console
    from utils.config_manager import load_config
    cfg = load_config()
    log_level = logging.DEBUG if cfg.get("debug_logging", False) else logging.WARNING
    log_path = os.path.join(get_config_dir(), "jacky_debug.log")
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger().info("=== Jacky debug session started ===")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running via system tray

    from core.pet_window import PetWindow
    pet = PetWindow()
    pet.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
