---
name: contention-test
description: Specifies a contention test (deadlock, lost update, lock ordering, idempotency) against the real database/queue engine in an ephemeral container (Testcontainers or the stack's equivalent). Use when the user types /contention-test, or from /plan when the change touches concurrent writes.
argument-hint: "<contended resource and competing operations>"
disable-model-invocation: true
disallowed-tools: Edit, Write, NotebookEdit
---

Specify (do not implement) a contention test for the scenario below. The output is a
specification an executor implements without deciding anything. Write it in Brazilian
Portuguese; keep code, commands and dependency coordinates verbatim.

## Principle
A concurrency test is only worth anything against the **same engine and version as
production**. Embedded or in-memory substitutes implement locking, isolation and deadlock
detection differently: green on them is zero evidence. The engine starts in an ephemeral
container per test run (Testcontainers is the usual mechanism; use the idiomatic
equivalent of the current stack and confirm in its documentation how the image and
version are declared).

## Discover before writing (one `explorer`, closed question)
- Which engine and version production uses (deploy config, docker-compose, migrations).
- Whether container-based test infrastructure already exists in the project. Reuse it;
  do not duplicate.
- Which code paths write to the contended resource, with `file:line`.

## The specification must contain
1. **Contended resource** and the competing operations (type, batch size, key order).
2. **Forced scenario**: N concurrent writers, small overlapping batches, mixed
   operations. Concrete numbers (e.g. 8 writers × 50 batches × 20 keys with 50% overlap).
   The scenario must be aggressive enough that the failure, if present, shows up on every
   run, not one in a hundred.
3. **Assertions**:
   - no deadlock reported by the engine's diagnostics (name which diagnostic, e.g.
     deadlock log, lock view, conflict counter);
   - final state equal to the expected one (no lost update, no duplicate);
   - reprocessing the same input yields the same state (idempotency), where applicable.
4. **Engine isolation and config** in the container equal to production (isolation
   level, lock timeout, relevant flags). List each with its value.
5. **How it runs**: suite command, Docker prerequisite, and how the test is skipped (not
   silenced) when Docker is absent.
6. **Where it lives**: test file path following the project's convention.

## Dependencies: verify online, never from memory
- Before naming any test-infrastructure dependency (Testcontainers or equivalent), look
  it up in the official registry (Maven Central, npm, PyPI, NuGet, etc.) and cite the
  current version found. A remembered version is a hypothesis, not a fact.
- **Java/Kotlin, known gotcha:** current Testcontainers is the **2.x** line
  (`org.testcontainers:testcontainers-bom`). The 1.x line, which tends to come from
  memory, **does not work with recent Docker**. Spring Boot and Quarkus may pull 1.x
  through their own BOM; in that case the specification must explicitly say to import
  the Testcontainers 2.x BOM before the framework BOM, or pin the version with
  `constraints`/`resolutionStrategy` in Gradle (or `dependencyManagement` in Maven), and
  include a verification step: `gradle dependencyInsight --dependency testcontainers`
  (or `mvn dependency:tree`) showing the resolved 2.x version.
- Other languages: no known incompatibility, but the online check applies equally.

## Do not
- Do not replace the engine with an in-memory version "to be fast".
- Do not shrink the scenario until it passes. If it passes easily, the scenario is weak.
- Do not implement. Deliver the specification.

Scenario: $ARGUMENTS
