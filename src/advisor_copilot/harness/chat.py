"""Chat threads: context for the next turn and the copilot's reply text, from the SQLite store."""

import hashlib
from pathlib import Path

from advisor_copilot.db import Store
from advisor_copilot.harness.orchestrator import ThreadContext
from advisor_copilot.harness.state import RunState, load_state, state_path
from advisor_copilot.render import render_text


def reply_text(state: RunState) -> str:
    if state.final:
        return state.final.recommendation.headline
    if state.answer:
        return render_text(state.answer.answer, state.metrics)
    return state.message or state.error or str(state.status)


def thread_context(store: Store, thread_id: str, runs_dir: Path, turns: int) -> ThreadContext:
    """Code-built summary of the last `turns` exchanges plus the latest run that has findings."""
    msgs = store.messages(thread_id)
    lines, last = [], None
    for q, a in zip(msgs[::2], msgs[1::2], strict=False):
        lines.append(
            f"Advisor: {q['text'][:160]} | route: {a['route']} | copilot: {a['text'][:200]}"
        )
    for m in reversed(msgs):
        if m["run_id"] and state_path(runs_dir, m["run_id"]).exists():
            st = load_state(m["run_id"], runs_dir)
            if st.analyst_reports:
                last = st
                break
    return ThreadContext("\n".join(lines[-turns:]), last)


def answer_key(thread_id: str, text: str, preset: str | None, data: str) -> str:
    raw = "|".join([thread_id, " ".join(text.lower().split()), preset or "", data])
    return "answer:" + hashlib.sha256(raw.encode()).hexdigest()
