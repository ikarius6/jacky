# Animation States for Jacky

Reference for the restructured PetState enum, sprite folder mapping, and animation fallback system.

## PetState Enum (15 states)

| PetState | Primary Animation | Fallbacks | Usage |
|---|---|---|---|
| `IDLE` | `idle` | — | Default state |
| `TALKING` | `talk` | — | Speech bubble active |
| `WALKING` | `walk` | — | Movement |
| `RUNNING` | `run` | — | Fast movement, chase |
| `HURT` | `hurt` | — | Peer attacks, fight strikes |
| `HAPPY` | `happy` | `kick` | Greet, fight win |
| `FALLING` | `falling` | — | Gravity (airborne after drag) |
| `JUMPING` | `jump_loop` | — | Reserved for future use |
| `ATTACKING` | `shooting` | `slashing` → `kick` | Attack, fight, minimize, topple, push, shake, knock, resize, tidy, screen interact |
| `EATING` | `happy` | `kick` | Fed from context menu |
| `DRAGGED` | `drag` | — | User drag |
| `DYING` | `dying` | — | Losing a fight |
| `DANCE` | `happy` | `kick` | Peer dance |
| `GETTING_PET` | `happy` | `kick` | Left-click pet reaction |
| `PEEKING` | `idle` | — | Peek behind window |

## DIR_TO_STATES (character.py)

Maps sprite subdirectory names → internal animation state names loaded by `AnimationController`.

| Sprite Folder | Animation States | Notes |
|---|---|---|
| `Idle` | `idle` | Default |
| `Idle Blinking` | `idle_blink`, `talk` | `idle_blink` loaded but unused (no PetState maps to it) |
| `Walking` | `walk` | |
| `Running` | `run` | |
| `Hurt` | `hurt`, `drag` | |
| `Kicking` | `kick`, `happy` | Fallback for ATTACKING and several other states |
| `Dying` | `dying` | |
| `Falling Down` | `falling` | Gravity system |
| `Jump Loop` | `jump_loop` | Reserved |
| `Shooting` | `shooting` | Primary ATTACKING animation |
| `Slashing` | `slashing` | First fallback for ATTACKING |

## Animation Fallback System

Defined in `ANIMATION_FALLBACKS` (pet.py), resolved in `_on_anim_tick` (pet_window.py):

```python
ANIMATION_FALLBACKS = {
    "shooting": ["slashing", "kick"],  # ATTACKING chain
    "happy":    ["kick"],              # HAPPY/DANCE/GETTING_PET/EATING chain
}
```

When the primary animation for a PetState is not available in the sprite pack, fallbacks are tried in order. This eliminates per-call-site branching.
