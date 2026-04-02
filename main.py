import sys
import os
import logging

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def ensure_sprites():
    """Generate placeholder sprites if they don't exist."""
    sprites_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites", "placeholder")
    if not os.path.isdir(sprites_dir) or not any(f.endswith(".png") for f in os.listdir(sprites_dir)):
        print("Generating placeholder sprites...")
        from sprites.generate_placeholders import generate
        generate()


def main():
    # Configure logging — file + console
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jacky_debug.log")
    logging.basicConfig(
        level=logging.DEBUG,
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

    ensure_sprites()

    from core.pet_window import PetWindow
    pet = PetWindow()
    pet.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
