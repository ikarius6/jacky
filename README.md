# Jacky — Desktop Virtual Pet

A Windows desktop pet application. Jacky is a cute chibi character who walks around your screen, interacts with windows, and talks to you.

## Features

- **Transparent frameless window** — only the pet sprite is visible
- **Autonomous walking** — Jacky walks along the screen bottom and window title bars
- **Click interactions** — left-click to pet, right-click for context menu, drag to reposition
- **Speech bubbles** — contextual dialogue with predefined lines
- **Window awareness** — detects open windows, reads titles, pushes windows, peeks from edges
- **LLM integration** — optional Ollama support for dynamic dialogue
- **System tray** — quick access to settings and quit

## Setup

```bash
cd D:\Aplicaciones\jacky

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

## Configuration

Edit `config.json` or use the in-app Settings dialog (right-click Jacky → Settings).

| Key | Description | Default |
|-----|-------------|---------|
| `movement_speed` | Walking speed (1-10) | 3 |
| `llm_enabled` | Enable Ollama LLM dialogue | false |
| `ollama_url` | Ollama server URL | http://localhost:11434 |
| `ollama_model` | Ollama model name | llama3 |
| `window_interaction_enabled` | Enable window awareness | true |
| `window_push_enabled` | Allow pushing windows | true |
| `bubble_timeout` | Speech bubble duration (seconds) | 5 |

## Custom Sprites

Replace PNGs in `sprites/placeholder/` with your own. Follow the naming convention:
- `idle_0.png` ... `idle_3.png`
- `walk_right_0.png` ... `walk_right_3.png`
- `walk_left_0.png` ... `walk_left_3.png`
- `talk_0.png`, `talk_1.png`
- `happy_0.png`, `happy_1.png`
- `drag_0.png`

Sprites should be 128×128 px with transparent backgrounds.

# Compile

```powershell
# From project root:
.\venv\Scripts\pyinstaller.exe jacky.spec --noconfirm

# Then copy config.json next to the exe (for user-writable settings):
Copy-Item config.json dist\Jacky\config.json
```

Run `dist\Jacky\Jacky.exe` to start Jacky.
