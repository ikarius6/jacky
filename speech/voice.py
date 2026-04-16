import os
import sys
import time
import logging
import tempfile
import threading
import hashlib
import json
from collections import deque
from typing import Callable, Optional

import requests
import assemblyai as aai
from PyQt6.QtCore import QUrl, QObject, pyqtSignal, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

log = logging.getLogger("speech.voice")


def _is_valid_mp3(filepath: str) -> bool:
    """Quick check: file exists, non-zero size, and ends with MP3 sync pattern."""
    if not os.path.isfile(filepath):
        return False
    size = os.path.getsize(filepath)
    if size < 128:  # MP3 frame header is 4 bytes + ID3v1 tag is 128 bytes
        return False
    # Check for ID3 header or any MP3 frame sync (0xFF 0xFB)
    try:
        with open(filepath, "rb") as f:
            header = f.read(4)
            if header[:2] == b"ID":
                return True  # ID3v2 tag
            if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
                return True  # MP3 frame sync
        return True  # If we can read it, assume it's OK — FFmpeg will validate further
    except Exception:
        return False

class ElevenLabsTTSClient(QObject):
    """Client for ElevenLabs Text-to-Speech API.
    Downloads the audio stream and plays it using QMediaPlayer."""

    # Signal to notify when playback finishes (or errors)
    playback_finished = pyqtSignal()
    # Internal signal to safely transition from worker thread to main thread
    _playback_ready = pyqtSignal(str)

    def __init__(self, api_key: str, voice_id: str = "U0W3edavfdI8ibPeeteQ", model_id: str = "eleven_flash_v2_5", allow_cache_func: Optional[Callable[[], bool]] = None):
        super().__init__()
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._allow_cache_func = allow_cache_func
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._playback_ready.connect(self._start_playback)
        self._current_temp_file: Optional[str] = None
        
        self._cache_dir = os.path.join(tempfile.gettempdir(), "jacky_tts_cache")
        self._usage_file = os.path.join(self._cache_dir, "usage.json")
        self._usage_lock = threading.Lock()

    def _update_usage_record(self, filename: str):
        with self._usage_lock:
            try:
                usage = {}
                if os.path.exists(self._usage_file):
                    with open(self._usage_file, 'r', encoding='utf-8') as f:
                        usage = json.load(f)
            except Exception:
                usage = {}
                
            if filename not in usage:
                usage[filename] = {"count": 0, "last_accessed": time.time()}
                
            usage[filename]["count"] += 1
            usage[filename]["last_accessed"] = time.time()
            
            try:
                 with open(self._usage_file, 'w', encoding='utf-8') as f:
                     json.dump(usage, f)
            except Exception as e:
                 log.warning(f"Failed to update usage record: {e}")

    def play_tts(self, text: str):
        """Fetch TTS in a background thread and play it."""
        if not self._api_key:
            log.warning("ElevenLabs API key not set")
            self.playback_finished.emit()
            return
            
        # Clean up text for TTS: remove common text emoticons the pet uses
        emoticons = [
            ":3", "^_^", ":)", ":(", ":D", ":P", ":O", ";)", "T_T", 
            "-_-", "o_o", "O_O", "UwU", "uwu", "OwO", "owo", "<3", "~_~", "u_u"
        ]
        clean_text = text
        for e in emoticons:
            clean_text = clean_text.replace(e, "")
        clean_text = clean_text.strip()
            
        def _worker():
            try:
                allow_cache = self._allow_cache_func() if self._allow_cache_func else True
                text_hash = hashlib.md5(clean_text.encode('utf-8')).hexdigest()
                filename = f"{self._voice_id}_{self._model_id}_{text_hash}.mp3"
                
                if allow_cache:
                    os.makedirs(self._cache_dir, exist_ok=True)
                    output_path = os.path.join(self._cache_dir, filename)
                    if os.path.exists(output_path) and _is_valid_mp3(output_path):
                        log.debug(f"Using cached TTS audio for text: {clean_text[:30]}...")
                        self._update_usage_record(filename)
                        self._playback_ready.emit(output_path)
                        return
                    elif os.path.exists(output_path):
                        log.debug(f"Discarding corrupted cache file: {filename}")
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass
                else:
                    output_path = os.path.join(tempfile.gettempdir(), f"temp_{filename}")

                url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
                headers = {
                    "xi-api-key": self._api_key,
                    "content-type": "application/json",
                    "accept": "audio/mpeg"
                }
                payload = {
                    "text": clean_text,
                    "model_id": self._model_id,
                    "output_format": "mp3_44100_128",
                }
                
                log.debug(f"Requesting TTS from ElevenLabs for text: {clean_text[:30]}...")
                response = requests.post(url, json=payload, headers=headers, stream=True, timeout=10)
                
                if response.status_code == 200:
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=4096):
                            if chunk:
                                f.write(chunk)
                    
                    if allow_cache:
                        self._update_usage_record(filename)
                        self._enforce_cache_limit()
                    
                    # Safely emit signal to transition to the main GUI thread
                    self._playback_ready.emit(output_path)
                else:
                    log.error(f"ElevenLabs TTS failed with HTTP {response.status_code}: {response.text}")
                    self.playback_finished.emit()
            except Exception as e:
                log.error(f"Error calling ElevenLabs API: {e}")
                self.playback_finished.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _start_playback(self, file_path: str):
        # Stop previous playback if any
        self._cleanup()
        self._current_temp_file = file_path

        if not _is_valid_mp3(file_path):
            log.warning("Skipping invalid audio file: %s", file_path)
            self.playback_finished.emit()
            return

        self._player.setSource(QUrl.fromLocalFile(file_path))
        self._player.play()

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._cleanup()
            self.playback_finished.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            if self._current_temp_file:
                log.warning("Invalid media detected, removing corrupted file: %s", self._current_temp_file)
                try:
                    os.remove(self._current_temp_file)
                except Exception:
                    pass
            self._cleanup()
            self.playback_finished.emit()

    def _enforce_cache_limit(self):
        """Enforces a 100MB cache limit by deleting least frequently used (LFU) files."""
        max_bytes = 100 * 1024 * 1024  # 100 MB
        target_bytes = 90 * 1024 * 1024  # Target 90 MB when cleaning up
        
        with self._usage_lock:
            try:
                usage = {}
                if os.path.exists(self._usage_file):
                    with open(self._usage_file, 'r', encoding='utf-8') as f:
                        usage = json.load(f)
            except Exception:
                usage = {}
                
            try:
                files = []
                total_size = 0
                for filename in os.listdir(self._cache_dir):
                    if filename == "usage.json":
                        continue
                    path = os.path.join(self._cache_dir, filename)
                    if os.path.isfile(path) and filename.endswith(".mp3"):
                        stat = os.stat(path)
                        file_usage = usage.get(filename, {"count": 1, "last_accessed": stat.st_atime})
                        files.append((path, filename, stat.st_size, file_usage["count"], file_usage["last_accessed"]))
                        total_size += stat.st_size
                        
                if total_size > max_bytes:
                    # Sort primarily by access count (ascending), then by last access (ascending)
                    files.sort(key=lambda x: (x[3], x[4]))
                    
                    for path, filename, size, count, _ in files:
                        try:
                            # Skip if it is the currently playing file
                            if path == self._current_temp_file:
                                continue
                            os.remove(path)
                            total_size -= size
                            if filename in usage:
                                del usage[filename]
                            log.debug(f"Cache Eviction (LFU): deleted {path} ({size} bytes, usage count: {count})")
                            if total_size <= target_bytes:
                                break
                        except Exception as e:
                            log.warning(f"Failed to delete cached file {path}: {e}")
                            
                    # Save the cleaned up usage back
                    try:
                        with open(self._usage_file, 'w', encoding='utf-8') as f:
                            json.dump(usage, f)
                    except Exception:
                        pass
            except Exception as e:
                log.error(f"Error enforcing cache limit: {e}")

    def _cleanup(self):
        """Stop player and release the file handle."""
        if self._current_temp_file:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
                allow_cache = self._allow_cache_func() if self._allow_cache_func else True
                if not allow_cache and os.path.exists(self._current_temp_file):
                    try:
                        os.remove(self._current_temp_file)
                    except Exception:
                        pass
                self._current_temp_file = None
            except Exception as e:
                log.warning(f"Error cleaning up TTS media player: {e}")

