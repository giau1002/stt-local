"""Continuous speaker frames; token ends are estimates, not forced alignment."""
import numpy as np


class SpeakerTimeline:
    def __init__(self, frame_seconds=0.01):
        self.frame_seconds = frame_seconds
        self.offset = 0
        self.frames = np.empty((0, 8), dtype=np.float32)

    @property
    def through(self):
        return (self.offset + len(self.frames)) * self.frame_seconds

    def append(self, frames):
        frames = np.asarray(frames, dtype=np.float32)
        if frames.ndim != 2 or frames.shape[1] != 8 or not np.isfinite(frames).all():
            raise ValueError("Invalid diarization output")
        self.frames = np.concatenate((self.frames, frames))

    def prune(self, before):
        n = max(0, min(len(self.frames), int(before / self.frame_seconds) - self.offset))
        self.frames = self.frames[n:]
        self.offset += n

    def label(self, start, end):
        lo = max(0, int(start / self.frame_seconds) - self.offset)
        hi = min(len(self.frames), max(lo + 1, int(np.ceil(end / self.frame_seconds)) - self.offset))
        frames = self.frames[lo:hi]
        if not len(frames):
            return {"speaker_id": None, "speaker_score": 0.0, "overlap": False}
        active = frames >= 0.5
        occupancy = active.mean(axis=0)
        best, second = np.argsort(occupancy)[-2:][::-1]
        overlap = bool((active.sum(axis=1) > 1).mean() >= 0.15)
        certain = occupancy[best] >= 0.45 and occupancy[best] - occupancy[second] >= 0.15 and not overlap
        return {"speaker_id": f"speaker_{best + 1}" if certain else None,
                "speaker_score": round(float(occupancy[best]), 3), "overlap": overlap}


def merge_tokens(result, start, end, timeline):
    pieces, times = result.get("tokens", []), result.get("timestamps", [])
    if not pieces or len(pieces) != len(times):
        if not result.get("text", "").strip():
            return []
        return [{"text": result["text"].strip(), "start": start, "end": end,
                 "timing": "segment", **timeline.label(start, end)}]
    tokens = []
    for i, (piece, timestamp) in enumerate(zip(pieces, times)):
        if piece in ("<blk>", "<blank>", "<s>", "</s>", "<sos/eos>", "<unk>"):
            continue
        t0 = min(end, max(start, start + float(timestamp)))
        t1 = min(end, max(t0 + 0.01, start + float(times[i + 1]) if i + 1 < len(times) else t0 + 0.3))
        tokens.append({"text": piece.replace("▁", " "), "start": round(t0, 3), "end": round(t1, 3),
                       "timing": "rnnt_estimated", **timeline.label(t0, min(t1, t0 + 0.3))})
    return tokens


def group_tokens(tokens):
    groups = []
    for token in tokens:
        if groups and (groups[-1]["speaker_id"], groups[-1]["overlap"]) == (token["speaker_id"], token["overlap"]):
            groups[-1]["text"] += token["text"]
            groups[-1]["end"] = token["end"]
        else:
            groups.append({k: token[k] for k in ("text", "start", "end", "speaker_id", "overlap")})
    for group in groups:
        group["text"] = group["text"].strip()
    return [g for g in groups if g["text"]]
