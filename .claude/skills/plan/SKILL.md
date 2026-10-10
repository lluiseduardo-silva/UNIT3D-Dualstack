---
name: plan
description: Plans a sensitive or cross-module change without implementing it. Produces a self-sufficient docs/plans/<date>-<slug>.md. Use when the user types /plan.
argument-hint: "<description of the change>"
disable-model-invocation: true
disallowed-tools: Edit, NotebookEdit
---

Plan the change below WITHOUT implementing anything. The working tree leaves as it came in.
The only allowed write is the plan file under `docs/plans/`. No other file.
The plan file and your reply are written in Brazilian Portuguese.

## Exploration
- ONE `explorer` per concern, with a closed question and the user's raw material verbatim.
- Before spawning, list the questions and remove the ones that overlap.
- Dependency sources only if the plan depends on a specific default: one agent, once.

## Verification
- Only for items that came back as Hypothesis and that the plan depends on. At most 5
  `verifier`.
- Items Confirmed with a line, and user evidence, are not verified.
- A conflict with no line on either side goes to "Decisões pendentes".

## The plan — docs/plans/<YYYY-MM-DD>-<slug>.md
Must be SELF-SUFFICIENT: whoever executes it opens no file beyond the cited ones and
confirms nothing.

For each affected file, mandatory:
- path and exact function/class/block (name + line)
- relevant current state — signature, query, contract — **copied**, not described
- final state — **copied** or in pseudocode, not described
- why, only if not obvious from the diff

For each step:
- order and dependency on previous steps
- verification: a concrete command or assertion proving the step worked

If the change touches concurrent writes, locks, transactions, queues, or jobs across
multiple instances, the plan must include a **contention test step against the real
engine** (same engine and version as production, provisioned in an ephemeral container,
Testcontainers or equivalent). That step's verification is the command that runs the
test. Use `/contention-test` to specify it. Without this step the plan is not ready.

Sections, in this order (headings in Portuguese):
1. Objetivo
2. Fora de escopo
3. Premissas (what the plan assumes and did not confirm)
4. Arquivos afetados
5. Passos
6. Riscos que mudam a implementação (one line each)
7. Decisões pendentes (questions to the user, not explained choices)
8. Achados adjacentes (listed, not touched)

## Style
- Direct sentences. No introduction, no justifying unquestioned choices, no repeating
  context across sections.
- Before delivering, reread and cut everything an executor does not need in order to act.

## Delivery
Reply only with: the file path, the number of assumptions, and the pending decisions.

Change: $ARGUMENTS
