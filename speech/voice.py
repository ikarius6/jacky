import os
import sys
import time
import logging
import tempfile
import threading
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

    def __init__(self, api_key: str, voice_id: str = "U0W3edavfdI8ibPeeteQ", model_id: str = "eleven_flash_v2_5"):
        super().__init__()
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._current_temp_file: Optional[str] = None

    def play_tts(self, text: str):
        """Fetch TTS in a background thread and play it."""
        if not self._api_key:
            log.warning("ElevenLabs API key not set")
            self.playback_finished.emit()
            return
            
        def _worker():
            try:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
                headers = {
                    "xi-api-key": self._api_key,
                    "content-type": "application/json",
                    "accept": "audio/mpeg"
                }
                payload = {
                    "text": text,
                    "model_id": self._model_id,
                    "output_format": "mp3_44100_128",
                }
                
                log.debug(f"Requesting TTS from ElevenLabs for text: {text[:30]}...")
                response = requests.post(url, json=payload, headers=headers, stream=True, timeout=10)
                
                if response.status_code == 200:
                    fd, temp_path = tempfile.mkstemp(suffix=".mp3")
                    with os.fdopen(fd, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=4096):
                            if chunk:
                                f.write(chunk)
                    
                    # Playback must be initiated on the main thread
                    # QTimer.singleShot is thread-safe in PyQt6 for invoking across threads
                    QTimer.singleShot(0, lambda: self._start_playback(temp_path))
                else:
                    log.error(f"ElevenLabs TTS failed with HTTP {response.status_code}: {response.text}")
                    QTimer.singleShot(0, self.playback_finished.emit)
            except Exception as e:
                log.error(f"Error calling ElevenLabs API: {e}")
                QTimer.singleShot(0, self.playback_finished.emit)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_playback(self, file_path: str):
        # Clean up previous temp file if it exists
        self._cleanup()
        self._current_temp_file = file_path
        
        self._player.setSource(QUrl.fromLocalFile(file_path))
        self._player.play()

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia or status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._cleanup()
            self.playback_finished.emit()

    def _cleanup(self):
        """Delete the current temp file if it exists."""
        if self._current_temp_file and os.path.exists(self._current_temp_file):
            try:
                # Stop player to release file handle just in case
                self._player.stop()
                self._player.setSource(QUrl())
                os.remove(self._current_temp_file)
                self._current_temp_file = None
            except Exception as e:
                log.warning(f"Could not delete temp TTS file {self._current_temp_file}: {e}")

import json
import pyaudio
import websockets.sync.client

class AssemblyAISTTClient:
    """Client for AssemblyAI Realtime STT using v3 websockets."""
    
    def __init__(self, api_key: str):
        self._api_key = api_key
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
            url = "wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le&format_turns=true&speech_model=u3-rt-pro"
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
