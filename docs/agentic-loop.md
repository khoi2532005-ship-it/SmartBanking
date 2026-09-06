# The Shared Agentic Loop

`Plan → Act → Observe → Adapt`, implemented once for the whole application.

## Why there is only one

The project specification puts the loop at team level, not student level:

> **§4.3 Shared Team Agentic Loop** — "The workflow shall be implemented by the **integrated team application**."

> **§3.1** — "The **integrated application** shall implement the **shared** Plan → Act → Observe → Adapt Agentic AI workflow."

> **§6.1** — "Microservices architecture, AI-mode, **shared** Plan → Act → Observe → Adapt workflow, and **individual** DevOps CI/CD pipelines."

That last line puts *shared* on the loop and *individual* on the pipelines in one sentence, so the split is deliberate. Five separate loops would not meet §4.3.

But §2.2 also makes it an individual responsibility to *demonstrate* the workflow, and §10.3 requires each student to demo their own feature in the group video. So: **one implementation, five demonstrable slices.** Each feature is a mode on the same menu, and each owner demos their own option.

## Running it

```bash
cp .env.example .env                      # then set GEMINI_API_KEY
pip install -r requirements-agentic.txt
docker compose up -d                      # the loop drives the running services

python agentic_loop.py                    # interactive menu — use this to demo
python agentic_loop.py --mode fraud       # one feature
python agentic_loop.py --all              # every implemented feature + summary
python agentic_loop.py --all --quiet      # CI; exit code only
```

The loop runs on the host and talks to the services over HTTP, the same way a marker would. It is not a container.

## What the engine does

```
PLAN     mode.plan()            state the goal and the checks up front
ACT      mode.collect()         gather deterministic facts — no LLM
                                 └─ if evidence is unusable, stop here and
                                    spend no tokens
ACT      mode.build_prompt()    build the prompt from those facts
         llm.ask()              call the implementation model
OBSERVE  mode.validate()        check the answer against the facts
ADAPT    ── rejected? ──────────┘  feed the reason back into the prompt
                                   and run ACT again (bounded, default 2)
REVIEW   llm.ask(review=True)   second opinion from the review model
                                (only on an accepted answer; advisory)
```

The `ADAPT` arrow going back into `ACT` is what makes this a loop rather than a
pipeline. A run that passes first time completes in one attempt; a run that
fails `OBSERVE` visibly corrects itself. That behaviour is the thing being
marked, so `agentic/loop.py` logs every stage and the reporter calls out when
`ADAPT` fired.

### Two prompt layers

| Layer | Lives in | Loaded by | Whose job |
|---|---|---|---|
| **Feature prompts** | `prompts/<feature>/` | your `build_prompt()` | the feature owner |
| **Loop prompts** | `prompts/_loop/` | the engine | shared, edit as a team |

`prompts/_loop/review_system_prompt.txt` and `review_task_prompt.txt` drive the
REVIEW stage for every feature, so a wording change there affects all five.
The review model replies in the Risk / Correction / Retest format.

The reviewer is **advisory and never overturns the verdict** — `validate()` is
the gate. A reviewer that could flip a result would make runs
non-reproducible in front of a marker. Its opinion is printed and written to
the evidence log so a human can act on it, which is the human-review step the
project spec defers to Release 2 (§4.2).

Two more rules the engine enforces for you:

- **No LLM call on bad evidence.** If `collect()` returns `ok=False`, nothing is sent to the model. A service being down produces a readable message, not a hallucinated answer about data that was never read.
- **Degraded is not the same as passing.** If `collect()` returns `degraded=True`, the run continues but says so, in the console and in the evidence log.

## Adding your feature

Four methods. You write no loop, retry, printing or logging code.

**1. Copy the template**

```bash
cp agentic/modes/_template.py agentic/modes/budgeting.py
```

**2. Implement the four methods**

| Method | Stage | Does |
|---|---|---|
| `plan()` | PLAN | Returns a `Plan`: goal, checks, stop condition |
| `collect()` | ACT | Hits your DB/endpoints, returns `Evidence`. **No LLM calls.** |
| `build_prompt(plan, evidence, feedback)` | ACT | Returns `(system, user)`. Append `feedback` — that append *is* Adapt |
| `validate(output, evidence)` | OBSERVE | Returns `Verdict(ok, reasons)` |

**3. Register it** — one import and one line in `agentic/modes/__init__.py`:

```python
from agentic.modes.budgeting import BudgetingMode

MODES = {mode.key: mode for mode in (FraudMode(), BudgetingMode())}
```

Then delete your feature's line from `PENDING` in the same file.

**4. Put your prompts in `prompts/<yourfeature>/`** as `.txt` files, never inline
in Python. Teammates can then edit prompt wording without touching your code,
and a prompt change shows up as a reviewable diff.

`agentic/modes/fraud.py` is a complete worked example against a live service —
read it next to the template.

### Writing a good `validate()`

This is the method that decides whether your loop is real. The test is: **could
this reject a fluent answer that is wrong?** If it only checks the call
returned 200 or the string is non-empty, `ADAPT` will never fire and there is
nothing to demonstrate.

Check the answer is grounded in facts you actually collected:

```python
if str(int(amount)) not in text.replace(",", ""):
    reasons.append(f"it did not state the transaction amount (${amount:.2f})")
```

Phrase every reason as an instruction to the model, because that is exactly
where it goes — straight into the retry prompt. `"it did not name the
triggered rule"` is useful. `"validation failed"` teaches the model nothing.

## Evidence for the report

Every run writes to `docs/evidence/`:

- `<mode>-<timestamp>.json` — full transcript: plan, evidence, every attempt, every verdict
- `evidence-log.md` — one appended row per run, paste-ready for the technical report

The spec requires pre-testing and post-testing evidence (§2.2), so run the loop
before and after a change and keep both rows.

## Tests

```bash
python -m pytest tests/test_agentic_loop.py -q
```

Six tests over the engine. They stub the LLM and need no services and no API
key, so they run in CI on every push. `test_adapt_retries_and_recovers` is the
one that proves the loop loops — keep it passing.

## Model configuration

One switch in `.env` drives everything:

```
LLM_PROVIDER=gemini                       # or: ollama
GEMINI_MODEL=gemini-flash-lite-latest
```

Gemini is tutor-approved for this project. The Ollama path is kept working as a
fallback — `agentic/llm.py` mirrors the env var names already used by
`services/fraud-alerts/backend/services/llm_client.py`, so there is one set of
credentials to configure, not two.

## Scope

This is the Release 0 loop. Release 1 adds MCP and RAG (§4.2), and Release 2
adds Planner/Worker/Reviewer agents. Those extend the same engine — a new mode,
or a second model role inside `build_prompt`/`validate` — rather than replacing
it.
