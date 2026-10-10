# Workflow and agents

## 0. Output language

Everything the user reads is written in **Brazilian Portuguese**: replies, diagnoses,
plans under `docs/plans/`, subagent output, and commit messages. Instruction files
(rules, skills, agents) stay in English. Code identifiers, commands, log excerpts and
quoted source stay exactly as they are in the codebase.

## 1. Triage — before any action

Classify the request into ONE of four modes and follow only that mode's rules:

| Mode | When | Tool |
|---|---|---|
| Direct | local change, ≤3 files, does not touch money/auth/data/concurrency | edit and done |
| Diagnosis | "which problems", "why", "explain", "audit" | `/diag` |
| Plan | sensitive change, or one crossing module boundaries | `/plan` |
| Ultracode | migration, cross-cutting refactor, real parallelism | only when the user types `ultracode` |

Never escalate the mode on your own. If the request looks bigger than the chosen mode,
say so and ask.

## 2. Evidence

- Material pasted by the user (logs, stack traces, screenshots, SQL) is **fact**, not
  hypothesis. Never spend an agent confirming or refuting what the user provided.
- Every subagent receives that material **verbatim**, never paraphrased.
- Every claim about the code cites `file:line`. No citation = hypothesis, labeled as such.

## 3. Read-only until approval

- Diagnosis and plan edit nothing. The working tree leaves as it came in.
- This holds even when the fix looks obvious, even in one file, even in a test.
- Adjacent scope discovered along the way is **listed**, never touched.
- Implementation starts when the user approves the plan, and covers only what is in it.

## 4. Subagents

Rules for any spawn (`explorer`, `verifier` or ad hoc):

- One agent per concern. Before spawning, check whether another agent already covers
  the same question.
- Closed question: the answer is yes/no, a list, or a code excerpt. "Check whether X is
  correct" is forbidden.
- Complete input: question + raw material + files already known to be relevant.
- Budget: at most 15 tool calls. On reaching it, return what you have.
- Dependency sources (jars, Gradle/Maven cache, node_modules): only when the plan depends
  on a specific default or behavior. Once, one agent, a question of the form "what is the
  default of X in version Y". Record the answer as Confirmed with the source path.
- Output always in this format, no prose outside it:
  ```
  Confirmado: (file:line)
  Hipótese: (looks true, not seen in the code)
  Não verificado: (left outside the budget)
  ```

Model: `explorer` and `verifier` run on Sonnet by default. Opus only if the orchestrator
justifies in one line why Sonnet is not enough.

## 5. Verification

- Verify **only** items marked as Hypothesis that the plan depends on. Items Confirmed
  with `file:line`, and user evidence, are not verified.
- One `verifier` per hypothesis. At most 5 verifiers per task; beyond that the plan has
  too many hypotheses — go back to exploration or ask the user.
- The verifier receives: the exact hypothesis, the `file:line` that produced it, and the
  raw material.
- Conflict between explorer and verifier: the orchestrator decides by the cited evidence.
  If neither cites a line, the hypothesis goes to "Decisões pendentes", not into the plan.

## 6. Execution

- Execute from the plan file, in a fresh session (`/clear` first).
- No subagents by default. The plan is already the specification.
- At the end of each step, run the verification declared in the step. Failed: stop and
  report, do not improvise.
- One single final review allowed: "compare the diff with the plan and list divergences".
  Nothing beyond that.
- Adjacent scope that shows up during execution: list it, do not touch it.

## 7. What is a rule and what is a mechanism

- Subagent budgets (15/10 calls) and the read-only nature of `explorer`/`verifier` are
  enforced by the harness (`maxTurns`, `disallowedTools` in the frontmatter), not only by
  text.
- `/diag` and `/contention-test` have no `Edit`/`Write`. `/plan` has `Write` only, for
  `docs/plans/`. Writing anywhere else during a plan is a violation even when the harness
  allows it.
- The engineering guide (concurrency, data access, failure handling) lives in
  `.claude/rules/engineering.md` and applies to all code written or reviewed in this
  repository.
