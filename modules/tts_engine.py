"""
Module 2: Acoustic & Temporal Metadata Engine
==============================================
Uses edge-tts (Microsoft Edge TTS via WebSocket) to synthesize speech
and capture word-boundary events that the service emits alongside the
audio stream.

Key output: List[WordBoundary] — the bridge between text-space and
time-space that Module 3 needs to drive the highlight cursor.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

import edge_tts


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class WordBoundary:
    """One atom of the text↔time mapping."""

    word: str
    start_time_ms: int
    end_time_ms: int
    # character offsets into the *original* plain-text string
    text_index_start: int = 0
    text_index_end: int = 0


@dataclass
class TTSResult:
    """Everything produced by a single synthesis run."""

    audio_path: str  # path to the generated mp3 file
    boundaries: List[WordBoundary] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TTSEngine:
    """
    Wraps *edge-tts* to produce:
      1.  An MP3 audio file.
      2.  A list of WordBoundary objects with ms-accurate timestamps
          AND character-level offsets into the original text.

    Usage
    -----
        engine = TTSEngine(voice="en-US-GuyNeural", rate="+0%", volume="+0%")
        result: TTSResult = engine.synthesize(plain_text)
        # result.audio_path  -> "…/tts_output.mp3"
        # result.boundaries  -> [WordBoundary(…), …]
    """

    # Default voice — natural, widely available
    DEFAULT_VOICE = "en-US-GuyNeural"

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        rate: str = "+0%",
        volume: str = "+0%",
        output_dir: Optional[str] = None,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume
        # Where to write the mp3; defaults to a temp directory
        self._output_dir = output_dir or tempfile.gettempdir()

    # ------------------------------------------------------------------
    # Public API (synchronous wrapper)
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> TTSResult:
        """Synchronous entry-point — safe to call from any thread."""
        # edge-tts is async-only; run it inside a *new* event-loop so
        # we never collide with an already-running loop (e.g. Tkinter's).
        return asyncio.run(self._synthesize_async(text))

    # ------------------------------------------------------------------
    # Async implementation
    # ------------------------------------------------------------------

    async def _synthesize_async(self, text: str) -> TTSResult:
        communicate = edge_tts.Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )

        import uuid

        audio_filename = f"tts_output_{uuid.uuid4().hex}.mp3"
        audio_path = os.path.join(self._output_dir, audio_filename)
        audio_chunks: list[bytes] = []
        raw_boundaries: List[dict] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                raw_boundaries.append(
                    {
                        "word": chunk["text"],
                        "offset": chunk["offset"],  # 100-ns ticks (timestamp)
                        "duration": chunk["duration"],  # 100-ns ticks
                    }
                )

        # ---- write audio file ----
        with open(audio_path, "wb") as fp:
            for c in audio_chunks:
                fp.write(c)

        # ---- build WordBoundary list with real text-indices ----
        boundaries = self._build_boundaries(text, raw_boundaries)

        # ---- compute total duration ----
        duration_ms = 0
        if boundaries:
            last = boundaries[-1]
            duration_ms = last.end_time_ms

        return TTSResult(
            audio_path=audio_path,
            boundaries=boundaries,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Mapping: edge-tts events → WordBoundary with text offsets
    # ------------------------------------------------------------------

    @staticmethod
    def _build_boundaries(
        original_text: str,
        raw_events: List[dict],
    ) -> List[WordBoundary]:
        """
        edge-tts emits *WordBoundary* events with:
          - offset   : character offset **into the SSML text** (may differ
                       from the plain-text offset if SSML tags are present).
          - duration : in 100-ns ticks (1 tick = 0.0001 ms).
          - text     : the word fragment the service recognised.

        We re-map each word onto the *original plain-text* using a
        greedy forward search so that highlight indices are always correct.
        """
        boundaries: List[WordBoundary] = []
        search_start = 0  # cursor in original_text
        cumulative_ms: float = 0.0

        for evt in raw_events:
            sentence: str = evt["word"].strip()
            ticks_offset: int = evt["offset"]
            ticks_duration: int = evt["duration"]

            start_ms = int(ticks_offset / 10_000)
            end_ms = int((ticks_offset + ticks_duration) / 10_000)

            # Locate *sentence* in original_text starting from search_start
            idx = original_text.find(sentence, search_start)
            if idx == -1:
                # edge-tts occasionally normalises punctuation; fall back
                # to a case-insensitive search
                idx = original_text.lower().find(sentence.lower(), search_start)
            if idx == -1:
                # Still not found — skip this event but keep timeline going
                continue

            # Split sentence into 5-word chunks and interpolate timestamps
            word_matches = list(re.finditer(r"\S+", sentence))
            chunk_size = 5  # Highlight 5 words at a time
            sentence_len = len(sentence)

            for i in range(0, len(word_matches), chunk_size):
                chunk_matches = word_matches[i : i + chunk_size]
                if not chunk_matches:
                    continue

                chunk_start_offset = chunk_matches[0].start()
                chunk_end_offset = chunk_matches[-1].end()

                chunk_text = sentence[chunk_start_offset:chunk_end_offset]

                # Interpolate time based on character positions within the sentence.
                fraction_start = chunk_start_offset / max(1, sentence_len)
                fraction_end = chunk_end_offset / max(1, sentence_len)

                chunk_start_ms = start_ms + int((end_ms - start_ms) * fraction_start)
                chunk_end_ms = start_ms + int((end_ms - start_ms) * fraction_end)

                boundaries.append(
                    WordBoundary(
                        word=chunk_text,
                        start_time_ms=chunk_start_ms,
                        end_time_ms=chunk_end_ms,
                        text_index_start=idx + chunk_start_offset,
                        text_index_end=idx + chunk_end_offset,
                    )
                )

            search_start = idx + sentence_len

        return boundaries

    # ------------------------------------------------------------------
    # Utility: list available voices (handy for the GUI voice picker)
    # ------------------------------------------------------------------

    @staticmethod
    async def _list_voices_async() -> List[dict]:
        voices = await edge_tts.list_voices()
        return voices

    def list_voices(self) -> List[dict]:
        """Return a list of all voices available on the edge-tts service."""
        return asyncio.run(self._list_voices_async())


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample = (
        "The quick brown fox jumps over the lazy dog. "
        "This is a demonstration of real-time word highlighting."
    )
    engine = TTSEngine()
    result = engine.synthesize(sample)

    print(f"Audio saved to: {result.audio_path}")
    print(f"Total duration: {result.duration_ms} ms")
    print(f"Word boundaries ({len(result.boundaries)}):")
    for wb in result.boundaries:
        print(
            f"  [{wb.start_time_ms:>6} – {wb.end_time_ms:>6} ms]  "
            f"chars [{wb.text_index_start}:{wb.text_index_end}]  "
            f'"{wb.word}"'
        )
