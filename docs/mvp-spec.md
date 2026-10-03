# Buzz MVP specification

> Neste documento, “Buzz” é o sistema de orquestração da Adventure, não “buzz” no sentido de
> marketing, hype, tendência ou zum-zum. O produto existe para reduzir ruído e organizar sinal,
> contexto, decisões e handoffs.

## Objective

Validate an end-to-end, local-first flow where Buzz receives a natural-language demand,
classifies it, selects explicit context, produces a structured handoff, records human approval
and leaves a trace.

## First scenario

Diagnose what is missing to finish Osana and prepare real-world validation with Graciano,
Salvador Autocenter, referred by Gustavo Rosa. This is planning/diagnosis only: no contact,
production change, live GitHub write or external side effect.

## Second evaluation scenario

Diagnose the current capabilities, limits, runtime dependencies and next readiness milestone
of Liara, an Adventure-internal marketing operations agent/product. The evaluation uses
sanitized local snapshots only; no live database, server or advertising-platform access is
part of the MVP.

## Runtime rules

- deterministic code owns state, policy, context and permissions;
- LLMs interpret, classify and synthesize within validated schemas;
- local fixture is the initial source adapter;
- stale or unavailable sources are never silently substituted;
- material uncertainty is explicit;
- external writes require preview, approval, execute, reread and verify.
- `completed` means a human confirmed execution; Buzz does not perform that execution in the MVP.

## MVP acceptance

Given the Osana fixture and a natural-language objective, Buzz must produce within three intake
rounds a provisional classification, scoped context refs, complexity, executor profile,
uncertainties, next actions and a human-review handoff.

The Liara fixture must exercise the same contract while distinguishing the internal product
project from the related agent entity and explicitly reporting snapshot-only uncertainty.

## Deliberately deferred

GitHub writes, authentication orchestration beyond the local `gh` CLI, MCP runtime, RAG/vector storage,
remote database, multi-user login, OpenClaw, LangGraph, LangChain and external telemetry.
