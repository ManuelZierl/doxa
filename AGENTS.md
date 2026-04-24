# AGENTS.md

This document defines how coding agents should use Qdrant memory in this repository.

## Startup Protocol (Required)

At the start of every task, consolidate relevant Qdrant memory before making edits.

1. Build a short retrieval query from the user request:
   - include domain terms (for example: `doxa`, `belief`, `query engine`, `postgres`, `native`, `cli`)
   - include task intent (for example: `bug`, `refactor`, `test`, `docs`)
2. Run at least 2-3 memory searches with different phrasings.
3. Merge results into a compact working brief with:
   - project facts and constraints
   - prior decisions and conventions
   - any known pitfalls or TODOs
4. Use that brief to guide file discovery, implementation, and validation.

## Suggested Retrieval Pattern

- Query 1: direct user wording
- Query 2: repo/domain wording
- Query 3: implementation detail wording (module/path/tooling)

If results conflict, prefer current repository source of truth and note the mismatch.

## After Completing Work

Store a concise memory entry containing:

- what changed and why
- key files touched
- follow-up work or caveats

Do not store secrets, credentials, tokens, or personal data.

## Quality Bar

- Memory-first: do retrieval before code edits.
- Source-grounded: verify memory against current files.
- Concise: keep briefs and stored notes short and actionable.
