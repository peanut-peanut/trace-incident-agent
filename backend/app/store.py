from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, select, update
from sqlalchemy.exc import IntegrityError


def now():
    return datetime.now(timezone.utc)


metadata = MetaData()
runs = Table("runs", metadata,
    Column("id", String(36), primary_key=True),
    Column("title", String(160), nullable=False),
    Column("description", Text, nullable=False),
    Column("input", JSON, nullable=False),
    Column("mode", String(12), nullable=False),
    Column("status", String(24), nullable=False),
    Column("report", JSON), Column("evidence", JSON), Column("metrics", JSON),
    Column("error", String(500)), Column("decision", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
events = Table("events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(36), nullable=False, index=True),
    Column("kind", String(40), nullable=False),
    Column("message", String(500), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
tickets = Table("tickets", metadata,
    Column("id", String(36), primary_key=True),
    Column("run_id", String(36), nullable=False, unique=True),
    Column("title", String(160), nullable=False),
    Column("body", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class Store:
    def __init__(self, url):
        self.engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def create(self, data, mode):
        row = {"id": str(uuid4()), "title": data["title"], "description": data["description"], "input": data, "mode": mode, "status": "queued", "created_at": now(), "updated_at": now()}
        with self.engine.begin() as conn:
            conn.execute(runs.insert().values(**row))
        return row["id"]

    def get(self, run_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
            if row is None:
                return None
            out = dict(row)
            ticket = conn.execute(select(tickets).where(tickets.c.run_id == run_id)).mappings().first()
            out["ticket"] = dict(ticket) if ticket else None
            return out

    def list(self):
        with self.engine.connect() as conn:
            return [dict(x) for x in conn.execute(select(runs.c.id, runs.c.title, runs.c.mode, runs.c.status, runs.c.created_at).order_by(runs.c.created_at.desc()).limit(50)).mappings()]

    def patch(self, run_id, **values):
        with self.engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id).values(**values, updated_at=now()))

    def transition(self, run_id, expected, target, **values):
        with self.engine.begin() as conn:
            result = conn.execute(update(runs).where(runs.c.id == run_id, runs.c.status.in_(expected)).values(status=target, **values, updated_at=now()))
            return result.rowcount == 1

    def event(self, run_id, kind, message, payload=None):
        with self.engine.begin() as conn:
            conn.execute(events.insert().values(run_id=run_id, kind=kind, message=message, payload=payload or {}, created_at=now()))

    def get_events(self, run_id):
        with self.engine.connect() as conn:
            return [dict(x) for x in conn.execute(select(events).where(events.c.run_id == run_id).order_by(events.c.id)).mappings()]

    def ticket(self, run_id, decision, report):
        row = {"id": str(uuid4()), "run_id": run_id, "title": decision["title"], "body": {"report": report, "approval_note": decision["note"]}, "created_at": now()}
        try:
            with self.engine.begin() as conn:
                conn.execute(tickets.insert().values(**row))
        except IntegrityError:
            with self.engine.connect() as conn:
                existing = conn.execute(select(tickets).where(tickets.c.run_id == run_id)).mappings().first()
                if existing is None:
                    raise
                row = dict(existing)
        return row["id"]

    def recover(self):
        # 当前只支持单进程，没有多 worker 的租约或心跳。
        with self.engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.status.in_(["queued", "running", "approving"])).values(status="interrupted", error="服务重启，任务已保留；可从最近检查点恢复。", updated_at=now()))
