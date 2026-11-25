"""Runs one task for an AI staff agent.

Staff agents are plain Messages API calls made from your machine, with web
search and web fetch, so the CEO can create, rewrite and retire them freely:
each one is just a role, a system prompt and KPIs stored in company.db.
"""

from __future__ import annotations

import os

import anthropic

STAFF_MODEL = os.environ.get("ASHWA_STAFF_MODEL", "claude-opus-5-5")
STAFF_EFFORT = os.environ.get("ASHWA_STAFF_EFFORT", "medium")
MAX_CONTINUATIONS = 5

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]


class StaffRunner:
    def __init__(self, client: anthropic.Anthropic, model: str = STAFF_MODEL, effort: str = STAFF_EFFORT):
        self.client = client
        self.model = model
        self.effort = effort

    def __call__(self, system: str, task: str) -> tuple[str, bool]:
        messages: list[dict] = [{"role": "user", "content": task}]
        texts: list[str] = []
        sources: dict[str, str] = {}
        response = None
        for _ in range(MAX_CONTINUATIONS + 1):
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=system,
                messages=messages,
                tools=WEB_TOOLS,
                output_config={"effort": self.effort},
                # If a safety classifier declines, the API retries on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
            for block in response.content:
                if block.type == "text":
                    texts.append(block.text)
                    for c in getattr(block, "citations", None) or []:
                        url = getattr(c, "url", None)
                        if url:
                            sources.setdefault(url, getattr(c, "title", None) or url)
            if response.stop_reason != "pause_turn":
                break
            # The server paused a long web-research loop: send it back to resume.
            messages.append({"role": "assistant", "content": response.content})

        text = "".join(texts).strip()
        if sources:
            text += "\n\nSources:\n" + "\n".join(f"- {title}: {url}" for url, title in sources.items())
        if response is None:
            return "No response.", False
        if response.stop_reason == "refusal":
            return f"The model declined this task ({getattr(response.stop_details, 'category', None)}). " \
                   "Rephrase it or check it is legitimate.", False
        if response.stop_reason == "pause_turn":
            return text + "\n\n[Stopped: research ran too long. Split the task.]", False
        if response.stop_reason == "max_tokens":
            return text + "\n\n[Cut off: output too long. Ask for a shorter result.]", bool(text)
        return text or "The agent returned no text.", bool(text)
