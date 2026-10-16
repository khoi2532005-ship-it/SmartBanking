"""Shared Multi-Agent Server (Release 2).

One host process, never a Compose service, that coordinates a Planner, a
Worker and a Reviewer agent and holds each workflow for a human decision
before releasing the result. Feature backends reach it through the
MULTI_AGENT_SERVER_URL connection config in docker-compose.yml.
"""
