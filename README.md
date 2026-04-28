# Jacky — Desktop Virtual Pet

A desktop pet application for **Windows** and **macOS**. Jacky is a cute chibi character who walks around your screen, interacts with windows, interacts with other Jackys, listens to your voice, talks back to you, can *see* your screen, follows instructions (click, type, close, minimize windows), sets timers, reminders, and alarms, and reacts to system events like battery changes.

## Try it now!

[⬇ Download](https://github.com/ikarius6/jacky/releases/latest)

## [Demo](https://github.com/ikarius6/jacky/demo.mp4)

https://github.com/user-attachments/assets/e34f4733-f044-4b01-8944-50e9c8e887cf

## Screenshots

![Jacky](screens/1.jpg)
![Skins](screens/2.jpg)
![Vision](screens/3.jpg)
![Multiple Jackys](screens/4.gif)

## Features

- **Transparent frameless window** — only the pet sprite is visible
- **Autonomous walking** — Jacky walks along the screen bottom and window title bars
- **Gravity** — optional physics mode where Jacky walks on the ground and window-top platforms, falls when dropped in mid-air, and lands realistically
- **Click interactions** — left-click to pet, right-click for context menu, drag to reposition
- **Voice interaction (STT & TTS)** — press a hotkey to speak to Jacky, and hear spoken responses
- **Screen interaction** — tell Jacky to **click**, **type text**, **close**, **minimize**, or **navigate to** any element on screen; uses a two-phase grid-based vision pipeline with LLM to locate targets accurately
- **Speech bubbles** — contextual dialogue with predefined lines
- **Window awareness** — detects open windows, reads titles, pushes windows, peeks from edges
- **Vision** — Jacky can capture and analyze what's on your screen using multimodal LLM models (DPI-aware, multi-monitor)
- **Timers, reminders & alarms** — set countdown timers, time-based reminders, and daily-repeating alarms via the context menu or voice; entries persist across restarts
- **Routines** — let your pet fetch data from APIs, parse responses, and speak or notify you based on custom logic via JSON files
- **System events** — Jacky reacts to battery level changes (low, critical, charging, full), power cable plug/unplug, and welcomes you back after idle periods
- **LLM integration** — three provider options: **Ollama** (local), **Groq** (cloud, with key rotation), and **OpenRouter** (cloud)
- **Multi-instance / Peer interactions** — run multiple Jackys that discover each other and interact (greet, attack, chase, dance, fight)
- **Multilanguage (i18n)** — ships with Spanish and English; add a new language by dropping a single JSON file in `locales/`
- **Granular permissions** — toggle individual behaviours (comment, peek, sit, push, shake, minimize, resize, knock, drag, tidy, topple, vision, screen interaction)
- **Operation Modes** — switch between Silent, Gamer, and Music modes to adapt to your current activity
- **System tray** — quick access to settings and quit
- **Easter eggs** — 10+ hidden secrets to discover

## Setup

### Windows

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy config.json.example config.json
python main.py
```

### macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.json.example config.json
python main.py
```

> **macOS permissions:** Jacky requires the following permissions on macOS:
>
> | Permission | Where to grant | What it enables |
> |---|---|---|
> | **Accessibility** | System Settings → Privacy & Security → Accessibility | Window manipulation (move, resize, peek, minimize). Jacky still runs without it — only these features are disabled. |
> | **Input Monitoring** | System Settings → Privacy & Security → Input Monitoring | Global hotkey (push-to-talk). Without this, the voice hotkey will not respond while another app is in focus. |
> | **Microphone** | System Settings → Privacy & Security → Microphone | Voice input (STT). Required to record your voice when the hotkey is pressed. |
> | **Screen Recording** | System Settings → Privacy & Security → Screen Recording | Vision and screen interaction. Required to capture screenshots for LLM analysis and on-screen element targeting. |
>
> Jacky prompts for Accessibility, Microphone, and Screen Recording automatically when each feature is first used. **Input Monitoring must be granted manually** — macOS will not prompt for it automatically.

## Troubleshooting

### macOS — `pyaudio` build fails (`portaudio.h` file not found)

`pyaudio` requires the **portaudio** C library to be present on your system before pip can build it. On macOS this library is not installed by default, so `pip install -r requirements.txt` will fail with:

```
fatal error: 'portaudio.h' file not found
error: command '/usr/bin/clang' failed with exit code 1
ERROR: Failed building wheel for pyaudio
```

**Fix:** Install portaudio via Homebrew first, then re-run pip pointing to the Homebrew paths:

```bash
brew install portaudio
CPATH=$(brew --prefix portaudio)/include \
LIBRARY_PATH=$(brew --prefix portaudio)/lib \
pip install pyaudio
```

After that, any remaining packages in `requirements.txt` can be installed normally:

```bash
pip install -r requirements.txt
```

### macOS — Global hotkey not working (Input Monitoring)

If the voice hotkey (`Ctrl+Shift+Space` by default / `Shift+G` etc.) does nothing when another app is in focus, and the log shows:

```
ERROR: CGEventTapCreate failed
ERROR: CGEventTap thread failed to initialise
ERROR: Failed to register global hotkey: ...
```

This is a **macOS Input Monitoring** permission issue. Even if the toggle appears ON in System Settings, the macOS TCC permission database sometimes caches the old "denied" state.

**Fix — toggle the permission off and back on:**

1. Open **System Settings → Privacy & Security → Input Monitoring**
2. Toggle **Jacky** (and **python** if listed) **OFF**
3. Wait 2 seconds
4. Toggle them back **ON**
5. **Fully quit Jacky** (right-click Dock icon → Quit, or Cmd+Q)
6. Relaunch Jacky

> **Why this happens:** macOS caches TCC permission decisions per process. Granting the permission while the app is running does not update the cached state for that process. Removing and re-adding the entry forces a fresh grant, which the next launch picks up correctly.

## Configuration

Edit `config.json` or use the in-app Settings dialog (right-click Jacky → Settings / Ajustes).

> **Note:** Use `config.json.example` as template.

| Key | Description | Default |
|-----|-------------|---------|
| `language` | UI and dialogue language (`"es"`, `"en"`, …) | `"es"` |
| `movement_speed` | Walking speed (1–10) | `6` |
| `llm_enabled` | Enable LLM dialogue | `false` |
| `llm_provider` | `"ollama"`, `"groq"`, or `"openrouter"` | `"ollama"` |
| `ollama_url` | Ollama server URL | `http://localhost:11434` |
| `ollama_model` | Ollama model name | `llama3.2:latest` |
| `groq_api_keys` | List of Groq API keys (rotation) | `[]` |
| `groq_model` | Groq model identifier | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `openrouter_api_key` | OpenRouter API key | *(empty)* |
| `openrouter_model` | OpenRouter model identifier | `google/gemma-4-26b-a4b-it:free` |
| `gravity` | Enable gravity mode (walk on ground/platforms, fall) | `false` |
| `window_interaction_enabled` | Enable window awareness | `true` |
| `window_push_enabled` | Allow pushing windows | `true` |
| `bubble_timeout` | Speech bubble duration (seconds) | `5` |
| `peer_interaction_enabled` | Enable multi-instance discovery | `true` |
| `max_peer_instances` | Max simultaneous Jacky instances (1–20) | `5` |
| `peer_check_interval` | Peer poll interval `[min, max]` seconds | `[8, 20]` |
| `permissions` | Object toggling individual behaviours | *(all true)* |

### LLM Providers

- **Ollama** — Run a local model. Install [Ollama](https://ollama.com), pull a model, and set `ollama_url` / `ollama_model`. Supports vision when using a multimodal model.
- **Groq** — Fast cloud inference. Get API keys at [console.groq.com](https://console.groq.com). Supply one or more keys in `groq_api_keys`; Jacky rotates through them automatically and handles rate-limit cooldowns (round-robin with per-key 60 s cooldown).
- **OpenRouter** — Access hundreds of models (some free). Get an API key at [openrouter.ai](https://openrouter.ai), set `llm_provider` to `"openrouter"`, and paste your key in `openrouter_api_key`.

All three providers support **vision** (multimodal image input) with automatic text-only fallback if the selected model doesn't support it.

### Vision

When LLM is enabled, Jacky can "look" at your screen:
- Triggered automatically by keywords in conversation (e.g. "qué ves", "what do you see")
- Triggered manually via the context menu
- Captures a 1024×1024 area around the pet, DPI-aware and multi-monitor safe
- The screenshot is sent to the LLM as a base64 image for analysis

### Screen Interaction

When instructed, Jacky can take action on your screen! Tell Jacky to _"click on the start button"_, or _"close the browser window"_. Jacky will intelligently partition the screen, use vision to identify the target, and perform actual mouse clicks.

Supported actions: **navigate** (walk to), **click**, **write** (type text), **close** (Alt+F4), and **minimize**.

The full pipeline involves intent detection (keyword matching + LLM fallback), a two-phase grid-based locate system with dynamic crop sizing, coordinate mapping across DPI-aware coordinate spaces, and optional LLM-based position refinement.

📖 **[Screen Interaction — Technical Deep Dive](docs/screen_interaction.md)** — full architecture, coordinate pipeline, debug mode, and configuration reference.

### Voice Interaction (STT & TTS)

Jacky can listen to your voice and talk back!
- Enable voice transcription via AssemblyAI. Press `Ctrl+Alt+Space` to toggle voice recording.
- Enable voice synthesis via ElevenLabs. Jacky's responses will be spoken aloud!
- Configure API keys, models, and voices directly in the Settings dialog (Voice tab).

### Timers, Reminders & Alarms

Jacky can manage countdown timers, time-based reminders, and alarms:
- **Timers** — set a countdown (e.g. "5 minutes") with optional label; quick presets available
- **Reminders** — fire at a specific date and time with a custom message
- **Alarms** — fire at a time of day, optionally repeating daily

Create and manage entries from the context menu (Timers dialog) or by voice. All entries persist to `timers.json` and are restored on startup — missed entries that expired within 10 minutes are fired immediately, and daily alarms auto-reschedule.

### Routines

Jacky can run custom routines defined as JSON files in the `routines/` directory without writing any code. Routines can be triggered manually (via context menu or keywords) or automatically on a repeating timer.

With Routines, Jacky can:
- **Fetch Data** — Make HTTP requests to external APIs.
- **Parse Responses** — Extract data using JSON paths, XML tags, or Regex.
- **Evaluate Logic** — Follow IF/THEN branching logic based on the extracted variable values.
- **Take Action** — Emit system tray notifications, silent logs, or have Jacky use the LLM to speak about the results.

📖 **[Routines — JSON API deep dive & examples](docs/routines.md)**

### Gravity

Toggle gravity mode in Settings. When enabled:
- Jacky walks on the **screen bottom** and on top of **window title bars** as platforms
- When dragged and dropped in mid-air, Jacky **falls** with a falling animation until landing
- Without gravity, Jacky roams freely across all screen areas

### System Events

Jacky monitors system-level events and reacts with contextual dialogue (or LLM-generated responses when enabled):
- **Battery low / critical** — warns you when battery drops below 20% or 10%
- **Charging / discharging** — notices when the power cable is plugged in or unplugged
- **Battery full** — celebrates when the battery reaches 100%
- **User returned** — welcomes you back after 5+ minutes of inactivity

### Operation Modes

Jacky can adapt to your current activity using different operation modes:
- **Silent Mode** — Mutes all TTS voice output and sound effects. Speech bubbles will still appear, but Jacky will be completely quiet.
- **Gamer Mode** — Puts Jacky in the background (behind other windows), disables window pushing, suspends background routines, and mutes him so he doesn't interfere with your gameplay.
- **Music Mode** — Detects when you are listening to media (Spotify, Apple Music, YouTube) and reacts to the music with dance animations and track comments.

### Multi-instance & Peer Interactions

Run several Jacky instances simultaneously. They discover each other via a shared temp file (`jacky_peers.json` in the system temp directory) and can interact:
- **Greet** — wave and say hello
- **Attack / Fight** — animated battle sequences
- **Chase** — one Jacky chases another
- **Dance** — synchronised dance

Peers appear in a dynamic "Companions" submenu in the context menu.

### Multilanguage (i18n)

Jacky ships with **Spanish** (default) and **English**. The language can be changed live from Settings without restarting.

To add a new language, create a `locales/<code>.json` file following the structure of `locales/es.json`. It will be auto-discovered on next launch.

Translated content includes: dialogues, app-group keywords, UI labels, permission descriptions, vision keywords, and the LLM system prompt.

## Custom Sprites

Drop sprite folders inside `sprites/`. Each folder contains a `character.json` descriptor and sub-folders for each animation state (Idle, Walking, Dying, Hurt, etc.). Sprites should have transparent backgrounds.

### Animation States
📖 **[Animation States — Technical Deep Dive](docs/animation_states.md)** — full reference for PetState enum, sprite folder mapping, and animation fallback system.

## Compile

### Windows

```powershell
.\venv\Scripts\pyinstaller.exe jacky.spec --noconfirm

# Copy your config next to the exe:
Copy-Item config.json dist\Jacky\config.json
```

Run `dist\Jacky\Jacky.exe` to launch.

### macOS

```bash
python -m PyInstaller jacky_mac.spec --noconfirm

# Copy your config into the app bundle:
cp config.json dist/Jacky.app/Contents/MacOS/config.json
```

Run `dist/Jacky.app` to launch (double-click or `open dist/Jacky.app`).

> **macOS notes:**
> - The `.app` bundle is ad-hoc signed. For distribution, sign with a Developer ID certificate.
> - If macOS blocks the app ("unidentified developer"), right-click → Open, or allow it in System Settings → Privacy & Security.
