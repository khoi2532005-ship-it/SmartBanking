"""The three model roles. Each module is one role with one job.

    planner   request -> ordered plan (commit 2)
    worker    plan -> evidence from the feature APIs and a result (commit 3)
    reviewer  plan + result -> verdict, defects and risks (commit 4)

Role boundaries are enforced in code: a role only receives the inputs its
contract names and its output is validated before the next role sees it.
"""
