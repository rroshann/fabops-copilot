# FabOps Copilot

An agentic LLM assistant for semiconductor service-parts supply-chain operations.

A Material Planner asks a question in natural language — "why is part A7 about to stock out at the Taiwan fab, and what should I do?" — and an agent plans the investigation, calls domain tools (intermittent-demand forecaster, inventory lookup, supplier lead-time model, SEC filings search, macro industry signals), reasons over the results, and returns a root-cause analysis with a recommended action and a full audit trail.

**Status:** work in progress. Architecture, design spec, and implementation plan in progress.

## Stack (planned)

- **Frontend:** static dashboard served from S3
- **API:** Amazon API Gateway (HTTP, CORS)
- **Compute:** AWS Lambda (Python 3.9, arm64)
- **Persistence:** Amazon DynamoDB
- **Observability:** Amazon CloudWatch (structured logs, metrics, dashboard)
- **LLM:** Google Gemini
- **Agent framework:** LangGraph (on top of `langchain-core`)

## Data sources (planned, all public)

- Hyndman `carparts` intermittent-demand benchmark (service-parts demand backbone)
- SEC EDGAR — Applied Materials 10-K, 10-Q, 8-K, earnings call transcripts
- US Census M3 — NAICS 334413 Semiconductor and Related Device Manufacturing
- SEMI / WSTS public monthly billings and bookings statistics
- FRED — semiconductor manufacturing PPI and industrial production series

## Course context

Final project for DS 5730-01 Context-Augmented Gen AI Apps (Spring 2026), Vanderbilt University.
