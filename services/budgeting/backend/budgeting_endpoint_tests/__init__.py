"""Post-commit endpoint tests for the budgeting API (Release 2), black-box HTTP against a running stack.

A package of their own, so its conftest never collides with another feature's `tests` package
when several suites run in one pytest session.
"""
