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

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # from platform.claude.com
python setup_agent.py                    # once; re-run after editing ashwa/agent_config.py
python run_ceo.py                        # first run: the CEO interviews you
```

Each week:

```bash
python run_ceo.py --review
```

Where things are saved:
- `company.db`: all company records (SQLite, stays on your machine)
- `reports/`: weekly reports
- `outputs/<session>/`: plans, landing pages and drafts the CEO writes

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
