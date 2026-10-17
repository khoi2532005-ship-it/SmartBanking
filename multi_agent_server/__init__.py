"""Shared Multi-Agent Server (Release 2).

One host process, never a Compose service, that coordinates a Planner, a
Worker and a Reviewer agent and holds each workflow for a human decision
before releasing the result. Feature backends reach it through the
MULTI_AGENT_SERVER_URL connection config in docker-compose.yml.

Run it from the repo root:  python -m multi_agent_server.server
Validate it:                python -m multi_agent_server.validate [--evidence]
From a terminal:            python -m multi_agent_server.run --request "..."
Decide pending ones:        python -m multi_agent_server.review [--watch 5]
"""
