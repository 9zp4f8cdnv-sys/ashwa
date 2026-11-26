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


def config_problem() -> str | None:
    if len(os.environ.get("ASHWA_PASSWORD", "")) < 8:
        return "ASHWA_PASSWORD must be at least 8 characters."
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "ANTHROPIC_API_KEY is missing (get one at platform.claude.com → API Keys)."
    return None


def setup_needed_app(problem: str):
    """On a cloud host, serve a page that says what to fix instead of crashing."""
    from html import escape

    from flask import Flask
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def fix_me(path):
        return (f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<body style='font:18px/1.5 -apple-system,sans-serif;padding:24px'>"
                f"<h2>Ashwa needs one more setting</h2><p>{escape(problem)}</p>"
                f"<p>In Render: open the <b>ashwa</b> service → <b>Environment</b> → edit the value → "
                f"<b>Save, rebuild and deploy</b>.</p>"), 503
    return app


def build_app():
    problem = config_problem()
    if problem:
        if os.environ.get("ASHWA_BEHIND_PROXY") == "1":
            return setup_needed_app(problem)
        raise SystemExit(problem)
    password = os.environ["ASHWA_PASSWORD"]

    client = anthropic.Anthropic()
    # The CEO agent is created on the first message, so the page always comes up
    # and any setup problem (bad key, no credit) shows in the chat.
    worker = CEOWorker(DB_FILE, managed_agents_turn(client, lambda: ensure_agent(client, update=False)),
                       staff_runner=StaffRunner(client))
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
