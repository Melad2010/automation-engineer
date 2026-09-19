# Lead qualification agent, with the guardrails on

An agent that researches an organisation with tools, scores it, and returns a
schema-validated verdict — under a token budget, a cost budget, a request
budget, a rate limit, a tool allowlist and a turn limit, every one of them
enforced in code.

The interesting part is not that it calls a model. It is what makes it stop.

## Run it

```bash
cd projects/ai-agent

python3 run.py --dry-run                                  # no key, no network, no cost
python3 run.py --dry-run --domain gizafoodbank.example.org
python3 run.py --dry-run --budget-usd 0.02                # watch the budget stop it
python3 run.py --list-leads

pip install anthropic                                     # live mode
export ANTHROPIC_API_KEY=...                              # or: ant auth login
python3 run.py --domain nileyouth.example.org
```

`--dry-run` replays a canned model transcript through the **real** agent loop:
the same guardrails, the same tool code, the same budget accounting. Only the
model's side of the conversation is scripted. That is what lets the whole test
suite run in CI for nothing.

## The guardrails

| Guardrail | What it does | Where |
|---|---|---|
| Cost budget | Stops the run at a dollar ceiling, priced per model | `budget.py` |
| Token budget | Stops at a token ceiling — with a **reserve** for the reply that has not arrived yet | `budget.py` |
| Request budget | Caps how many API calls one task may make | `budget.py` |
| Rate limiter | Sliding window, at most N requests per minute | `guardrails.py` |
| Tool allowlist | A tool the model invents is refused by name | `guardrails.py` |
| Per-tool call cap | Stops the "call lookup 40 times" loop | `guardrails.py` |
| Result truncation | One huge tool result cannot eat the context window | `guardrails.py` |
| Turn limit | A model that never concludes still terminates | `agent.py` |
| Retry policy | Retries 429/5xx and transport errors; **never** retries a 400 | `guardrails.py` |
| Refusal handling | A refusal is HTTP 200 — it is checked before any content is read | `agent.py` |

The reserve is the one that is easy to skip. Checking only what has *already*
been spent means the final request sails straight past the ceiling, because the
reply it pays for has not been counted yet.

## API choices, and why

- **`claude-opus-5`** with **adaptive thinking** (`{"type": "adaptive"}`) — the
  model decides how much to think per turn. The old fixed `budget_tokens` is
  gone on this model; the token ceiling here is the *budget*'s job, not the
  thinking parameter's.
- **Server-side refusal fallbacks** are on by default (`fallbacks: "default"`),
  so a refused request is routed by category instead of returning nothing.
  `--` turn them off with `Agent(enable_fallbacks=False)` if you would rather
  handle refusals yourself.
- **`strict: true`** on every tool with `additionalProperties: false`, so tool
  arguments are guaranteed to match the schema.
- **Structured outputs** (`output_config.format`) for the final verdict, so the
  caller gets a validated dict instead of parsing prose.
- **A hand-written loop**, not the SDK's `tool_runner`. Every guardrail above
  lives *between* two turns of that loop. Owning the loop is what makes them
  visible and testable. Use the tool runner when you want the loop and not the
  rules.
- Tool inputs are read with `json.loads`, never string-matched — escaping in
  tool-call JSON varies by model.

## What the tools do — and refuse to do

`lookup_company` returns `found: false` for an unknown domain, along with the
domains it does know, and tells the model not to invent one. `check_website`
returns `status: null` when the status is genuinely unknown rather than
guessing. `score_fit` does the arithmetic deterministically: the model decides
what to look up and what to conclude, it does not get to decide the score.

A tool called with bad arguments returns an error result to the model so it can
correct itself; a tool that breaks a *policy* stops the run. The difference is
whether the next turn could plausibly fix it.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

71 tests, no API key, no network, no cost. Mostly failure paths, because that is
where agents go wrong: every budget stopping mid-run, the reserve refusing an
unaffordable request, the turn limit, the tool allowlist, per-tool caps, result
truncation, a 503 retried and a 400 not retried, the rate limiter pacing
requests, a refusal detected before content is read, a bad tool argument handed
back for correction, and an unparseable verdict recorded rather than crashing.
