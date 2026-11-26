"""Creates (or updates) the CEO agent and its environment on Managed Agents,
and remembers their IDs in STATE_FILE. Used by setup_agent.py, and by the
phone app on first start so a cloud deploy needs no terminal."""

from __future__ import annotations

import json
from typing import Callable

import anthropic

from .agent_config import AGENT_NAME, MODEL, SYSTEM_PROMPT, agent_tools
from .company import CompanyTools
from .db import connect
from .paths import STATE_FILE


def ensure_agent(client: anthropic.Anthropic, *, update: bool = True,
                 log: Callable[[str], None] = print) -> dict:
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    if state.get("agent_id") and state.get("environment_id") and not update:
        return state

    # Tool definitions don't depend on data, so an in-memory DB is enough here.
    tools = agent_tools(CompanyTools(connect(":memory:")))

    if "environment_id" not in state:
        env = client.beta.environments.create(
            name="ashwa-ceo",
            # Market research needs the open web. The CEO's container commands still go
            # through the `auto` permission policy, and it has no tool that spends or sends.
            config={"type": "cloud", "networking": {"type": "unrestricted"}},
        )
        state["environment_id"] = env.id
        log(f"Created environment {env.id}")

    if "agent_id" not in state:
        agent = client.beta.agents.create(name=AGENT_NAME, model=MODEL, system=SYSTEM_PROMPT, tools=tools)
        log(f"Created agent {agent.id} (version {agent.version})")
    else:
        current = client.beta.agents.retrieve(state["agent_id"])
        agent = client.beta.agents.update(
            state["agent_id"], version=current.version, name=AGENT_NAME, model=MODEL,
            system=SYSTEM_PROMPT, tools=tools,
        )
        log(f"Agent {agent.id} is at version {agent.version}")

    state["agent_id"] = agent.id
    state["agent_version"] = agent.version
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    log(f"Saved IDs to {STATE_FILE}")
    return state
