# Mac Compatibility — Platform Abstraction Layer

Introduce a `platform/` package that abstracts all OS-specific code behind a common interface, enabling full-feature-parity macOS support while keeping Windows behavior unchanged. Linux deferred.

---

## Audit Summary — Windows-Specific Code

### Files with direct Win32 / ctypes.windll usage

| File | Win32 surface area | Functions/features affected |
|---|---|---|
| `utils/win32_helpers.py` (545 lines) | `win32gui`, `win32con`, `win32api`, `win32process`, `ctypes.windll.user32`, `ctypes.windll.kernel32` | **Everything**: window enumeration, foreground detection, move/resize/minimize/tile windows, cursor control, click, Alt+F4, keyboard typing (SendInput), WinEvent hooks |
| `utils/dwm_helpers.py` (87 lines) | `ctypes.windll.dwmapi`, `ctypes.windll.user32` | `set_topmost()`, `remove_dwm_border()` — pet window z-order and border removal |
| `core/system_events.py` (194 lines) | `ctypes.windll.kernel32`, `ctypes.windll.user32` | Battery status (`GetSystemPowerStatus`), user idle time (`GetLastInputInfo`) |
| `interaction/hotkey.py` (170 lines) | `ctypes.windll.user32` | Global hotkey registration (`RegisterHotKey` / `GetMessageW` loop) |
| `interaction/window_awareness.py` (413 lines) | `import win32gui` (line 4), direct `win32gui.GetWindowRect` (line 353) | Window polling, drag tick, plus all functions imported from `win32_helpers` |
| `core/pet_window.py` (~1027 lines) | Imports `set_topmost`, `remove_dwm_border`, `set_window_click_through`, `capture_vision_area` | `_reassert_topmost()`, `_remove_dwm_border()`, `set_click_through()` |
| `core/movement.py` (217 lines) | Imports `get_work_area`, `get_taskbar_rect` | Fallback bounds when Qt bounds unavailable |
| `core/screen_interaction/handler.py` (879 lines) | Imports `click_at`, `send_alt_f4`, `minimize_foreground_window`, `type_text` | Screen interaction actions |
| `core/window_interactions.py` (314 lines) | Imports `WindowInfo`, `get_foreground_window` | Window interaction dispatcher |

### Cross-platform dependencies already in use
- **PyQt6** — fully cross-platform ✅
- **mss** — fully cross-platform ✅ (screen capture)
- **requests** — cross-platform ✅
- **assemblyai** — cross-platform ✅

### Windows-only dependencies
- **pywin32** (`win32gui`, `win32con`, `win32api`, `win32process`) — Windows only ❌
- **ctypes.windll** — Windows only ❌
- **webrtcvad** — problematic on Apple Silicon (conditional dep strategy chosen)

---

## Architecture: Platform Abstraction Layer (PAL)

### New package structure

```
platform/
├── __init__.py          # Factory: get_platform() → PlatformBackend
├── base.py              # Abstract base class defining the full interface
├── windows.py           # Windows implementation (wraps current win32_helpers + dwm_helpers)
└── macos.py             # macOS implementation (Cocoa/AppKit/Accessibility)
```

### `base.py` — Abstract interface (~25 methods, grouped)

```python
class PlatformBackend(ABC):
    """Abstract interface for all OS-specific operations."""

    # --- Screen / Desktop ---
    def get_screen_size() -> Tuple[int, int]
    def get_work_area() -> Tuple[int, int, int, int]
    def get_taskbar_rect() -> Tuple[int, int, int, int]

    # --- Window enumeration ---
    def get_visible_windows(exclude_pids) -> List[WindowInfo]
    def get_foreground_window() -> Optional[WindowInfo]

    # --- Window manipulation ---
    def move_window(wid, dx, dy) -> bool
    def set_window_pos(wid, x, y) -> bool
    def resize_window(wid, dw, dh) -> bool
    def minimize_window(wid) -> bool
    def flash_window(wid, count) -> bool
    def set_foreground_window(wid) -> bool
    def tile_windows(wids) -> bool
    def get_window_rect(wid) -> Tuple[int, int, int, int]

    # --- Pet window chrome ---
    def set_topmost(wid) -> None
    def remove_window_border(wid) -> None
    def set_click_through(wid, enabled) -> bool

    # --- Cursor / Input ---
    def get_cursor_position() -> Tuple[int, int]
    def set_cursor_position(x, y) -> bool
    def click_at(x, y, safety_check) -> bool
    def send_close_window() -> bool          # Alt+F4 / Cmd+W
    def minimize_foreground_window() -> bool
    def type_text(text, char_delay) -> bool

    # --- System events ---
    def get_power_status() -> Tuple[Optional[bool], Optional[int]]
    def get_idle_seconds() -> float

    # --- Global hotkey ---
    def register_hotkey(shortcut, callback) -> object  # returns handle
    def unregister_hotkey(handle) -> None

    # --- Window event hooks ---
    def register_window_event_hook(callback) -> None
    def unregister_all_hooks() -> None
```

