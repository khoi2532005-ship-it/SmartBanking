"""The engine: Plan -> Act -> Observe -> Adapt, with bounded self-correction.

This is the shared team loop the project spec requires (section 4.3: "the
workflow shall be implemented by the integrated team application"). It is
written once, here, and every feature plugs into it as a Mode.

The part that makes it a loop rather than a pipeline is `max_attempts`: when
OBSERVE rejects the model's answer, the reasons are fed back into the prompt
and ACT runs again. A run that never fails OBSERVE completes in one attempt;
a run that does will visibly correct itself, which is the behaviour that has
to be demonstrated at the showcase.
"""

from __future__ import annotations

from agentic import llm, prompts, reporter
from agentic.core import Attempt, Evidence, Mode, Plan, Result, Review, Verdict

# The loop's own prompts, shared by every feature - distinct from the per-feature
# prompt folders a mode loads in build_prompt().
LOOP_PROMPT_FAMILY = "_loop"

# Two is the useful default: one chance to get it right, one chance to correct
# after being told what was wrong. A third attempt almost never changes the
# outcome and just costs a demo 20 seconds of dead air.
DEFAULT_MAX_ATTEMPTS = 2


def run(mode: Mode, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> Result:
    label = mode.label

    # ---- PLAN ---------------------------------------------------------
    plan = mode.plan()
    reporter.stage(label, "PLAN", plan.goal)
    for check in plan.checks:
        reporter.stage(label, "", f"  - {check}")

    # ---- ACT (deterministic half) --------------------------------------
    # Facts first. If the app is not in a state worth asking about, say so
    # and spend no tokens.
    reporter.stage(label, "ACT", "collecting evidence")
    try:
        evidence = mode.collect()
    except Exception as exc:
        evidence = Evidence(ok=False, summary=f"collector raised: {exc}")

    if not evidence.ok:
        reporter.stage(label, "OBSERVE", f"evidence unusable - {evidence.summary}")
        return Result(mode=mode.key, plan=plan, evidence=evidence)

    reporter.stage(label, "OBSERVE", evidence.summary)
    if evidence.degraded:
        reporter.stage(label, "ADAPT", f"degraded source - {evidence.note}")

    result = Result(mode=mode.key, plan=plan, evidence=evidence)
    feedback = ""

    for n in range(1, max_attempts + 1):
        # ---- ACT (LLM half) --------------------------------------------
        if n > 1:
            reporter.stage(label, "ADAPT", f"retrying with correction: {feedback}")
        reporter.stage(label, "ACT", f"asking {llm.describe()} (attempt {n})")

        try:
            system_prompt, user_prompt = mode.build_prompt(plan, evidence, feedback)
            output = llm.ask(system_prompt, user_prompt)
        except llm.LLMUnavailable as exc:
            # A missing key or a rate limit should end the run cleanly with a
            # readable reason, not a stack trace in front of a marker.
            result.attempts.append(
                Attempt(n=n, output="", verdict=Verdict(False, [str(exc)]),
                        adapt_note=feedback, error=str(exc))
            )
            reporter.stage(label, "OBSERVE", f"no answer - {exc}")
            break
        except Exception as exc:
            result.attempts.append(
                Attempt(n=n, output="", verdict=Verdict(False, [str(exc)]),
                        adapt_note=feedback, error=f"prompt build failed: {exc}")
            )
            reporter.stage(label, "OBSERVE", f"prompt build failed - {exc}")
            break

        # ---- OBSERVE ---------------------------------------------------
        verdict = mode.validate(output, evidence)
        result.attempts.append(
            Attempt(n=n, output=output, verdict=verdict, adapt_note=feedback)
        )
        reporter.stage(
            label, "OBSERVE",
            "answer accepted" if verdict.ok else f"answer rejected - {verdict.feedback}",
        )

        if verdict.ok:
            break

        # ---- ADAPT ------------------------------------------------------
        # The reasons become the next prompt's correction. Loop continues.
        feedback = verdict.feedback
    else:
        reporter.stage(label, "ADAPT", f"giving up after {max_attempts} attempts")

    # ---- REVIEW ---------------------------------------------------------
    # Only worth spending a call on an answer that already passed OBSERVE.
    if result.ok:
        result.review = _review(label, result)

    return result


def _review(label: str, result: Result) -> Review:
    """Second opinion from the review model, using the loop's own prompts.

    Advisory: it never changes the pass/fail verdict, because a flaky reviewer
    would make runs non-reproducible in front of a marker. It is recorded in
    the console output and the evidence log so a human can act on it - which is
    the human-review step the project spec defers to Release 2.
    """
    try:
        system_prompt, task_prompt = prompts.load_all(
            LOOP_PROMPT_FAMILY,
            "review_system_prompt.txt",
            "review_task_prompt.txt",
        )
    except prompts.MissingPrompt as exc:
        return Review(error=str(exc))

    user_prompt = (
        f"{task_prompt}\n\n"
        f"Evidence given to the answering model:\n{result.evidence.summary}\n\n"
        f"Answer under review:\n{result.final_output}"
    )

    reporter.stage(label, "REVIEW", "second opinion from the review model")
    try:
        text = llm.ask(system_prompt, user_prompt, review=True, max_tokens=400)
    except llm.LLMUnavailable as exc:
        reporter.stage(label, "REVIEW", f"unavailable - {exc}")
        return Review(error=str(exc))

    return Review(text=text, model=llm.describe(review=True))
