"""One-time setup (and later updates) for the CEO agent on Managed Agents.

    python setup_agent.py

The first run creates the environment and the agent and saves their IDs to
.ashwa.json (in ASHWA_DATA_DIR). Later runs update the agent in place, which
publishes a new version; existing sessions keep the version they started with.
The phone app runs this automatically on first start.
"""

from __future__ import annotations

import anthropic

from ashwa.setup import ensure_agent

if __name__ == "__main__":
    ensure_agent(anthropic.Anthropic())