> **Note**: `WindowInfo.hwnd` becomes `WindowInfo.wid` (window identifier) — an `int` on both platforms (HWND on Windows, CGWindowID/NSWindow number on Mac). The `WindowInfo` dataclass stays in `platform/base.py`.

### `__init__.py` — Factory

```python
import sys

def get_platform() -> PlatformBackend:
    if sys.platform == "win32":
        from .windows import WindowsBackend
        return WindowsBackend()
    elif sys.platform == "darwin":
        from .macos import MacOSBackend
        return MacOSBackend()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
```

A module-level singleton `_backend` is created on first import. Convenience re-exports for the most-used functions allow consumers to do:
```python
from platform import get_visible_windows, click_at, WindowInfo
```

---

## Implementation Plan — Phase by Phase

### Phase 1: Create the PAL and migrate Windows code (no behavior change)

1. **Create `platform/base.py`** — abstract base class + `WindowInfo` dataclass (move from `win32_helpers.py`)
2. **Create `platform/windows.py`** — move all function bodies from `utils/win32_helpers.py` and `utils/dwm_helpers.py` into a `WindowsBackend` class
3. **Create `platform/__init__.py`** — factory + convenience re-exports
4. **Update all 9 consumer files** to import from `platform/` instead of `utils/win32_helpers` / `utils/dwm_helpers`:
   - `interaction/window_awareness.py` — replace `import win32gui` and `from utils.win32_helpers import ...`
   - `interaction/hotkey.py` — replace all `ctypes.windll.user32` with platform backend methods
   - `core/pet_window.py` — replace `from utils.dwm_helpers import ...` and `from utils.win32_helpers import ...`
   - `core/movement.py` — replace `from utils.win32_helpers import get_work_area, get_taskbar_rect`
   - `core/window_interactions.py` — replace `from utils.win32_helpers import WindowInfo, get_foreground_window`
   - `core/screen_interaction/handler.py` — replace `from utils.win32_helpers import click_at, send_alt_f4, ...`
   - `core/system_events.py` — move battery/idle Win32 calls into platform backend
5. **Delete `utils/win32_helpers.py` and `utils/dwm_helpers.py`** (all code moved to `platform/windows.py`)
6. **Verify**: Run on Windows — behavior must be 100% identical

### Phase 2: Implement `platform/macos.py`

macOS APIs for each capability group:

#### Screen / Desktop
- `NSScreen.mainScreen().frame` for screen size
- `NSScreen.mainScreen().visibleFrame` for work area (excludes Dock & menu bar)
- Dock rect = difference between `frame` and `visibleFrame`

#### Window enumeration
- `CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)` — returns list of all visible windows with bounds, PID, title, layer
- Filter by `kCGWindowLayer == 0` (normal windows), exclude own PID
- For foreground: `NSWorkspace.sharedWorkspace().frontmostApplication()` → PID → match against window list

#### Window manipulation (requires Accessibility permission)
- **pyobjc** (`pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`)
- `AXUIElementCreateApplication(pid)` → `AXUIElementCopyAttributeValue` to get windows
- `AXUIElementSetAttributeValue(window, kAXPositionAttribute, ...)` — move
- `AXUIElementSetAttributeValue(window, kAXSizeAttribute, ...)` — resize
- `AXUIElementPerformAction(window, kAXMinimizeAction)` — minimize
- `AXUIElementPerformAction(window, kAXRaiseAction)` — bring to front
- Flash = `NSApplication.sharedApplication().requestUserAttention_(...)` (bounce Dock icon)
- Tile = compute grid + set position/size for each window

