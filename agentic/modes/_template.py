"""COPY ME. Template for a feature mode.

    cp agentic/modes/_template.py agentic/modes/<yourfeature>.py

Then:
  1. Fill in key / label / owner.
  2. Implement the four methods below.
  3. Register your class in agentic/modes/__init__.py (one line).
  4. Put your prompt text in prompts/<yourfeature>/ - never inline in Python.

You do not write any loop, retry, printing or evidence-log code. The engine in
agentic/loop.py does all of that for every mode.

`agentic/modes/fraud.py` is a complete worked example against a running
service - read that one alongside this.
"""

from __future__ import annotations

import os

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

SERVICE_URL = os.getenv("YOUR_SERVICE_URL", "http://localhost:500X")
PROMPT_FAMILY = "yourfeature"  # -> prompts/yourfeature/


class TemplateMode(Mode):
    key = "yourfeature"
    label = "Your Feature"
    owner = "Your Name"

    def plan(self) -> Plan:
        """State what this run checks, before it runs."""
        return Plan(
            goal="One sentence: what is this run trying to establish?",
            checks=[
                "your service responds on the endpoints below",
                "the data needed to ask a useful question exists",
                "the AI answer is grounded in that data",
            ],
            stop_condition="An answer passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        """Gather deterministic facts. No LLM calls in here.

        Return ok=False (with a summary that says how to fix it) whenever the
        app is not in a state worth asking the model about - the engine then
        stops without spending an API call.
        """
        try:
            records = net.get_json(f"{SERVICE_URL}/api/your-endpoint")
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"your-service at {SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d <your-service>",
            )

        if not records:
            return Evidence(ok=False, summary="No records found. Seed the database first.")

        return Evidence(
            ok=True,
            summary=f"{len(records)} records available; using record {records[0].get('id')}",
            facts={"record": records[0], "count": len(records)},
            # Set degraded=True when you fell back to a secondary source, so the
            # run reports a qualified pass instead of a clean one it did not earn.
            degraded=False,
            note="",
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        """Return (system_prompt, user_prompt).

        `feedback` is empty on attempt 1. On a retry it holds the reasons your
        validate() rejected the last answer - appending it is the Adapt stage.
        """
        system_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY,
            "implementation/system_prompt.txt",
            "implementation/task_prompt.txt",
        )

        record = evidence.facts["record"]
        evidence_block = "\n".join(f"{k}: {v}" for k, v in record.items())

        correction = ""
        if feedback:
            correction = (
                f"\n\nYour previous answer was rejected: {feedback}. Fix exactly that."
            )

        return system_prompt, f"{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        """Check the answer against the facts. Phrase reasons as instructions.

        Good: "it did not state the account balance".
        Useless: "validation failed".

        The reasons go straight into the retry prompt, so they have to tell the
        model what to do differently.
        """
        record = evidence.facts["record"]
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()

        # Example: require the answer to mention the thing it is explaining.
        expected = str(record.get("name", "")).lower()
        if expected and expected not in text:
            reasons.append(f"it did not mention '{record.get('name')}'")

        if len(output) > 40 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
