import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from PyQt6.QtCore import QTimer

log = logging.getLogger("peer_discovery")

_PEERS_FILE = os.path.join(tempfile.gettempdir(), "jacky_peers.json")
_HEARTBEAT_TIMEOUT = 10.0  # seconds before a peer is considered dead
_EVENT_TTL = 30.0  # seconds before stale events are cleaned up


@dataclass
class PeerInfo:
    """Data about a remote Jacky instance."""
    pid: int = 0
    hwnd: int = 0
    pet_name: str = ""
    display_name: str = ""
    character: str = ""
    x: int = 0
    y: int = 0
    state: str = "idle"
    direction: int = 1
    registered_at: float = 0.0
    heartbeat: float = 0.0


@dataclass
class PeerEvent:
    """An event sent from one peer to another."""
    id: str = ""
    type: str = ""  # "greet", "attack", "chase", "dance", "fight"
    source_pid: int = 0
    target_pid: int = 0
    timestamp: float = 0.0
    data: dict = field(default_factory=dict)


def _read_peers_file() -> dict:
    """Read and parse the shared peers JSON file. Returns empty structure on failure."""
    empty = {"peers": {}, "events": []}
    if not os.path.exists(_PEERS_FILE):
        return empty
    try:
        with open(_PEERS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return empty
        data = json.loads(content)
        if "peers" not in data:
            data["peers"] = {}
        if "events" not in data:
            data["events"] = []
        return data
    except (OSError, json.JSONDecodeError, PermissionError):
        return empty


def _write_peers_file(data: dict):
    """Atomically write the peers JSON file using a PID-specific temp file."""
    tmp_path = _PEERS_FILE + f".{os.getpid()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Retry os.replace a few times — the target may be briefly open by another instance
        for attempt in range(5):
            try:
                os.replace(tmp_path, _PEERS_FILE)
                return
            except PermissionError:
                time.sleep(0.05)
        # Final attempt — let it raise
        os.replace(tmp_path, _PEERS_FILE)
    except OSError as e:
        log.warning("Failed to write peers file: %s", e)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class PeerDiscovery:
    """Discovers and communicates with other Jacky instances via a shared JSON file."""

    def __init__(self, pet_window):
        self._pw = pet_window
        self._pid = os.getpid()
        self._display_name = ""
        self._known_peers: Dict[int, PeerInfo] = {}  # pid -> PeerInfo
        self._processed_event_ids: Set[str] = set()
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._max_peers = 5

        # Callbacks
        self.on_peer_joined: Optional[Callable[[PeerInfo], None]] = None
        self.on_peer_left: Optional[Callable[[PeerInfo], None]] = None
        self.on_event_received: Optional[Callable[[PeerEvent], None]] = None

    @property
    def display_name(self) -> str:
        return self._display_name

    def start(self, poll_interval_ms: int = 500, max_peers: int = 5):
        """Register this instance and start polling for peers."""
        self._max_peers = max_peers
        self._register()
        self._poll_timer.start(poll_interval_ms)
        log.info("PeerDiscovery started: pid=%d display_name='%s'", self._pid, self._display_name)

    def stop(self):
        """Unregister this instance and stop polling."""
        self._poll_timer.stop()
        self._unregister()
        log.info("PeerDiscovery stopped: pid=%d", self._pid)

    def get_peers(self) -> List[PeerInfo]:
        """Return list of live peers (excluding self), limited by max_peers."""
        peers = list(self._known_peers.values())
        return peers[:self._max_peers]

    def get_peer_pids(self) -> Set[int]:
        """Return set of PIDs belonging to known peer instances."""
        return set(self._known_peers.keys())

    def send_event(self, target_pid: int, event_type: str, data: Optional[dict] = None):
        """Send an event to a specific peer."""
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "source_pid": self._pid,
            "target_pid": target_pid,
            "timestamp": time.time(),
            "data": data or {},
        }
        file_data = _read_peers_file()
        file_data["events"].append(event)
        _write_peers_file(file_data)
        log.info("SEND_EVENT type=%s target=%d id=%s", event_type, target_pid, event["id"])

    def _register(self):
        """Register this instance in the shared file."""
        file_data = _read_peers_file()
        now = time.time()

        # Assign unique display name
        self._display_name = self._assign_display_name(file_data)

        hwnd = 0
        try:
            hwnd = int(self._pw.winId())
        except Exception:
            pass

        my_entry = {
            "pid": self._pid,
            "hwnd": hwnd,
            "pet_name": self._pw.pet.name,
            "display_name": self._display_name,
            "character": self._pw._config.get("character", "Forest Ranger 3"),
            "x": self._pw.x(),
            "y": self._pw.y(),
            "state": self._pw.pet.state.name.lower(),
            "direction": self._pw.pet.direction,
            "registered_at": now,
            "heartbeat": now,
        }
        file_data["peers"][str(self._pid)] = my_entry
        _write_peers_file(file_data)

    def _unregister(self):
        """Remove this instance from the shared file."""
        file_data = _read_peers_file()
        file_data["peers"].pop(str(self._pid), None)
        # Clean up events we sent
        file_data["events"] = [
            e for e in file_data["events"]
            if e.get("source_pid") != self._pid
        ]
        _write_peers_file(file_data)

    def _assign_display_name(self, file_data: dict) -> str:
        """Assign a unique display name like 'Jacky #1', resolving duplicates."""
        my_name = self._pw.pet.name
        existing_names = set()
        for pid_str, peer in file_data.get("peers", {}).items():
            if int(pid_str) != self._pid:
                existing_names.add(peer.get("display_name", ""))

        # Check if the base name is taken
        if my_name not in existing_names:
            # Check if there are any peers with the same pet_name
            same_name_peers = [
                p for pid_str, p in file_data.get("peers", {}).items()
                if int(pid_str) != self._pid and p.get("pet_name") == my_name
            ]
            if not same_name_peers:
                return my_name

        # Need a numbered suffix
        for i in range(1, 100):
            candidate = f"{my_name} #{i}"
            if candidate not in existing_names:
                return candidate
        return f"{my_name} #{self._pid}"

    def _poll(self):
        """Read shared file, update heartbeat, detect peer changes, process events."""
        file_data = _read_peers_file()
        now = time.time()

        # Update our own entry
        my_key = str(self._pid)
        if my_key in file_data["peers"]:
            current_name = self._pw.pet.name
            old_pet_name = file_data["peers"][my_key].get("pet_name", "")
            if current_name != old_pet_name:
                self._display_name = self._assign_display_name(file_data)
                file_data["peers"][my_key]["pet_name"] = current_name
                file_data["peers"][my_key]["display_name"] = self._display_name
            file_data["peers"][my_key]["heartbeat"] = now
            file_data["peers"][my_key]["x"] = self._pw.x()
            file_data["peers"][my_key]["y"] = self._pw.y()
            file_data["peers"][my_key]["state"] = self._pw.pet.state.name.lower()
            file_data["peers"][my_key]["direction"] = self._pw.pet.direction
            try:
                file_data["peers"][my_key]["hwnd"] = int(self._pw.winId())
            except Exception:
                pass
        else:
            # We got cleaned out somehow — re-register
            self._register()
            return

        # Clean stale peers
        stale_pids = []
        for pid_str, peer in list(file_data["peers"].items()):
            pid = int(pid_str)
            if pid == self._pid:
                continue
            if (now - peer.get("heartbeat", 0)) > _HEARTBEAT_TIMEOUT:
                stale_pids.append(pid_str)
                # Also check if we knew this peer
                if pid in self._known_peers:
                    left_peer = self._known_peers.pop(pid)
                    log.info("PEER_STALE pid=%d name='%s'", pid, left_peer.display_name)
                    if self.on_peer_left:
                        self.on_peer_left(left_peer)

        for pid_str in stale_pids:
            file_data["peers"].pop(pid_str, None)

        # Clean stale events
        file_data["events"] = [
            e for e in file_data["events"]
            if (now - e.get("timestamp", 0)) < _EVENT_TTL
        ]

        # Detect new and updated peers
        for pid_str, peer_data in file_data["peers"].items():
            pid = int(pid_str)
            if pid == self._pid:
                continue

            peer_info = PeerInfo(
                pid=peer_data.get("pid", pid),
                hwnd=peer_data.get("hwnd", 0),
                pet_name=peer_data.get("pet_name", ""),
                display_name=peer_data.get("display_name", ""),
                character=peer_data.get("character", ""),
                x=peer_data.get("x", 0),
                y=peer_data.get("y", 0),
                state=peer_data.get("state", "idle"),
                direction=peer_data.get("direction", 1),
                registered_at=peer_data.get("registered_at", 0),
                heartbeat=peer_data.get("heartbeat", 0),
            )

            if pid not in self._known_peers:
                # Respect max_peers limit
                if len(self._known_peers) >= self._max_peers:
                    continue
                self._known_peers[pid] = peer_info
                log.info("PEER_JOINED pid=%d name='%s' pos=(%d,%d)",
                         pid, peer_info.display_name, peer_info.x, peer_info.y)
                if self.on_peer_joined:
                    self.on_peer_joined(peer_info)
            else:
                # Update existing peer info
                self._known_peers[pid] = peer_info

        # Detect peers that left (not stale, just gone from file)
        current_pids = {int(p) for p in file_data["peers"] if int(p) != self._pid}
        for pid in list(self._known_peers.keys()):
            if pid not in current_pids:
                left_peer = self._known_peers.pop(pid)
                log.info("PEER_LEFT pid=%d name='%s'", pid, left_peer.display_name)
                if self.on_peer_left:
                    self.on_peer_left(left_peer)

        # Process events directed at us
        remaining_events = []
        for evt in file_data["events"]:
            if evt.get("target_pid") == self._pid and evt.get("id") not in self._processed_event_ids:
                self._processed_event_ids.add(evt["id"])
                peer_event = PeerEvent(
                    id=evt.get("id", ""),
                    type=evt.get("type", ""),
                    source_pid=evt.get("source_pid", 0),
                    target_pid=evt.get("target_pid", 0),
                    timestamp=evt.get("timestamp", 0),
                    data=evt.get("data", {}),
                )
                log.info("RECV_EVENT type=%s from=%d id=%s",
                         peer_event.type, peer_event.source_pid, peer_event.id)
                if self.on_event_received:
                    self.on_event_received(peer_event)
                # Don't keep processed events in remaining
                continue
            remaining_events.append(evt)

        file_data["events"] = remaining_events
        _write_peers_file(file_data)

        # Trim processed event IDs cache to prevent unbounded growth
        if len(self._processed_event_ids) > 500:
            self._processed_event_ids = set(list(self._processed_event_ids)[-200:])
