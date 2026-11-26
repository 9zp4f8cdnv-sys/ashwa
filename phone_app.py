"""Run the phone app: a web page you open in your phone's browser.

On your own computer:

    export ANTHROPIC_API_KEY=sk-ant-...
    export ASHWA_PASSWORD='a long password'
    python phone_app.py --host 0.0.0.0     # phones on the same Wi-Fi: http://<computer-ip>:8080

On a cloud host (Render, see render.yaml and the README), the host runs:

    gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT 'phone_app:build_app()'

Keep it to ONE worker process: the CEO runs in a background thread inside it.
The CEO agent is created automatically on first start.
"""

from __future__ import annotations

import argparse
import os
import sys

import anthropic

from ashwa.paths import DB_FILE
from ashwa.setup import ensure_agent
from ashwa.staff import StaffRunner
from ashwa.web import CEOWorker, create_app, managed_agents_turn


def build_app():
    password = os.environ.get("ASHWA_PASSWORD", "")
    if len(password) < 8:
        raise SystemExit("Set ASHWA_PASSWORD to a password of at least 8 characters first.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first (from platform.claude.com).")

    client = anthropic.Anthropic()
    state = ensure_agent(client, update=False)
    worker = CEOWorker(DB_FILE, managed_agents_turn(client, state), staff_runner=StaffRunner(client))
    app = create_app(worker, password=password, db_path=DB_FILE,
                     secret_key=os.environ.get("ASHWA_SECRET_KEY"))

    if os.environ.get("ASHWA_BEHIND_PROXY") == "1":
        # On a cloud host: trust its HTTPS proxy for the client IP and scheme,
        # and only send the login cookie over HTTPS.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
        app.config["SESSION_COOKIE_SECURE"] = True
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = parser.parse_args()
    try:
        app = build_app()
    except SystemExit as e:
        sys.exit(str(e))
    print(f"Open http://{'<this-computer-ip>' if args.host == '0.0.0.0' else args.host}:{args.port} on your phone.")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