#### Accessibility permission check
- `AXIsProcessTrusted()` — returns bool
- Show permission prompt: `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})`
- If not trusted, disable window-manipulation features at runtime and show a user-friendly message

#### Pet window chrome
- **Topmost**: `NSWindow.setLevel_(NSFloatingWindowLevel)` — Qt already supports this via `Qt.WindowStaysOnTopHint`, but we may need native reinforcement via `winId()` → `NSView` → `window()` → `setLevel_`
- **Border removal**: macOS frameless windows via Qt flags (`Qt.FramelessWindowHint`) already work; no DWM equivalent needed. May need `NSWindow.setHasShadow_(False)` via pyobjc
- **Click-through**: `NSWindow.setIgnoresMouseEvents_(True/False)` via `winId()` → NSView → window()

#### Cursor / Input
- `CGEventCreateMouseEvent` + `CGEventPost` for cursor move + click
- `CGEventCreateKeyboardEvent` for key simulation
- Close window: simulate Cmd+W (`CGEventCreateKeyboardEvent` with kVK_ANSI_W + kCGEventFlagMaskCommand)
- Type text: `CGEventKeyboardSetUnicodeString` per character

#### System events
- Battery: `IOKit` via `IOPSCopyPowerSourcesInfo()` / `IOPSCopyPowerSourcesList()`, or simpler: `psutil.sensors_battery()` (cross-platform, already well-tested)
- Idle time: `CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType)`

#### Global hotkey
- `pyobjc` + `NSEvent.addGlobalMonitorForEventsMatchingMask_handler_()` — or use the `pynput` library's hotkey listener which works on both platforms
- Alternative: keep current approach but replace Win32 `RegisterHotKey` with Carbon `RegisterEventHotKey` via pyobjc

#### Window event hooks
- `NSWorkspace.sharedWorkspace().notificationCenter()` — observe `NSWorkspaceDidActivateApplicationNotification`, `NSWorkspaceDidLaunchApplicationNotification`, `NSWorkspaceDidTerminateApplicationNotification`
- For individual window-level events: poll-based (already the primary strategy on Windows too)

### Phase 3: Update dependencies

#### `requirements.txt` — platform-conditional

```
PyQt6>=6.6.0
requests>=2.31.0
mss>=9.0.0
assemblyai[extras]>=0.25.0

# Windows only
pywin32>=306; sys_platform == "win32"
webrtcvad>=2.0.10; sys_platform == "win32"

# macOS only
pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"
pyobjc-framework-Quartz>=10.0; sys_platform == "darwin"
pyobjc-framework-ApplicationServices>=10.0; sys_platform == "darwin"
# silero-vad intentionally omitted on macOS — requires torch (~448 MB);
# the graceful fallback in speech/voice.py connects immediately without VAD pre-gate.
```

### Phase 4: Platform-aware junk-window filtering

Update `_JUNK_PATTERNS` and `_JUNK_PROCESSES` in `window_awareness.py`:
- **Windows**: `.exe` suffix check, ApplicationFrameHost, Progman, WorkerW
- **Mac**: filter by `kCGWindowLayer != 0`, exclude Finder desktop, Dock, SystemUIServer, Spotlight, NotificationCenter

Move platform-specific junk definitions into each backend or into a `JUNK_PATTERNS` property on `PlatformBackend`.

### Phase 5: Peer discovery — cross-platform path

Current: `%TEMP%/jacky_peers.json` — works on Windows.
Fix: Use `tempfile.gettempdir()` which is already cross-platform (`/tmp/jacky_peers.json` on Mac). **Already correct** — `peer_discovery.py` line 14 uses `tempfile.gettempdir()`. ✅ No change needed.

Peer `hwnd` field → rename to `wid` to be platform-neutral (or keep as legacy name with platform-specific semantics).

### Phase 6: Mac packaging

Create `jacky_mac.spec` for PyInstaller:
- Target: `.app` bundle via `--windowed` + `--osx-bundle-identifier com.jacky.pet`
- Include `Info.plist` with:
  - `NSAccessibilityUsageDescription` (for Accessibility permission prompt)
  - `NSMicrophoneUsageDescription` (for STT/voice input)
- Remove `win32*` from `hiddenimports`, add pyobjc frameworks
- Sign with ad-hoc signature for local use, or guide for Developer ID signing

Alternative: Add a second target block in `jacky.spec` gated on `sys.platform`.

