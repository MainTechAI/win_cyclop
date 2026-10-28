"""Cyclop's idle life: short scripted "acts" chosen by mood, energy and liveliness.

An act is a list of beats. Each beat lasts a moment and says where the eye looks
and what its body does (lids, tilt, hop, squash, zoom, iris spin, sonar). The
engine picks the next act when the pointer has been still for a short while,
weighting the choice by how much energy Cyclop has left: lively antics when it is
fresh, yawns and dozing when it has been left alone for long, or late at night.

Everything here is plain Python so it can be tested without a display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import random

# Look specifications used by beats:
#   ("rel", gx, gy)       gaze offset in eye space, x right, y up, roughly [-0.42, 0.42]
#   ("screen", fx, fy)    a point on the screen as fractions of its width and height
#   ("cursor",)           the mouse pointer
#   ("away",)             the opposite side from the pointer
#   ("roll", turns)       roll the eye around in a full circle during the beat


@dataclass
class Beat:
    duration: float
    look: tuple | None = None
    open: float | None = None      # lid openness override (1 = wide open)
    tilt: float | None = None      # head tilt in degrees
    hop: float = 0.0               # upward impulse at the start of the beat (px/s)
    squash: float = 0.0            # squash (+) or stretch (-) impulse
    zoom: float | None = None      # scale the orb (1 = normal)
    spin: float | None = None      # iris spin speed
    ping: bool = False             # red sonar pulse at the start of the beat
    mark: bool = False             # sonar mark on the screen where it looks
    sweep: bool = False            # radar sweep around the eye
    glow: float = 0.0              # extra glow during the beat
    pupil: float | None = None     # pupil size override (1 = normal)


@dataclass
class Act:
    name: str
    beats: list[Beat] = field(default_factory=list)

    @property
    def duration(self):
        return sum(beat.duration for beat in self.beats)


def _corner_points(rng):
    corners = [(0.06, 0.12), (0.94, 0.12), (0.94, 0.9), (0.06, 0.9), (0.5, 0.55)]
    rng.shuffle(corners)
    return corners[:rng.randint(3, 4)]


def act_patrol(rng):
    beats = [Beat(0.2, ("rel", 0.0, 0.0), sweep=True)]
    for fx, fy in _corner_points(rng):
        beats.append(Beat(0.75, ("screen", fx, fy), ping=True, mark=True, sweep=True))
    beats.append(Beat(0.4, ("cursor",)))
    return Act("patrol", beats)


def act_hunt(rng):
    spot = ("screen", rng.uniform(0.1, 0.9), rng.uniform(0.25, 0.9))
    return Act("hunt", [
        Beat(0.5, spot, open=0.75, ping=True),
        Beat(1.1, spot, open=0.55, tilt=rng.choice((-8, 8)), mark=True, pupil=0.7, glow=0.2),
        Beat(0.35, spot, open=1.0, hop=95, squash=-2.5, ping=True, mark=True, pupil=1.25),
        Beat(0.5, ("cursor",), open=0.85),
    ])


def act_peer(rng):
    tilt = rng.choice((-1, 1)) * rng.uniform(8, 13)
    return Act("peer", [
        Beat(0.45, ("cursor",), tilt=tilt * 0.5, zoom=1.06),
        Beat(1.4, ("cursor",), tilt=tilt, zoom=1.14, pupil=1.35, open=1.0),
        Beat(0.4, ("cursor",), open=0.15),          # slow, curious blink
        Beat(0.5, ("cursor",), tilt=0, zoom=1.0),
    ])


def act_double_take(rng):
    return Act("double_take", [
        Beat(0.9, ("away",), open=0.8),
        Beat(0.12, ("away",)),
        Beat(0.55, ("cursor",), open=1.0, hop=120, squash=-2.2, pupil=0.75, zoom=1.08),
        Beat(0.5, ("cursor",), zoom=1.0),
    ])


def act_nod(rng):
    beats = []
    for _ in range(2):
        beats += [Beat(0.22, ("rel", 0.0, -0.26), tilt=0), Beat(0.22, ("rel", 0.0, 0.12))]
    beats.append(Beat(0.3, ("cursor",)))
    return Act("nod", beats)


def act_shake(rng):
    beats = []
    for _ in range(3):
        beats += [Beat(0.14, ("rel", -0.3, 0.0), tilt=-4), Beat(0.14, ("rel", 0.3, 0.0), tilt=4)]
    beats.append(Beat(0.3, ("cursor",), tilt=0))
    return Act("shake", beats)


def act_roll(rng):
    return Act("roll", [
        Beat(1.5, ("roll", rng.choice((-1, 1))), open=0.9, spin=6),
        Beat(0.3, ("rel", 0.0, 0.0), open=0.1),
        Beat(0.3, ("cursor",), open=1.0),
    ])


def act_stretch(rng):
    return Act("stretch", [
        Beat(0.55, ("rel", 0.0, 0.3), open=0.35, squash=-3.5, tilt=-6),
        Beat(0.45, ("rel", 0.0, 0.3), open=0.25, squash=3.0, tilt=6),
        Beat(0.4, ("cursor",), open=1.0, ping=True),
    ])


def act_spin(rng):
    return Act("spin", [
        Beat(1.3, ("rel", 0.0, 0.05), spin=16, glow=0.35, open=0.8, pupil=0.7),
        Beat(0.3, ("cursor",), ping=True, pupil=1.2),
    ])


def act_yawn(rng):
    return Act("yawn", [
        Beat(0.6, ("rel", 0.0, 0.2), open=0.5, squash=-1.5),
        Beat(1.0, ("rel", 0.0, 0.25), open=0.05, squash=-2.0, tilt=5),
        Beat(0.8, ("rel", 0.0, -0.1), open=0.45, tilt=0),
    ])


def act_doze(rng):
    return Act("doze", [
        Beat(2.2, ("rel", 0.0, -0.2), open=0.12),
        Beat(0.18, ("rel", 0.0, -0.2), open=0.0),
        Beat(0.45, ("cursor",), open=1.0, hop=70, pupil=0.75),   # jolts awake
    ])


ACTS = {
    "patrol": act_patrol, "hunt": act_hunt, "peer": act_peer, "double_take": act_double_take,
    "nod": act_nod, "shake": act_shake, "roll": act_roll, "stretch": act_stretch,
    "spin": act_spin, "yawn": act_yawn, "doze": act_doze,
}

# Which acts fit which energy level; weights are relative.
ENERGETIC = {"patrol": 4, "hunt": 4, "peer": 3, "double_take": 3, "roll": 2, "spin": 2, "nod": 1, "shake": 1, "stretch": 1}
TIRED = {"yawn": 3, "doze": 3, "stretch": 2, "nod": 1, "peer": 1}

LIVELINESS = {
    # (pointer stillness before acting, pause between acts min, max)
    "Calm": (6.0, 7.0, 15.0),
    "Lively": (2.5, 2.5, 6.0),
    "Playful": (1.2, 0.8, 3.0),
}


def night(now: datetime | None = None) -> bool:
    hour = (now or datetime.now()).hour
    return hour >= 23 or hour < 6


class Engine:
    """Chooses and plays acts. Call ``update`` every frame with the current time."""

    def __init__(self, liveliness="Lively", rng=None):
        self.rng = rng or random.Random()
        self.liveliness = liveliness if liveliness in LIVELINESS else "Lively"
        self.energy = 1.0
        self.act: Act | None = None
        self.act_started = 0.0
        self.beat_index = -1
        self.beat_started = 0.0
        self.next_act = 0.0
        self.history: list[str] = []
        self.started_beats: list[Beat] = []   # beats that began since the last update (for impulses)

    # ---------------------------------------------------------- energy
    def refresh(self, amount=0.35):
        """Something happened (pointer, typing, clicks): perk up."""
        self.energy = min(1.0, self.energy + amount)

    def drain(self, dt, is_night=False):
        rate = 1 / 240 * (2.0 if is_night else 1.0)   # ~4 minutes from fresh to sleepy
        self.energy = max(0.0, self.energy - rate * dt)

    @property
    def sleepy(self):
        return self.energy < 0.08

    @property
    def tired(self):
        return self.energy < 0.3

    # ---------------------------------------------------------- acts
    def idle_after(self):
        return LIVELINESS[self.liveliness][0]

    def choose(self):
        table = TIRED if self.tired else ENERGETIC
        names = list(table)
        weights = [table[name] for name in names]
        # Avoid repeating the last two acts.
        recent = set(self.history[-2:])
        weights = [w * (0.15 if name in recent else 1.0) for name, w in zip(names, weights)]
        name = self.rng.choices(names, weights)[0]
        return ACTS[name](self.rng)

    def start(self, act: Act, now):
        self.act, self.act_started, self.beat_index, self.beat_started = act, now, -1, now
        self.history = (self.history + [act.name])[-8:]
        self._advance(now)

    def stop(self, now=None):
        if self.act is not None and now is not None:
            self.schedule_next(now)
        self.act = None
        self.beat_index = -1

    def schedule_next(self, now):
        _, low, high = LIVELINESS[self.liveliness]
        if self.tired:
            low, high = low * 1.6, high * 1.6
        self.next_act = now + self.rng.uniform(low, high)

    def _advance(self, now):
        self.beat_index += 1
        self.beat_started = now
        if self.act is not None and self.beat_index < len(self.act.beats):
            self.started_beats.append(self.act.beats[self.beat_index])

    def update(self, now, idle_for, allowed=True):
        """Advance the current act, or start one when the pointer has rested long enough.

        Returns the active beat (or None) and how far through it we are (0..1).
        """
        self.started_beats = []
        if self.act is not None and not allowed:
            self.stop(now)
        if self.act is None and allowed and not self.sleepy and idle_for >= self.idle_after() and now >= self.next_act:
            self.start(self.choose(), now)
        if self.act is None:
            return None, 0.0
        beat = self.act.beats[self.beat_index]
        while now - self.beat_started >= beat.duration:
            started = self.beat_started + beat.duration
            self._advance(started)
            if self.beat_index >= len(self.act.beats):
                self.stop(now)
                return None, 0.0
            beat = self.act.beats[self.beat_index]
        progress = (now - self.beat_started) / beat.duration if beat.duration else 1.0
        return beat, min(1.0, max(0.0, progress))


def resolve_look(look, progress, cursor_rel, screen_rel):
    """Turn a beat's look spec into a gaze offset.

    ``cursor_rel`` is the gaze towards the pointer; ``screen_rel(fx, fy)`` converts
    a screen fraction into a gaze offset.
    """
    if look is None:
        return None
    kind = look[0]
    if kind == "rel":
        return (look[1], look[2])
    if kind == "cursor":
        return cursor_rel
    if kind == "away":
        return (-cursor_rel[0] * 0.9 or 0.3, 0.18)
    if kind == "screen":
        return screen_rel(look[1], look[2])
    if kind == "roll":
        angle = look[1] * progress * 2 * math.pi + math.pi / 2
        return (0.36 * math.cos(angle), 0.28 * math.sin(angle))
    return None


class Wiggle:
    """Detects the pointer being shaken back and forth (to make Cyclop dizzy)."""

    def __init__(self, reversals=6, window=1.6):
        self.reversals_needed = reversals
        self.window = window
        self.direction = 0
        self.reversals: list[float] = []

    def feed(self, now, dx, speed):
        if abs(dx) < 6 or speed < 600:
            return False
        direction = 1 if dx > 0 else -1
        if self.direction and direction != self.direction:
            self.reversals = [t for t in self.reversals if now - t < self.window] + [now]
        self.direction = direction
        if len(self.reversals) >= self.reversals_needed:
            self.reversals.clear()
            return True
        return False
