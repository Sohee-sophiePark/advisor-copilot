"""Typed trace events, async pub/sub bus, and JSONL sink."""

import asyncio
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class TraceEvent(BaseModel):
    seq: int
    run_id: str
    ts: dt.datetime
    t_ms: int
    type: str
    agent: str
    level: Literal["info", "warn", "error"] = "info"
    payload: dict[str, Any] = {}


class TraceBus:
    """Event list + optional JSONL sink; subscribers get history first, then live events."""

    def __init__(self, run_id: str, sink: Path | None = None) -> None:
        self.run_id, self.sink, self.t0 = run_id, sink, time.monotonic()
        self.events: list[TraceEvent] = []
        self.queues: list[asyncio.Queue[TraceEvent | None]] = []
        self.closed = False

    def emit(
        self, type: str, agent: str, payload: dict[str, Any] | None = None, level: str = "info"
    ) -> TraceEvent:
        event = TraceEvent(
            seq=len(self.events) + 1,
            run_id=self.run_id,
            ts=dt.datetime.now(dt.UTC),
            t_ms=int((time.monotonic() - self.t0) * 1000),
            type=type,
            agent=agent,
            level=level,
            payload=payload or {},
        )
        self.events.append(event)
        if self.sink:
            self.sink.parent.mkdir(parents=True, exist_ok=True)
            with self.sink.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        for q in self.queues:
            q.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue[TraceEvent | None]:
        q: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
        for event in self.events:
            q.put_nowait(event)
        if self.closed:
            q.put_nowait(None)
        self.queues.append(q)
        return q

    def close(self) -> None:
        self.closed = True
        for q in self.queues:
            q.put_nowait(None)

    def totals(self) -> dict[str, int]:
        done = [e.payload for e in self.events if e.type == "llm_call_finished"]
        return {
            "llm_calls": len(done),
            "tokens_in": sum(p["tokens_in"] for p in done),
            "tokens_out": sum(p["tokens_out"] for p in done),
            "wall_ms": int((time.monotonic() - self.t0) * 1000),
            "retries": sum(e.type == "llm_retry" for e in self.events),
        }


def load_events(path: Path) -> list[TraceEvent]:
    return [TraceEvent.model_validate(json.loads(line)) for line in path.read_text().splitlines()]
