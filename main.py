import sys
import os
import logging

# Suppress Qt Multimedia / FFmpeg stderr noise (codec probing, etc.)
os.environ["QT_LOGGING_RULES"] = (
    "qt.multimedia.ffmpeg*=false;"
    "qt.multimedia*=false"
)

def _silence_c_stderr() -> None:
    """Redirect fd 2 to /dev/null before Qt/FFmpeg load.
    FFmpeg writes codec-probing lines ([mp3 @ ...], 'Input #0...') directly
    to C-level stderr, bypassing Python's logging entirely."""
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
    except OSError:
        pass

_silence_c_stderr()

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
