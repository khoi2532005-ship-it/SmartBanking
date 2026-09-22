---
source_id: smartbank-overview
title: SmartBank application overview
authority_tier: 2
origin: README.md and docker-compose.yml (extract, 2026-09-22)
---

# What SmartBank is

SmartBank is a personal finance and banking assistant built by a team of five UTS students for 41026 Advanced Software Development. Each student owns one full-stack feature made of three microservices: a frontend, a Flask backend/API, and a Flask database service over SQLite. An AI layer sits on top of every feature.

# The five features and their owners

Accounts and Customers is owned by William Por (Student 1). Loans and Credit is owned by David Lee (Student 2). Fraud Alerts is owned by Duc Minh Khoi Tran (Student 3). Budgeting and Spending Insights is owned by Cong Bao Nguyen (Student 4). Transactions is owned by Aidan Lei (Student 5).

# Ports

The shared home page runs on port 3000. Accounts uses frontend 3001, API 5001, database 5011. Loans uses frontend 3002, API 5002, database 5012. Fraud Alerts uses frontend 3003, API 5003, database 5013. Budgeting uses frontend 3004, API 5004, database 5014. Transactions uses frontend 3005, API 5005, database 5015.

# Running the application

Copy .env.example to .env and set GEMINI_API_KEY. Run docker compose up --build -d to start all five features and the home page, then open http://localhost:3000. Stop everything with docker compose down -v. The Release 0 docker-compose.yml deploys only the containerised feature microservices.

# AI-Mode

AI-Mode uses the Gemini API through its OpenAI-compatible chat-completions endpoint, selected by LLM_PROVIDER=gemini. Gemini was approved by the tutor for this project. Setting LLM_PROVIDER=ollama switches to local Qwen or Llama models as a fallback. Both providers speak the same protocol, so one client drives either.

# Release 1 additions

Release 1 adds one shared local MCP server on port 8100, one shared local RAG server on port 8200, and MCP and RAG validation modes in the shared agentic loop. AI-Mode, the MCP server, the RAG server and the agentic loop all run on the host and are not containerised and are not defined as docker-compose services. Containerised backends reach the host services at host.docker.internal.

# Repository layout

services/ holds one folder per feature (accounts, transactions, fraud-alerts, budgeting, loans), each with frontend, backend and database. shared/frontend/ holds the unified index.html, the CSS theme and htmx. prompts/ holds prompt text files per feature. agentic/ is the shared agentic-loop engine with one mode per feature. mcp_server/ is the shared MCP server. rag_server/ is the shared RAG server. docs/evidence/ holds run evidence for the technical report.
