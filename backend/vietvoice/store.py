import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, create_engine, select, update


class Store:
    def __init__(self, url):
        if url.startswith("sqlite:///") and not url.endswith(":memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, pool_pre_ping=True)
        meta = MetaData()
        self.sessions = Table("sessions", meta, Column("id", String(36), primary_key=True),
                              Column("title", String(120)), Column("created_at", String(40)),
                              Column("status", String(20)), Column("duration", Float), Column("speakers", Text))
        self.segments = Table("segments", meta, Column("session_id", String(36), primary_key=True),
                             Column("segment_id", Integer, primary_key=True), Column("payload", Text))
        meta.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(update(self.sessions).where(self.sessions.c.status == "recording").values(status="interrupted"))

    def create(self, sid, title):
        with self.engine.begin() as conn:
            conn.execute(self.sessions.insert().values(id=sid, title=title, duration=0, speakers="{}",
                         created_at=datetime.now(timezone.utc).isoformat(), status="recording"))

    def final(self, sid, event):
        with self.engine.begin() as conn:
            conn.execute(self.segments.insert().values(session_id=sid, segment_id=event["segment_id"],
                                                      payload=json.dumps(event, ensure_ascii=False)))

    def finish(self, sid, duration, status):
        with self.engine.begin() as conn:
            conn.execute(update(self.sessions).where(self.sessions.c.id == sid).values(duration=duration, status=status))

    def list(self):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(self.sessions).order_by(self.sessions.c.created_at.desc()).limit(100)).mappings()]

    def get(self, sid):
        with self.engine.connect() as conn:
            row = conn.execute(select(self.sessions).where(self.sessions.c.id == sid)).mappings().first()
            if not row:
                return None
            result = dict(row)
            result["speakers"] = json.loads(result["speakers"])
            result["segments"] = [json.loads(r[0]) for r in conn.execute(
                select(self.segments.c.payload).where(self.segments.c.session_id == sid).order_by(self.segments.c.segment_id))]
            return result

    def rename(self, sid, speaker_id, name):
        with self.engine.begin() as conn:
            raw = conn.execute(select(self.sessions.c.speakers).where(self.sessions.c.id == sid).with_for_update()).scalar_one_or_none()
            if raw is None:
                return False
            names = json.loads(raw)
            names[speaker_id] = name
            conn.execute(update(self.sessions).where(self.sessions.c.id == sid).values(speakers=json.dumps(names, ensure_ascii=False)))
            return True


def export_transcript(session, fmt):
    def speaker(key):
        return session["speakers"].get(key, key or "Chưa xác định")
    turns = [t for s in session["segments"] for t in s["turns"]]
    if fmt == "json":
        return json.dumps(session, ensure_ascii=False, indent=2), "application/json"
    if fmt == "txt":
        return "\n".join(f'[{t["start"]:.2f}s] {speaker(t["speaker_id"])}: {t["text"]}' for t in turns), "text/plain"
    def stamp(seconds):
        ms = round(seconds * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    return "\n\n".join(f'{i}\n{stamp(t["start"])} --> {stamp(t["end"])}\n{speaker(t["speaker_id"])}: {t["text"]}'
                       for i, t in enumerate(turns, 1)), "application/x-subrip"
