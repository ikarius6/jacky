import logging
import random

from PyQt6.QtCore import QTimer

from core.pet import PetState
from interaction.peer_discovery import PeerInfo, PeerEvent
from speech.dialogue import get_line

log = logging.getLogger("peer_interactions")

# Weighted probability for each spontaneous peer action
_PEER_ACTION_WEIGHTS = {
    "greet": 0.30,
    "attack": 0.15,
    "chase": 0.15,
    "dance": 0.20,
    "fight": 0.20,
}


class PeerInteractionHandler:
    """Handles interactions between this Jacky instance and peer instances.

    Analogous to ``WindowInteractionHandler`` but for peer Jackys.
    Owns both the outgoing actions (initiated by this pet) and the
    incoming reactions (events received from other pets).
    """

    def __init__(self, pet_window):
        self._pw = pet_window
        self._walk_to_peer: PeerInfo | None = None
        self._walk_action: str | None = None  # action to perform on arrival
        self._chase_timer: QTimer | None = None
        self._fight_timer: QTimer | None = None
        self._fight_step: int = 0
        self._fight_target_pid: int = 0
        self._fight_role: str | None = None

    # ------------------------------------------------------------------
    # Scheduler entry point (spontaneous interactions)
    # ------------------------------------------------------------------

    def scheduled_interact(self):
        """Called by the Scheduler — pick a random peer and interact."""
        pw = self._pw
        if pw._silent_mode:
            return
        if pw.pet.state in (PetState.DRAGGED, PetState.FALLING, PetState.PEEKING):
            return

        peers = pw._peer_discovery.get_peers()
        if not peers:
            return

        target = random.choice(peers)
        actions = list(_PEER_ACTION_WEIGHTS.keys())
        weights = list(_PEER_ACTION_WEIGHTS.values())
        action = random.choices(actions, weights=weights, k=1)[0]

        log.info("SCHED peer_interact action=%s target='%s' pid=%d",
                 action, target.display_name, target.pid)

        handler = getattr(self, f"do_{action}", None)
        if handler:
            handler(target)

    # ------------------------------------------------------------------
    # Outgoing actions (initiated by THIS Jacky)
    # ------------------------------------------------------------------

    def do_greet(self, target: PeerInfo):
        """Walk toward the peer and greet them."""
        self._walk_toward_peer(target, "greet")

    def do_attack(self, target: PeerInfo):
        """Walk toward the peer and attack them."""
        self._walk_toward_peer(target, "attack")

    def do_chase(self, target: PeerInfo):
        """Continuously chase the peer for ~5 seconds."""
        pw = self._pw
        # Send the event and say the line, but set movement state AFTER _say so
        # we win over the TALKING state that _say may apply internally.
        pw._peer_discovery.send_event(target.pid, "chase")
        pw._say(get_line("peer_chase", pw.pet.name, peer_name=target.display_name))

        # Start chasing: update target position every 300ms
        self._chase_target_pid = target.pid
        if self._chase_timer is not None:
            self._chase_timer.stop()
            self._chase_timer.deleteLater()
        self._chase_timer = QTimer()
        self._chase_remaining = 16  # ~16 * 300ms = ~5 seconds
        self._chase_timer.timeout.connect(self._chase_tick)
        self._chase_timer.start(300)

        # Force movement state AFTER _say so it overrides any TALKING state.
        if "run" in pw.animation.available_states:
            pw.pet.set_state(PetState.RUNNING)
        else:
            pw.pet.set_state(PetState.WALKING)

    def do_dance(self, target: PeerInfo):
        """Start dancing and invite the peer to dance too."""
        pw = self._pw
        pw.pet.set_state(PetState.HAPPY)
        pw._say(get_line("peer_dance", pw.pet.name, peer_name=target.display_name))
        pw._peer_discovery.send_event(target.pid, "dance")
        pw._temp_state_timer.start(4000)

    def do_fight(self, target: PeerInfo):
        """Initiate a multi-round fight with the peer."""
        pw = self._pw
        pw._peer_discovery.send_event(target.pid, "fight")
        self._fight_target_pid = target.pid
        self._fight_step = 0
        self._fight_role = "initiator"

        # First strike (step 0)
        self._do_fight_strike(target)

    # ------------------------------------------------------------------
    # Walk-toward-peer logic
    # ------------------------------------------------------------------

    def _walk_toward_peer(self, target: PeerInfo, action: str):
        """Set the pet walking toward a peer's position. Execute action on arrival."""
        pw = self._pw
        if pw.pet.state not in (PetState.IDLE, PetState.WALKING, PetState.RUNNING, PetState.INTERACTING):
            return

        self._walk_to_peer = target
        self._walk_action = action

        # Convert peer position to target coords (DPI-aware)
        s = pw.movement._dpi_scale
        target_x = int(target.x / s) if s > 1.0 else target.x
        target_y = int(target.y / s) if s > 1.0 else target.y

        pw.movement._target_x = target_x
        pw.movement._target_y = target_y
        pw.movement._direction = 1 if target_x > pw.movement.x else -1
        pw.pet.direction = pw.movement._direction
        if "run" in pw.animation.available_states:
            pw.pet.set_state(PetState.RUNNING)
        else:
            pw.pet.set_state(PetState.WALKING)

        log.info("WALK_TO_PEER '%s' target=(%d,%d) action=%s",
                 target.display_name, target_x, target_y, action)

    def check_peer_arrival(self):
        """Called from PetWindow._on_move_tick to check if we arrived near a peer.
        Should be called every movement tick when _walk_to_peer is set.
        """
        if self._walk_to_peer is None:
            return

        pw = self._pw
        target = self._walk_to_peer

        # Refresh target position from latest peer data
        peers = pw._peer_discovery.get_peers()
        for p in peers:
            if p.pid == target.pid:
                target = p
                self._walk_to_peer = p
                break

        # Check proximity (~100px)
        dx = abs(pw.x() - target.x)
        dy = abs(pw.y() - target.y)
        distance = (dx * dx + dy * dy) ** 0.5

        if distance < 120 or pw.pet.state == PetState.IDLE:
            # Arrived or walk finished
            action = self._walk_action
            peer = self._walk_to_peer
            self._walk_to_peer = None
            self._walk_action = None

            if action and peer:
                self._execute_arrival_action(action, peer)

    def _execute_arrival_action(self, action: str, peer: PeerInfo):
        """Execute the planned action now that we've arrived near the peer."""
        pw = self._pw
        if action == "greet":
            pw.pet.set_state(PetState.HAPPY)
            pw._say(get_line("peer_greet", pw.pet.name, peer_name=peer.display_name))
            pw._peer_discovery.send_event(peer.pid, "greet")
            pw._temp_state_timer.start(2500)

        elif action == "attack":
            if "shooting" in pw.animation.available_states:
                pw.pet.set_state(PetState.SHOOTING)
            elif "slashing" in pw.animation.available_states:
                pw.pet.set_state(PetState.SLASHING)
            else:
                pw.pet.set_state(PetState.INTERACTING)
            pw._say(get_line("peer_attack", pw.pet.name, peer_name=peer.display_name))
            pw._peer_discovery.send_event(peer.pid, "attack")
            pw._temp_state_timer.start(2000)

    # ------------------------------------------------------------------
    # Chase logic
    # ------------------------------------------------------------------

    def _chase_tick(self):
        """Update chase target position and move toward it."""
        pw = self._pw
        self._chase_remaining -= 1

        if self._chase_remaining <= 0:
            self._stop_chase()
            return

        peers = pw._peer_discovery.get_peers()
        target = None
        for p in peers:
            if p.pid == self._chase_target_pid:
                target = p
                break

        if target is None:
            self._stop_chase()
            return

        # Update movement target to peer's current position
        pw.movement._target_x = target.x
        pw.movement._target_y = target.y
        pw.movement._direction = 1 if target.x > pw.movement.x else -1
        pw.pet.direction = pw.movement._direction

        # Re-assert movement state every tick: the talk-end timer or other events
        # may have reset the pet to IDLE, which stops _on_move_tick from calling
        # movement.tick().  This keeps the chaser actually running.
        if pw.pet.state not in (PetState.RUNNING, PetState.WALKING,
                                PetState.DRAGGED, PetState.FALLING):
            if "run" in pw.animation.available_states:
                pw.pet.set_state(PetState.RUNNING)
            else:
                pw.pet.set_state(PetState.WALKING)

    def _stop_chase(self):
        """Stop the chase."""
        if self._chase_timer is not None:
            self._chase_timer.stop()
            self._chase_timer.deleteLater()
            self._chase_timer = None
        pw = self._pw
        pw.movement.stop()
        if pw.pet.state in (PetState.RUNNING, PetState.WALKING):
            pw.pet.set_state(PetState.IDLE)

    # ------------------------------------------------------------------
    # Fight logic
    # ------------------------------------------------------------------

    def _do_fight_strike(self, target: PeerInfo):
        """Perform one fight strike."""
        pw = self._pw
        if "shooting" in pw.animation.available_states:
            pw.pet.set_state(PetState.SHOOTING)
        elif "slashing" in pw.animation.available_states:
            pw.pet.set_state(PetState.SLASHING)
        else:
            pw.pet.set_state(PetState.INTERACTING)

        pw._say(get_line("peer_attack", pw.pet.name, peer_name=target.display_name))
        pw._peer_discovery.send_event(target.pid, "fight_strike",
                                      {"step": self._fight_step})

        # Initiator resolves the fight after the final strike (step 2)
        if self._fight_role == "initiator" and self._fight_step >= 2:
            self._stop_fight_timer()
            self._fight_timer = QTimer()
            self._fight_timer.setSingleShot(True)
            self._fight_timer.timeout.connect(self._resolve_fight)
            self._fight_timer.start(1500)
        else:
            # Wait for the other side to strike back
            pw._temp_state_timer.start(1500)

    def _next_fight_strike(self):
        """Continue the fight with the next strike (called by _fight_timer)."""
        pw = self._pw
        if pw.pet.state in (PetState.DRAGGED, PetState.FALLING):
            self._reset_fight()
            return

        # Look up current target by stored PID
        peers = pw._peer_discovery.get_peers()
        target = None
        for p in peers:
            if p.pid == self._fight_target_pid:
                target = p
                break

        if target is None:
            # Target disappeared mid-fight
            self._reset_fight()
            pw.pet.set_state(PetState.IDLE)
            return

        self._do_fight_strike(target)

    def _stop_fight_timer(self):
        """Stop and clean up the fight timer."""
        if self._fight_timer is not None:
            self._fight_timer.stop()
            self._fight_timer.deleteLater()
            self._fight_timer = None

    def _reset_fight(self):
        """Reset all fight state."""
        self._stop_fight_timer()
        self._fight_target_pid = 0
        self._fight_step = 0
        self._fight_role = None

    def _resolve_fight(self):
        """Determine the fight outcome."""
        pw = self._pw
        won = random.random() < 0.5
        peers = pw._peer_discovery.get_peers()
        target_name = "???"
        for p in peers:
            if p.pid == self._fight_target_pid:
                target_name = p.display_name
                break

        if won:
            pw.pet.set_state(PetState.HAPPY)
            pw._say(get_line("peer_fight_win", pw.pet.name, peer_name=target_name))
            pw._peer_discovery.send_event(self._fight_target_pid, "fight_result",
                                          {"winner": "source"})
        else:
            pw.pet.set_state(PetState.DYING)
            pw._say(get_line("peer_fight_lose", pw.pet.name, peer_name=target_name))
            pw._peer_discovery.send_event(self._fight_target_pid, "fight_result",
                                          {"winner": "target"})
        pw._temp_state_timer.start(3000)
        self._reset_fight()

    # ------------------------------------------------------------------
    # Incoming event reactions
    # ------------------------------------------------------------------

    def on_event_received(self, event: PeerEvent):
        """Dispatch an incoming event from another Jacky."""
        handler = getattr(self, f"_react_to_{event.type}", None)
        if handler:
            handler(event)
        else:
            log.warning("Unknown peer event type: %s", event.type)

    def _get_source_name(self, event: PeerEvent) -> str:
        """Get the display name of the event source peer."""
        peers = self._pw._peer_discovery.get_peers()
        for p in peers:
            if p.pid == event.source_pid:
                return p.display_name
        return "???"

    def _react_to_greet(self, event: PeerEvent):
        pw = self._pw
        name = self._get_source_name(event)
        # Turn toward the greeter
        peers = pw._peer_discovery.get_peers()
        for p in peers:
            if p.pid == event.source_pid:
                pw.pet.direction = 1 if p.x > pw.x() else -1
                break
        pw.pet.set_state(PetState.HAPPY)
        pw._say(get_line("peer_greet_response", pw.pet.name, peer_name=name))
        pw._temp_state_timer.start(2500)

    def _react_to_attack(self, event: PeerEvent):
        pw = self._pw
        name = self._get_source_name(event)
        pw.pet.set_state(PetState.HURT)
        pw._say(get_line("peer_hurt", pw.pet.name, peer_name=name))
        pw._temp_state_timer.start(2000)

        # 30% chance to counterattack
        if random.random() < 0.3:
            QTimer.singleShot(2500, lambda: self._counterattack(event.source_pid, name))

    def _counterattack(self, target_pid: int, target_name: str):
        """Automatic counterattack after being attacked."""
        pw = self._pw
        if pw.pet.state in (PetState.DRAGGED, PetState.FALLING):
            return
        if "shooting" in pw.animation.available_states:
            pw.pet.set_state(PetState.SHOOTING)
        elif "slashing" in pw.animation.available_states:
            pw.pet.set_state(PetState.SLASHING)
        else:
            pw.pet.set_state(PetState.INTERACTING)
        pw._say(get_line("peer_attack", pw.pet.name, peer_name=target_name))
        pw._peer_discovery.send_event(target_pid, "attack")
        pw._temp_state_timer.start(2000)

    def _react_to_chase(self, event: PeerEvent):
        """Flee from the chaser."""
        pw = self._pw
        name = self._get_source_name(event)
        pw._say(get_line("peer_flee", pw.pet.name, peer_name=name))

        # Run in the opposite direction from the chaser
        peers = pw._peer_discovery.get_peers()
        for p in peers:
            if p.pid == event.source_pid:
                flee_dir = -1 if p.x > pw.x() else 1
                pw.pet.direction = flee_dir
                pw.movement._direction = flee_dir
                break

        if "run" in pw.animation.available_states:
            pw.pet.set_state(PetState.RUNNING)
        else:
            pw.pet.set_state(PetState.WALKING)
        pw.movement.pick_random_target()

    def _react_to_dance(self, event: PeerEvent):
        pw = self._pw
        name = self._get_source_name(event)
        pw.pet.set_state(PetState.HAPPY)
        pw._say(get_line("peer_dance_response", pw.pet.name, peer_name=name))
        pw._temp_state_timer.start(4000)

    def _react_to_fight(self, event: PeerEvent):
        """Received a fight initiation — prepare as responder."""
        pw = self._pw
        name = self._get_source_name(event)
        self._fight_target_pid = event.source_pid
        self._fight_role = "responder"
        self._fight_step = 0
        pw.pet.set_state(PetState.HURT)
        pw._say(get_line("peer_hurt", pw.pet.name, peer_name=name))
        pw._temp_state_timer.start(1500)

    def _react_to_fight_strike(self, event: PeerEvent):
        """Received a fight strike — show hurt and strike back if it's our turn."""
        pw = self._pw
        name = self._get_source_name(event)
        step = event.data.get("step", 0)
        pw.pet.set_state(PetState.HURT)
        pw._say(get_line("peer_hurt", pw.pet.name, peer_name=name))

        # Responder strikes back after initiator's turn (even steps < 2)
        if self._fight_role == "responder" and step % 2 == 0 and step < 2:
            self._fight_step = step + 1
            self._stop_fight_timer()
            self._fight_timer = QTimer()
            self._fight_timer.setSingleShot(True)
            self._fight_timer.timeout.connect(self._next_fight_strike)
            self._fight_timer.start(1500)
        # Initiator received responder's strike (odd step) — continue attacking
        elif self._fight_role == "initiator" and step % 2 == 1:
            self._fight_step = step + 1
            self._stop_fight_timer()
            self._fight_timer = QTimer()
            self._fight_timer.setSingleShot(True)
            self._fight_timer.timeout.connect(self._next_fight_strike)
            self._fight_timer.start(1500)
        else:
            # Final strike received or not in an active fight
            pw._temp_state_timer.start(1500)

    def _react_to_fight_result(self, event: PeerEvent):
        """The fight initiator sent the result."""
        pw = self._pw
        name = self._get_source_name(event)
        winner = event.data.get("winner", "source")
        if winner == "target":
            # We won!
            pw.pet.set_state(PetState.HAPPY)
            pw._say(get_line("peer_fight_win", pw.pet.name, peer_name=name))
        else:
            # We lost
            pw.pet.set_state(PetState.HURT)
            pw._say(get_line("peer_fight_lose", pw.pet.name, peer_name=name))
        pw._temp_state_timer.start(3000)

    # ------------------------------------------------------------------
    # Peer lifecycle callbacks
    # ------------------------------------------------------------------

    def on_peer_joined(self, peer: PeerInfo):
        """React to a new peer appearing."""
        pw = self._pw
        if pw._silent_mode:
            return
        pw._say(get_line("peer_discovered", pw.pet.name, peer_name=peer.display_name))

        # Update window awareness to exclude this peer's HWND
        pw._window_awareness.set_peer_pids(pw._peer_discovery.get_peer_pids())

    def on_peer_left(self, peer: PeerInfo):
        """React to a peer disappearing."""
        pw = self._pw

        # Stop any ongoing interactions with this peer
        if self._walk_to_peer and self._walk_to_peer.pid == peer.pid:
            self._walk_to_peer = None
            self._walk_action = None
        if self._chase_timer and hasattr(self, '_chase_target_pid') and self._chase_target_pid == peer.pid:
            self._stop_chase()
        if self._fight_target_pid == peer.pid:
            self._reset_fight()

        # Update window awareness
        pw._window_awareness.set_peer_pids(pw._peer_discovery.get_peer_pids())

        if pw._silent_mode:
            return
        pw._say(get_line("peer_left", pw.pet.name, peer_name=peer.display_name))
