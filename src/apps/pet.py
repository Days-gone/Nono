from __future__ import annotations

import time
from enum import Enum

from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples

BLINK_EVERY = 3.5  # seconds between blinks while resting
BLINK_FOR = 0.6  # how long one blink keeps the eyes shut (2 repaints)
HAPPY_FOR = 6.0  # how long a finished reply keeps it beaming
SULK_FOR = 5.0  # how long a failed call keeps it wailing
DOZE_AFTER = 180.0  # seconds of silence before it dozes off
HAPPY_TICK = 0.6  # eye wiggle pace while beaming
WAIL_TICK = 0.4  # eye squeeze pace while wailing
SLEEP_TICK = 1.5  # "z Z z" alternation pace while dozing
REFRESH_INTERVAL = 0.3  # prompt repaint period; fast enough that no frame above is skipped

_BALL_COLOR = "ansibrightcyan bold"
_EYE_COLOR = "ansiwhite bold"
_STATUS_COLOR = "ansibrightblack"
_PROMPT_COLOR = "ansicyan bold"

_BALL_TOP = " ▄▄▄▄▄▄"
_BALL_BOTTOM = " ▀▀▀▀▀▀"


class Mood(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    HAPPY = "happy"
    SLEEPY = "sleepy"
    SULK = "sulk"


# One frame = left eye, right eye, status bubble. All frames share one width
# so the block on screen never jitters; the ball outline is drawn by ``block``.
_Frame = tuple[str, str, str]
_FACES: dict[Mood, tuple[_Frame, _Frame]] = {
    Mood.IDLE: (("▮", "▮", "在等你说话"), ("▬", "▬", "在等你说话")),
    Mood.LISTENING: (("▮", "▮", "在认真听…"), ("▬", "▬", "在认真听…")),
    Mood.HAPPY: (("▂", "▂", "开心！"), ("▮", "▮", "开心♪")),
    Mood.SLEEPY: (("▬", "▬", "z Z z …"), ("▬", "▬", "… Z z Z")),
    Mood.SULK: (("╲", "╱", "呜…出错了"), ("▬", "▬", "呜…出错了")),
}


class NonoPet:
    """A tiny desk pet living in the block above the input line.

    The CLI pokes it at key moments (``observe``/``cheer``/``sulk``); in
    between it blinks, perks up while the user types, and dozes when ignored.
    ``render`` serves as the PromptSession message: all lines but the last
    are drawn above the input line, and ``refresh_interval`` keeps it moving.
    """

    def __init__(self) -> None:
        self._last_seen = time.monotonic()
        self._happy_until = 0.0
        self._sulk_until = 0.0

    def observe(self) -> None:
        """The user did something: submitted a line, picked a session."""
        self._last_seen = time.monotonic()

    def cheer(self) -> None:
        """A reply finished well; beam for a little while."""
        now = time.monotonic()
        self._last_seen = now
        self._happy_until = now + HAPPY_FOR

    def sulk(self) -> None:
        """A call failed; wail for a little while."""
        now = time.monotonic()
        self._last_seen = now
        self._sulk_until = now + SULK_FOR

    def block(self) -> StyleAndTextTuples:
        """The pet block alone -- for the startup banner and friends."""
        left, right, status = self._frame(self._mood())
        return [
            (_BALL_COLOR, _BALL_TOP),
            ("", "\n"),
            (_BALL_COLOR, "█ "),
            (_EYE_COLOR, left),
            ("", "  "),
            (_EYE_COLOR, right),
            (_BALL_COLOR, " █"),
            (_STATUS_COLOR, "  " + status),
            ("", "\n"),
            (_BALL_COLOR, _BALL_BOTTOM),
        ]

    def render(self) -> StyleAndTextTuples:
        """The prompt_toolkit message: pet block + prompt, lines split by \\n."""
        return self.block() + [
            ("", "\n"),
            (_PROMPT_COLOR, "Nono > "),
        ]

    def _mood(self) -> Mood:
        now = time.monotonic()
        if now < self._sulk_until:
            return Mood.SULK
        if now < self._happy_until:
            return Mood.HAPPY
        if self._user_typing():
            # Typing counts as being seen, or a long message would put the
            # pet to sleep mid-sentence.
            self._last_seen = now
            return Mood.LISTENING
        if now - self._last_seen >= DOZE_AFTER:
            return Mood.SLEEPY
        return Mood.IDLE

    def _frame(self, mood: Mood) -> _Frame:
        main, alt = _FACES[mood]
        now = time.monotonic()
        if mood is Mood.HAPPY:
            return alt if int(now // HAPPY_TICK) % 2 else main
        if mood is Mood.SULK:
            return alt if int(now // WAIL_TICK) % 2 else main
        if mood is Mood.SLEEPY:
            return alt if int(now // SLEEP_TICK) % 2 else main
        if now % BLINK_EVERY < BLINK_FOR:
            return alt
        return main

    def _user_typing(self) -> bool:
        """Whether the input buffer already holds unsubmitted text."""
        try:
            app = get_app()
            if getattr(app, "is_done", False):
                return False
            buffer = app.layout.get_buffer_by_name("DEFAULT_BUFFER")
            return buffer is not None and bool(buffer.text)
        except Exception:
            # Not rendered inside a running prompt application (e.g. banner).
            return False
