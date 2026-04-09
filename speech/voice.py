import os
import sys
import time
import logging
import tempfile
import threading
import hashlib
import json
from typing import Callable, Optional

import requests
import assemblyai as aai
from PyQt6.QtCore import QUrl, QObject, pyqtSignal, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

log = logging.getLogger("speech.voice")

class ElevenLabsTTSClient(QObject):
    """Client for ElevenLabs Text-to-Speech API.
    Downloads the audio stream and plays it using QMediaPlayer."""

    # Signal to notify when playback finishes (or errors)
    playback_finished = pyqtSignal()
    # Internal signal to safely transition from worker thread to main thread
    _playback_ready = pyqtSignal(str)

    def __init__(self, api_key: str, voice_id: str = "U0W3edavfdI8ibPeeteQ", model_id: str = "eleven_flash_v2_5"):
        super().__init__()
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._playback_ready.connect(self._start_playback)
        self._current_temp_file: Optional[str] = None
        
        self._cache_dir = os.path.join(tempfile.gettempdir(), "jacky_tts_cache")
        os.makedirs(self._cache_dir, exist_ok=True)
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
                text_hash = hashlib.md5(clean_text.encode('utf-8')).hexdigest()
                filename = f"{self._voice_id}_{self._model_id}_{text_hash}.mp3"
                cache_path = os.path.join(self._cache_dir, filename)

                if os.path.exists(cache_path):
                    log.debug(f"Using cached TTS audio for text: {clean_text[:30]}...")
                    self._update_usage_record(filename)
                    self._playback_ready.emit(cache_path)
                    return

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
                    with open(cache_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=4096):
                            if chunk:
                                f.write(chunk)
                    
                    self._update_usage_record(filename)
                    self._enforce_cache_limit()
                    
                    # Safely emit signal to transition to the main GUI thread
                    self._playback_ready.emit(cache_path)
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
        
        self._player.setSource(QUrl.fromLocalFile(file_path))
        self._player.play()

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia or status == QMediaPlayer.MediaStatus.InvalidMedia:
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
                self._current_temp_file = None
            except Exception as e:
                log.warning(f"Error cleaning up TTS media player: {e}")

import json
import pyaudio
import websockets.sync.client

class AssemblyAISTTClient:
    """Client for AssemblyAI Realtime STT using v3 websockets."""
    
    def __init__(self, api_key: str, model: str = "u3-rt-pro"):
        self._api_key = api_key
        self._model = model
        self.on_transcript_callback: Optional[Callable[[str], None]] = None
        self.on_error_callback: Optional[Callable[[str], None]] = None
        
        self._is_recording = False
        self._should_record_audio = False
        self._current_text = ""
        self._active_turn_text = ""

    def start_listening(self):
        if not self._api_key:
            log.warning("AssemblyAI API key not set")
            if self.on_error_callback:
                self.on_error_callback("No API key")
            return
            
        if self._is_recording:
            return
            
        self._current_text = ""
        self._active_turn_text = ""
        self._is_recording = True
        self._should_record_audio = True
        
        def _worker():
            url = f"wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le&format_turns=true&speech_model={self._model}"
            headers = {"Authorization": self._api_key}
            
            try:
                with websockets.sync.client.connect(url, additional_headers=headers) as ws:
                    p = pyaudio.PyAudio()
                    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4000)
                    
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

                                    if end_of_turn or is_formatted:
                                        self._current_text += text + " "
                                        self._active_turn_text = ""
                                    else:
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
                        while self._should_record_audio:
                            data = stream.read(4000, exception_on_overflow=False)
                            ws.send(data)
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
                        stream.stop_stream()
                        stream.close()
                        p.terminate()
                        self._is_recording = False
                        
                        final_text = (self._current_text.strip() + " " + self._active_turn_text.strip()).strip()
                        log.info(f"STT final transcript: '{final_text}'")
                        if final_text and self.on_transcript_callback:
                            self.on_transcript_callback(final_text)
                        elif not final_text:
                            log.warning("STT finished with empty transcript")
            except Exception as e:
                log.error(f"Failed to start AssemblyAI STT: {e}")
                self._is_recording = False
                if self.on_error_callback:
                    self.on_error_callback(str(e))
        
        threading.Thread(target=_worker, daemon=True).start()

    def stop_listening(self) -> str:
        """Stop listening. The worker thread will collect the final transcript and trigger the callback."""
        if not self._should_record_audio:
            return ""
        self._should_record_audio = False
        return ""