import json
import pyaudio
import websockets.sync.client

class AssemblyAISTTClient:
    """Client for AssemblyAI Realtime STT using v3 websockets."""
    
    def __init__(self, api_key: str, model: str = "universal-streaming-multilingual"):
        self._api_key = api_key
        self._model = model
        self.on_transcript_callback: Optional[Callable[[str], None]] = None
        self.on_error_callback: Optional[Callable[[str], None]] = None
        
        self._is_recording = False
        self._should_record_audio = False
        self._finalized_turns = []
        self._active_turn_text = ""
        self._pending_unformatted_turn: Optional[str] = None  # end_of_turn received, awaiting is_formatted

    def start_listening(self):
        if not self._api_key:
            log.warning("AssemblyAI API key not set")
            if self.on_error_callback:
                self.on_error_callback("No API key")
            return
            
        if self._is_recording:
            return
            
        self._finalized_turns = []
        self._active_turn_text = ""
        self._pending_unformatted_turn = None
        self._is_recording = True
        self._should_record_audio = True
        
        def _worker():
            _RATE = 16000
            _VAD_MS = 30  # webrtcvad requires 10/20/30 ms frames
            _VAD_FRAMES = int(_RATE * _VAD_MS / 1000)  # 480 samples
            _PRE_ROLL = 33  # ~1 s of audio at 30 ms/frame
            _SEND_BYTES = int(_RATE * 2 * 240 / 1000)  # 7680 — ~240 ms batch for WS
            _MIN_SEND_BYTES = int(_RATE * 2 * 50 / 1000)  # 1600 — 50 ms floor (API minimum)

            url = (
                f"wss://streaming.assemblyai.com/v3/ws"
                f"?sample_rate={_RATE}"
                f"&encoding=pcm_s16le"
                f"&format_turns=true"
                f"&speech_model={self._model}"
                f"&end_of_turn_confidence_threshold=0.85"
                f"&min_end_of_turn_silence_when_confident=500"
            )
            headers = {"Authorization": self._api_key}

            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16, channels=1,
                rate=_RATE, input=True,
                frames_per_buffer=_VAD_FRAMES,
            )

            try:
                # --- VAD pre-gate: buffer locally, connect only on speech ---
                pre_data = b""
                try:
                    import sys as _sys
                    _vad_obj = None
                    _vad_type = None  # 'webrtcvad' or 'silero'

                    if _sys.platform == "darwin":
                        try:
                            from silero_vad import load as _silero_load
                            _silero_model = _silero_load()
                            _vad_obj = _silero_model
                            _vad_type = "silero"
                        except ImportError:
                            pass
                    if _vad_obj is None:
                        try:
                            import webrtcvad
                            _vad_obj = webrtcvad.Vad(2)  # aggressiveness 0-3
                            _vad_type = "webrtcvad"
                        except ImportError:
                            pass

                    if _vad_obj is not None:
                        ring = deque(maxlen=_PRE_ROLL)
                        while self._should_record_audio:
                            frame = stream.read(_VAD_FRAMES, exception_on_overflow=False)
                            ring.append(frame)
                            if _vad_type == "webrtcvad":
                                speech = _vad_obj.is_speech(frame, _RATE)
                            else:  # silero
                                import torch
                                audio_tensor = torch.frombuffer(frame, dtype=torch.int16).float() / 32768.0
                                speech = _vad_obj(audio_tensor, _RATE).item() > 0.5
                            if speech:
                                break
                        if not self._should_record_audio:
                            return  # cancelled before speech — no WS opened, no billing
                        pre_data = b"".join(ring)
                        log.debug("VAD pre-gate (%s): speech detected, buffered %d bytes", _vad_type, len(pre_data))
                    else:
                        log.debug("No VAD available; connecting immediately (no pre-gate)")
                except ImportError:
                    log.debug("VAD import error; connecting immediately (no pre-gate)")

                # --- Stream via WS ---
                with websockets.sync.client.connect(url, additional_headers=headers) as ws:

                    def _receive():
                        try:
                            for message in ws:
                                data = json.loads(message)
                                mtype = data.get("type", "").lower()
                                
                                if mtype == "error":
                                    err_msg = data.get("error") or data.get("message")
                                    log.error(f"AssemblyAI Error: {err_msg}")
                                    if self.on_error_callback:
                                        self.on_error_callback(err_msg)
                                    self._is_recording = False
                                    break
                                elif mtype == "turn":
                                    text = data.get("transcript", "").strip()
                                    end_of_turn = data.get("end_of_turn")
                                    is_formatted = data.get("turn_is_formatted")

                                    # Skip empty turns — AssemblyAI sends them as
                                    # "turn started" signals before the real transcript arrives.
                                    if not text:
                                        continue

                                    if end_of_turn:
                                        if is_formatted:
                                            # Canonical final for this turn.
                                            self._pending_unformatted_turn = None
                                            if self._finalized_turns and self._finalized_turns[-1] == text:
                                                log.debug(f"STT: dropping consecutive duplicate turn: '{text}'")
                                            else:
                                                self._finalized_turns.append(text)
                                            self._active_turn_text = ""
                                        else:
                                            # Unformatted boundary — hold it until the formatted version
                                            # arrives (or until we finalize without a formatted follow-up).
                                            self._pending_unformatted_turn = text
                                            self._active_turn_text = ""
                                    elif is_formatted and self._pending_unformatted_turn:
                                        # Formatted version of a previously ended unformatted turn.
                                        self._pending_unformatted_turn = None
                                        if self._finalized_turns and self._finalized_turns[-1] == text:
                                            log.debug(f"STT: dropping consecutive duplicate turn: '{text}'")
                                        else:
                                            self._finalized_turns.append(text)
                                        self._active_turn_text = ""
                                    else:
                                        # Intermediate progressive update — just track it.
                                        self._active_turn_text = text

                                    # If user stopped recording and we just got the final turn output, we are done
                                    if not self._should_record_audio and (end_of_turn or is_formatted):
                                        self._is_recording = False
                                        break
                                elif mtype == "termination":
                                    self._is_recording = False
                                    break
                        except Exception as e:
                            log.debug(f"AssemblyAI WS receive error: {e}")

                    recv_thread = threading.Thread(target=_receive, daemon=True)
                    recv_thread.start()
                    
                    try:
                        buf = pre_data  # seed with VAD pre-buffer (may be empty)
                        while self._should_record_audio:
                            data = stream.read(_VAD_FRAMES, exception_on_overflow=False)
                            buf += data
                            if len(buf) >= _SEND_BYTES:
                                ws.send(buf)
                                buf = b""
                        if len(buf) >= _MIN_SEND_BYTES:
                            ws.send(buf)
                    except Exception as e:
                        log.debug(f"Audio read error: {e}")
                    finally:
                        try:
                            ws.send(json.dumps({"type": "ForceEndpoint"}))
                            # Wait up to 3 seconds for the final response
                            for _ in range(30):
                                if not self._is_recording:
                                    break
                                time.sleep(0.1)
                            ws.send(json.dumps({"type": "Terminate"}))
                        except: pass
                        self._is_recording = False
                        
                        final_text = " ".join(self._finalized_turns)
                        # If a turn ended but no formatted message arrived before termination,
                        # fall back to the pending unformatted text.
                        if self._pending_unformatted_turn:
                            if not self._finalized_turns or self._finalized_turns[-1] != self._pending_unformatted_turn:
                                final_text += (" " if final_text else "") + self._pending_unformatted_turn
                        elif self._active_turn_text:
                            final_text += (" " if final_text else "") + self._active_turn_text
                        final_text = final_text.strip()
                        log.info(f"STT final transcript: '{final_text}'")
                        if final_text and self.on_transcript_callback:
                            self.on_transcript_callback(final_text)
                        elif not final_text:
                            log.warning("STT finished with empty transcript")
            except Exception as e:
                log.error(f"Failed to start AssemblyAI STT: {e}")
                if self.on_error_callback:
                    self.on_error_callback(str(e))
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
                p.terminate()
                self._is_recording = False
        
        threading.Thread(target=_worker, daemon=True).start()

    def stop_listening(self) -> str:
        """Stop listening. The worker thread will collect the final transcript and trigger the callback."""
        if not self._should_record_audio:
            return ""
        self._should_record_audio = False
        return ""
