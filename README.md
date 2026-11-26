# Ashwa

An AI CEO that builds and runs a business for you. It interviews you, researches
markets on the web, picks a business that fits you, builds a team of AI staff
agents, runs small experiments, reviews every agent's performance, fixes or
replaces the ones that get stuck, and sends you a weekly report.

**You stay the owner.** The CEO can research, plan and draft. It can't spend money,
sign anything, publish anything or contact anyone. Each of those needs your
approval, and then you carry it out yourself.

> No software can promise you $1M. The CEO is told to aim high, but to give you
> realistic ranges and to stop experiments that don't work.

## How it works

```
 You (founder) ──approve / deny──┐
      │                          │
      ▼                          │
 CEO agent (Claude, Managed Agents: web research + a container for drafts)
      │  custom tools run on YOUR machine, against company.db
      ├── hire_agent / rewrite_agent / retire_agent ─► AI staff (Claude + web search)
      ├── assign_task ─────────────────────────────► staff does research / drafts
      ├── record_kpi / review_staff ───────────────► finds stuck agents
      ├── run_ethics_check / request_approval ─────► you decide
      ├── record_transaction ──────────────────────► money in / out
      └── log_decision / write_report ─────────────► reports/*.md
```

### The AI staff and "stuck" agents

Staff are AI agents. Each is a role, a system prompt and 1–3 measurable KPIs. In a
review (`python run_ceo.py --review`), an agent counts as **stuck** when:
- a KPI missed its target on the last two readings, or
- its last two tasks failed.

The CEO then works out *why* (unclear prompt, missing data, impossible target, role
not needed):
1. The first time it's stuck, the CEO **rewrites** the agent: new prompt, mission or KPIs.
2. If it's still stuck after that, the CEO **retires** it and hires a replacement
   built on what went wrong, or drops the role.

Every change is logged in `staff_changes` with the reason. **The CEO never manages
real people.** If a human is involved, it can only send you a written recommendation
(`human_staffing`), and you decide.

### Guardrails (enforced in code, not just the prompt)

| Rule | Where |
| --- | --- |
| Spending, contracts, launches, customer contact, legal filings and decisions about people need your `y` | `request_approval` |
| A launch needs a passed ethics check covering honest claims, privacy, consumer protection, legal registration, IP, accessibility and harm | `run_ethics_check` + `request_approval` |
| An expense must match an approved spend, and can't go over what's left of it | `record_transaction` |
| At most 8 active AI agents (keeps costs down) | `hire_agent` |
| KPIs come from real numbers, with a note of where each came from | `record_kpi` |
| No tool exists that pays, signs, publishes or sends | — |

## Run it from your iPhone (no computer needed)

The app runs on a small cloud server at [Render](https://render.com), and you open its
link on your phone. Everything below works in Safari.

1. Get an API key: [platform.claude.com](https://platform.claude.com) → **Billing**
   (add a card and set a **monthly limit**) → **API Keys** → **Create Key**. Copy it.
2. Tap **[Deploy to Render](https://render.com/deploy?repo=https://github.com/9zp4f8cdnv-sys/Ashwa)**
   and sign in **with GitHub**. Allow Render to see the **Ashwa** repo if asked.
3. Render shows the settings from `render.yaml`. Fill in:
   - `ANTHROPIC_API_KEY`: paste your key
   - `ASHWA_PASSWORD`: a password of 8 or more characters for the phone page
4. Tap **Deploy** (or **Apply**), add a card for Render, and wait about 3–5 minutes
   until it says **Live**.
5. Open the `https://ashwa-….onrender.com` link at the top, sign in, and say hello.
   In Safari, tap Share → **Add to Home Screen** to make it look like an app.

Costs: Render's Starter plan with a 1 GB disk is about US$7–8 a month (the disk keeps
your company records safe across restarts). Claude API usage is billed separately by
Anthropic.

To update after a code change: Render redeploys automatically when `main` changes.

## Setup on a computer

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # from platform.claude.com
python setup_agent.py                    # once; re-run after editing ashwa/agent_config.py
python run_ceo.py                        # first run: the CEO interviews you
```

Or use it from your phone: see [Phone app](#phone-app).

Each week:

```bash
python run_ceo.py --review
```

Where things are saved:
- `company.db`: all company records (SQLite, stays on your machine)
- `reports/`: weekly reports
- `outputs/<session>/`: plans, landing pages and drafts the CEO writes

## Phone app

A web page you open in your phone's browser. You can chat with the CEO, tap
**Approve** or **Deny** when it asks, check each AI agent's KPIs (stuck ones are
shown in red), see money in and out, and read the weekly reports.

```bash
export ASHWA_PASSWORD='a long password'   # required, at least 8 characters
python phone_app.py --host 0.0.0.0        # then open http://<your-computer-ip>:8080 on your phone
```

- The server runs on your computer (or a small server) and the phone just opens the page.
  The computer has to stay on.
- On the same Wi-Fi, use the computer's local IP (for example `http://192.168.1.20:8080`).
- **Away from home:** install [Tailscale](https://tailscale.com) (free) on the computer
  and the phone, then open `http://<computer-tailscale-name>:8080`. **Don't** open a port
  on your router: this page can approve spending.
- An approval you don't answer within 30 minutes counts as **denied**. The CEO can ask
  again later.
- To add it to your home screen: Share → **Add to Home Screen** (iPhone) or
  ⋮ → **Add to Home screen** (Android).
- Set `ASHWA_SECRET_KEY` to any long random string if you want to stay logged in after
  the server restarts.

## Costs

You pay for the Claude API: tokens for the CEO and every staff task, plus Managed
Agents session time. Web research makes heavy use of tokens. To spend less:
- `ASHWA_STAFF_MODEL=claude-sonnet-5-5` runs staff on a cheaper model.
- `ASHWA_STAFF_EFFORT=low` makes staff do lighter thinking.
- Keep the team small.

Check your usage at platform.claude.com.

## Settings

| Variable | Default | |
| --- | --- | --- |
| `ASHWA_DB` | `company.db` | Database file |
| `ASHWA_STAFF_MODEL` | `claude-opus-5-5` | Model for staff agents |
| `ASHWA_STAFF_EFFORT` | `medium` | `low` / `medium` / `high` |

## Tests

```bash
python -m pytest -q
```
