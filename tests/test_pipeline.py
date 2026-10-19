import numpy as np
from fakes import FakeBundle
from vietvoice.pipeline import Pipeline
from vietvoice.timeline import SpeakerTimeline, merge_tokens


def test_final_waits_and_emits_once():
    p = Pipeline(FakeBundle(), segment_seconds=0.3)
    audio = np.zeros(1600, dtype="<i2").tobytes()
    events = [e for _ in range(3) for e in p.feed(audio)]
    assert not any(e["type"] == "final" for e in events)
    events += [e for _ in range(2) for e in p.feed(audio)]
    finals = [e for e in events if e["type"] == "final"]
    assert len(finals) == 1
    assert finals[0]["tokens"][0]["speaker_id"] == "speaker_1"
    tail = p.finish()
    assert [e["segment_id"] for e in tail if e["type"] == "final"] == [1]
    assert tail[-1]["audio_seconds"] == 0.5
    assert p.finish() == []


def test_overlap_unknown_and_pruning():
    t = SpeakerTimeline()
    frames = np.zeros((200, 8), dtype=np.float32)
    frames[:50, :2] = 0.95
    frames[100:, 1] = 0.99
    t.append(frames)
    assert t.label(0, 0.4) == {"speaker_id":None, "speaker_score":1.0, "overlap":True}
    assert t.label(0.6, 0.8)["speaker_id"] is None
    t.prune(1)
    tokens = merge_tokens({"text":"CHÀO", "tokens":["▁CHÀO"], "timestamps":[0.2]}, 1, 2, t)
    assert tokens[0]["speaker_id"] == "speaker_2"
    assert tokens[0]["start"] == 1.2
    assert t.through == 2


def test_empty_session_and_isolation():
    a, b = Pipeline(FakeBundle()), Pipeline(FakeBundle())
    a.feed(bytes(3200))
    assert b.samples == 0 and a.diar is not b.diar
    assert b.finish()[-1]["audio_seconds"] == 0


def test_vad_rejects_non_speech_before_refinement():
    p = Pipeline(FakeBundle())
    p.online.finish_speech = lambda: False
    p.bundle.refine = lambda _: (_ for _ in ()).throw(AssertionError("Must not decode silence"))
    p.feed(bytes(3200))
    assert p.finish()[0]["text"] == ""
