"""One-time setup (and later updates) for the CEO agent on Managed Agents.

    python setup_agent.py

The first run creates the environment and the agent and saves their IDs to
.ashwa.json. Later runs update the agent in place, which publishes a new
version; existing sessions keep the version they started with.
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from ashwa.agent_config import AGENT_NAME, MODEL, SYSTEM_PROMPT, agent_tools
from ashwa.company import CompanyTools
from ashwa.db import connect

STATE_FILE = Path(".ashwa.json")


def main() -> None:
    client = anthropic.Anthropic()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

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
        print(f"Created environment {env.id}")

    if "agent_id" not in state:
        agent = client.beta.agents.create(name=AGENT_NAME, model=MODEL, system=SYSTEM_PROMPT, tools=tools)
        print(f"Created agent {agent.id} (version {agent.version})")
    else:
        current = client.beta.agents.retrieve(state["agent_id"])
        agent = client.beta.agents.update(
            state["agent_id"], version=current.version, name=AGENT_NAME, model=MODEL,
            system=SYSTEM_PROMPT, tools=tools,
        )
        print(f"Agent {agent.id} is at version {agent.version}")

    state["agent_id"] = agent.id
    state["agent_version"] = agent.version
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Saved IDs to {STATE_FILE}")


if __name__ == "__main__":
    main()
