# Jacky — Desktop Virtual Pet

A Windows desktop pet application. Jacky is a cute chibi character who walks around your screen, interacts with windows, and talks to you.

## Features

- **Transparent frameless window** — only the pet sprite is visible
- **Autonomous walking** — Jacky walks along the screen bottom and window title bars
- **Click interactions** — left-click to pet, right-click for context menu, drag to reposition
- **Speech bubbles** — contextual dialogue with predefined lines
- **Window awareness** — detects open windows, reads titles, pushes windows, peeks from edges
- **LLM integration** — optional Ollama or OpenRouter support for dynamic dialogue
- **System tray** — quick access to settings and quit

## Setup

```bash
cd D:\Aplicaciones\jacky

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create your config from the example
copy config.json.example config.json

# Run
python main.py
```

## Configuration

Edit `config.json` or use the in-app Settings dialog (right-click Jacky → Ajustes).

> **Note:** `config.json` is git-ignored to prevent leaking API keys. Use `config.json.example` as template.

| Key | Description | Default |
|-----|-------------|--------|
| `movement_speed` | Walking speed (1-10) | 3 |
| `llm_enabled` | Enable LLM dialogue | false |
| `llm_provider` | `"ollama"` or `"openrouter"` | ollama |
| `ollama_url` | Ollama server URL | http://localhost:11434 |
| `ollama_model` | Ollama model name | llama3 |
| `openrouter_api_key` | OpenRouter API key | *(empty)* |
| `openrouter_model` | OpenRouter model identifier | qwen/qwen3.6-plus:free |
| `window_interaction_enabled` | Enable window awareness | true |
| `window_push_enabled` | Allow pushing windows | true |
| `bubble_timeout` | Speech bubble duration (seconds) | 5 |

### LLM Providers

- **Ollama** — Run a local model. Install [Ollama](https://ollama.com), pull a model, and set `ollama_url` / `ollama_model`.
- **OpenRouter** — Use cloud models (some are free). Get an API key at [openrouter.ai](https://openrouter.ai), set `llm_provider` to `"openrouter"`, and paste your key in `openrouter_api_key`.

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

# Then copy your config next to the exe (for user-writable settings):
Copy-Item config.json dist\Jacky\config.json
```

Run `dist\Jacky\Jacky.exe` to start Jacky.
