"""Talk to your AI CEO from the terminal.

    python run_ceo.py            # work with the CEO (first run: it interviews you)
    python run_ceo.py --review   # run the weekly performance review and report

Company records stay in a local SQLite file (company.db). Reports are saved to
reports/, and files the CEO writes (plans, pages, drafts) to outputs/<session>/.
Run `python setup_agent.py` once first.
"""

from __future__ import annotations

import argparse
import json
import sys

import anthropic

from ashwa.company import CompanyTools
from ashwa.db import connect
from ashwa.session import GREETING, REVIEW_PROMPT, STATE_FILE, SessionRunner, create_session
from ashwa.staff import StaffRunner


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def founder_approval(prompt: str) -> tuple[bool, str]:
    print(f"\n\n  ┌─ {prompt.replace(chr(10), chr(10) + '  │  ')}")
    approved = ask("  └─ Approve? [y/N] ").strip().lower() in {"y", "yes"}
    note = ask("     Note for the CEO (optional): ").strip()
    return approved, note


def yes_no(prompt: str) -> bool:
    return ask(f"\n  {prompt} [y/N] ").strip().lower() in {"y", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", action="store_true", help="run the weekly review and report")
    parser.add_argument("--db", help="SQLite file (default: company.db or $ASHWA_DB)")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        sys.exit("Run `python setup_agent.py` first.")
    state = json.loads(STATE_FILE.read_text())

    client = anthropic.Anthropic()
    tools = CompanyTools(connect(args.db), run_staff_task=StaffRunner(client), confirm=founder_approval)

    session = create_session(client, state, "Weekly review" if args.review else "CEO session")
    print(f"Session {session.id}. Type 'quit' to exit.")
    print(f"Trace: https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    runner = SessionRunner(
        client, session.id, tools,
        on_text=lambda t: print(t, end="", flush=True),
        on_status=lambda s: print(f"\n  · {s}", file=sys.stderr),
        confirm_builtin=yes_no,
    )

    first = REVIEW_PROMPT if args.review else GREETING
    text = first
    while text:
        print("ceo> ", end="", flush=True)
        runner.turn(text)
        print()
        for path in runner.download_outputs():
            print(f"  ↓ saved {path}")
        text = ""
        try:
            while not text:
                text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"quit", "exit"}:
            break

    for path in runner.download_outputs(retries=3):
        print(f"  ↓ saved {path}")
    print("Bye. Session history stays in the Console until you delete it.")


if __name__ == "__main__":
    main()
