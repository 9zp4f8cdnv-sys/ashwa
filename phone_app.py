"""Run the phone app: a web page you open in your phone's browser.

    export ASHWA_PASSWORD='a long password'
    python phone_app.py                    # this computer only: http://127.0.0.1:8080
    python phone_app.py --host 0.0.0.0     # phones on the same Wi-Fi: http://<computer-ip>:8080

For use away from home, don't open a port on your router. Use a private
network such as Tailscale (see README). Run `python setup_agent.py` once first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic

from ashwa.session import STATE_FILE
from ashwa.staff import StaffRunner
from ashwa.web import CEOWorker, create_app, managed_agents_turn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", default=os.environ.get("ASHWA_DB", "company.db"))
    args = parser.parse_args()

    password = os.environ.get("ASHWA_PASSWORD", "")
    if len(password) < 8:
        sys.exit("Set ASHWA_PASSWORD to a password of at least 8 characters first.")
    if not STATE_FILE.exists():
        sys.exit("Run `python setup_agent.py` first.")
    state = json.loads(STATE_FILE.read_text())

    client = anthropic.Anthropic()
    worker = CEOWorker(args.db, managed_agents_turn(client, state), staff_runner=StaffRunner(client))
    app = create_app(worker, password=password, db_path=args.db,
                     secret_key=os.environ.get("ASHWA_SECRET_KEY"))
    print(f"Open http://{'<this-computer-ip>' if args.host == '0.0.0.0' else args.host}:{args.port} on your phone.")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