### Phase 7: VAD on macOS — no-op (connect-immediately fallback)

`webrtcvad` has poor Apple Silicon support; `silero-vad` requires `torch` which adds
~448 MB to the `.app` bundle — unacceptable.

**Decision**: skip VAD pre-gating entirely on macOS. `speech/voice.py` already handles
this gracefully:

```python
# voice.py — existing fallback path (no changes needed)
if _vad_obj is None:
    # Neither webrtcvad nor silero available
    log.debug("No VAD available; connecting immediately (no pre-gate)")
    # WS opened right away; billing starts at connection, not at speech
```

The user experience difference is negligible for short push-to-talk sessions:
AssemblyAI's server-side VAD still filters silence server-side, so transcripts are
unaffected. Only the "open WS on first speech" optimisation is lost.

---

## Files Changed (Summary)

### New files
| File | Purpose |
|---|---|
| `platform/__init__.py` | Factory + re-exports |
| `platform/base.py` | Abstract interface + `WindowInfo` dataclass |
| `platform/windows.py` | Windows backend (migrated from `win32_helpers` + `dwm_helpers`) |
| `platform/macos.py` | macOS backend (pyobjc + Quartz + Accessibility) |
| `jacky_mac.spec` | PyInstaller spec for macOS `.app` bundle |

### Modified files
| File | Change |
|---|---|
| `interaction/window_awareness.py` | Replace `win32gui` + `win32_helpers` imports → `platform` |
| `interaction/hotkey.py` | Replace ctypes Win32 hotkey → platform backend |
| `core/pet_window.py` | Replace `dwm_helpers` + `win32_helpers` → `platform` |
| `core/movement.py` | Replace `win32_helpers` → `platform` |
| `core/window_interactions.py` | Replace `win32_helpers` → `platform` |
| `core/screen_interaction/handler.py` | Replace `win32_helpers` → `platform` |
| `core/system_events.py` | Move Win32 battery/idle calls → `platform` |
| `speech/voice.py` | Conditional VAD: `webrtcvad` (Win) vs `silero-vad` (Mac) |
| `requirements.txt` | Platform-conditional dependencies |
| `jacky.spec` | Guard `hiddenimports` with `sys.platform` check |

### Deleted files
| File | Reason |
|---|---|
| `utils/win32_helpers.py` | All code moved to `platform/windows.py` |
| `utils/dwm_helpers.py` | All code moved to `platform/windows.py` |

---

## Acceptance Criteria

1. **Windows**: All existing behavior unchanged — no regressions
2. **Mac**: Pet renders, walks, interacts with windows (with Accessibility permission), screen interaction works, global hotkey works, battery/idle detection works, STT works with silero-vad
3. **Mac without Accessibility**: Pet still renders/walks/talks; window manipulation features show a "grant Accessibility permission" message instead of silently failing
4. **Import safety**: `import platform` on Mac never imports `win32gui`; on Windows never imports `pyobjc`
5. **Packaging**: `jacky_mac.spec` produces a working `.app` bundle
6. **No `platform` name collision**: Python has a built-in `platform` module — our package must use a different name (e.g., `platform_layer/`, `pal/`, or `backends/`). **Decision needed: use `pal/`** to avoid collision.

---

## Estimated effort

| Phase | Work |
|---|---|
| Phase 1: PAL + migrate Windows | ~4–6 hours |
| Phase 2: macOS backend | ~8–12 hours |
| Phase 3: Dependencies | ~30 min |
| Phase 4: Junk filtering | ~1 hour |
| Phase 5: Peer discovery | ~30 min (already cross-platform) |
| Phase 6: Mac packaging | ~2–3 hours |
| Phase 7: VAD conditional | ~1–2 hours |
| **Total** | **~17–25 hours** |

---

## Constraints & Risks

- **`platform` name collision**: Python stdlib has `platform`. We **must** name our package differently → `pal/` (Platform Abstraction Layer)
- **Accessibility permission UX**: First Mac launch will need a clear dialog explaining why Accessibility access is needed
- **pyobjc bundle size**: pyobjc frameworks add ~20–40MB to the app bundle
- **Testing**: Need a real Mac to test — cannot be fully verified in CI without macOS runners
- **AXUIElement reliability**: Some window manipulation may fail for certain apps (e.g., Electron apps sometimes don't expose full AX attributes)
