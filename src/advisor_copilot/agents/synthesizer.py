"""Single-writer synthesizer that drafts the Recommendation with placeholders (03 §8.3)."""

import json

from advisor_copilot.harness.context import Feedback, SynthContext, load_prompt, synth_inputs
from advisor_copilot.harness.deps import Deps
from advisor_copilot.llm.base import LLMRequest, Message
from advisor_copilot.models import ChatAnswer, Recommendation


async def synthesize(
    ctx: SynthContext, deps: Deps, feedback: Feedback | None, answer_mode: bool = False
) -> dict:
    """Recommendation draft (annual review) or short chat answer, numbers as placeholders."""
    s = deps.settings
    parts = synth_inputs(ctx)
    if feedback:
        parts += [
            f"<previous_draft>\n{json.dumps(feedback.draft)}\n</previous_draft>",
            f'<revision_feedback source="{feedback.source}">\n{json.dumps(feedback.items)}\n'
            "</revision_feedback>",
        ]
    req = LLMRequest(
        model=s.models.synthesizer,
        system=load_prompt(
            "synthesizer.md"
            if not answer_mode
            else "answer.md"
            if ctx.client
            else "book_answer.md",
            s,
        ),
        messages=[Message(role="user", text="\n".join(parts))],
        temperature=s.temperature.synthesizer,
        thinking_level=s.thinking_level.synthesizer,
        max_output_tokens=s.max_output_tokens.synthesizer,
        response_schema=ChatAnswer if answer_mode else Recommendation,
        purpose="synthesizer",
    )
    return (await deps.llm_call(req)).parsed or {}
