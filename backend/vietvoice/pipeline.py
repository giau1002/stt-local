from collections import deque
import time
import numpy as np
from .models import SR
from .timeline import SpeakerTimeline, group_tokens, merge_tokens


class Pipeline:
    def __init__(self, bundle, segment_seconds=12):
        self.bundle = bundle
        self.online, self.diar = bundle.create()
        self.timeline = SpeakerTimeline(self.diar.frame_seconds)
        self.segment_seconds = segment_seconds
        self.audio, self.pending = [], deque()
        self.samples = self.start_sample = self.segment_id = 0
        self.last_partial = ""
        self.closed = False
        self.compute_seconds = 0.0

    def _close_segment(self):
        if not self.audio:
            return
        audio = np.concatenate(self.audio)
        if self.online.finish_speech():
            lo, hi = self.online.speech_bounds(len(audio))
            result = self.bundle.refine(audio[lo:hi])
            result["timestamps"] = [t + lo / SR for t in result["timestamps"]]
        else:
            result = {"text": "", "tokens": [], "timestamps": []}
        self.pending.append((self.segment_id, self.start_sample / SR, self.samples / SR, result))
        self.segment_id += 1
        self.start_sample = self.samples
        self.audio.clear()
        self.online.reset()
        self.last_partial = ""

    def _emit(self, force=False):
        events = []
        while self.pending:
            sid, start, end, result = self.pending[0]
            if not force and self.timeline.through + 0.02 < end:
                break
            self.pending.popleft()
            tokens = merge_tokens(result, start, end, self.timeline)
            events.append({"type": "final", "segment_id": sid, "is_final": True, "start": start, "end": end,
                           "text": result["text"].strip(), "tokens": tokens, "turns": group_tokens(tokens)})
        self.timeline.prune(self.pending[0][1] if self.pending else self.start_sample / SR)
        return events

    def feed(self, pcm):
        if self.closed:
            raise ValueError("Session is closed")
        begin = time.monotonic()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self.audio.append(audio)
        self.samples += len(audio)
        self.timeline.append(self.diar.feed(audio))
        text, endpoint = self.online.feed(audio)
        events = []
        if text != self.last_partial:
            self.last_partial = text
            events.append({"type": "partial", "segment_id": self.segment_id, "text": text,
                           "start": self.start_sample / SR, "end": self.samples / SR, "is_final": False})
        if endpoint or self.samples - self.start_sample >= int(self.segment_seconds * SR):
            self._close_segment()
        events += self._emit()
        self.compute_seconds += time.monotonic() - begin
        return events

    def finish(self):
        if self.closed:
            return []
        begin = time.monotonic()
        self.closed = True
        self._close_segment()
        self.timeline.append(self.diar.feed(np.empty(0, dtype=np.float32), final=True))
        events = self._emit(force=True)
        self.compute_seconds += time.monotonic() - begin
        events.append({"type": "done", "audio_seconds": self.samples / SR,
                       "compute_seconds": round(self.compute_seconds, 3),
                       "rtf": round(self.compute_seconds / max(self.samples / SR, 0.001), 3)})
        return events
