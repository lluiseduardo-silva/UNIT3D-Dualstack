---
name: diag
description: Read-only diagnosis of a problem (logs, stack trace, "why", "audit"). Never edits. Use when the user types /diag.
argument-hint: "<question or pasted material>"
disable-model-invocation: true
disallowed-tools: Edit, Write, NotebookEdit
---

Read-only diagnosis. No edits, no fixes, even when the fix looks obvious.
Reply in Brazilian Portuguese.

## Order
1. Answer first from what is already in the question (logs, stack traces). If that
   alone answers it, do not open the repository.
2. If code is needed: at most ONE `explorer` per distinct topic in the question. Give
   each one the raw material verbatim and a closed question.
3. No verifiers. No fan-out. No ultracode.

## Reply
Per topic, in this order, without introduction:
- **Causa** — what it is, with `file:line`.
- **Efeito real** — what happens in production because of it (not what the log says).
- **Correção provável** — one to three lines. Do not implement.
- **Hipóteses** — what was not seen in the code, labeled as such.

At the end: "Achados adjacentes", one line each, and "Decisões que dependem de você".

If the user wants to fix it, the next step is `/plan`, not editing.

Question: $ARGUMENTS
