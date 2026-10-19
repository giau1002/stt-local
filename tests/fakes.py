"""Test doubles: never imported by the production application."""
import numpy as np


class FakeOnline:
    def feed(self, audio):
        return "XIN CHÀO", False

    def reset(self):
        pass

    def finish_speech(self):
        return True

    def speech_bounds(self, total):
        return 0, total


class FakeDiar:
    frame_seconds = 0.01

    def __init__(self):
        self.samples = self.emitted = 0

    def feed(self, audio, final=False):
        self.samples += len(audio)
        through = self.samples // 160 if final else max(0, self.samples // 160 - 20)
        frames = np.zeros((through - self.emitted, 8), dtype=np.float32)
        frames[:, 0] = 0.95
        self.emitted = through
        return frames


class FakeBundle:
    def __init__(self, settings=None):
        pass

    def create(self):
        return FakeOnline(), FakeDiar()

    def refine(self, samples):
        return {"text":"XIN CHÀO", "tokens":["▁XIN", "▁CHÀO"], "timestamps":[0.0, 0.06]}
