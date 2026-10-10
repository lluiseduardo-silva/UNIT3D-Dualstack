# Engineering Guidelines

## Meta-rule: concepts over tools
- Every rule in this file must capture a **concept**, never a tool, engine,
  library, or language. Tools change between projects; the underlying
  mechanics don't. If a rule only makes sense for one specific technology,
  rewrite it until the principle stands on its own — concrete tools may
  appear only as illustrative examples, never as the rule itself.
- When applying any rule, translate the concept to the current stack and
  **verify how that stack actually implements the mechanism** (locking
  strategy, isolation semantics, queue guarantees vary by implementation).
  The concept tells you what to look for; the stack's documentation and
  observed behavior tell you what is true here.

## Concurrent writes to shared state
- **Default: one serialized write path per contended resource** (a table, a
  file, a shared structure). Multiple independent writers doing batch updates
  on the same resource acquire locks in different orders and can cycle-wait
  (deadlock) under load. If different operation types target the same
  resource, prefer making the operation a field of the queued item rather
  than creating a separate writer.
- **This is a default, not a law — the concept-level alternatives:**
    - **consistent acquisition order:** if all writers lock keys in the same
      deterministic order, cycles cannot form, even with multiple writers;
    - **cheap conflict recovery:** smaller batches plus retry-with-backoff
      turns deadlocks from fatal into cheap — acceptable on low-contention
      paths;
    - **non-blocking claim semantics:** if the platform offers a primitive to
      claim work without waiting on locked items, queue-consumption patterns
      can parallelize safely;
    - **disjoint partitioning:** writers that touch non-overlapping key ranges
      cannot conflict by design.
      Choose based on contention level and on how the current storage layer
      actually implements locking and isolation — semantics differ between
      systems and between configuration modes of the same system; verify, don't
      assume.
- **Verify, don't trust:** any claim about behavior under load (including
  this file) must be validated by forcing contention on purpose — many
  writers, small overlapping batches — and by reading whatever conflict/
  deadlock diagnostics the current platform exposes. Advice that was true
  for someone else's workload may not hold for this one.
- **Contention tests run against the real storage engine, never a stand-in.**
  Embedded or in-memory substitutes implement locking, isolation, deadlock
  detection and lock timeouts differently from the production engine, so a
  green test on a substitute is zero evidence about contention. Provision the
  same engine and version production uses, ephemerally, per test run
  (container-backed test infrastructure such as Testcontainers is the usual
  mechanism; use the idiomatic equivalent of the current stack). Force
  contention on purpose inside that test — many writers, small overlapping
  batches, mixed operation types — and assert on the engine's own diagnostics
  (deadlock log, lock views, conflict counters), not only on the final state.
  The same test is what surfaces engine-specific behavior that a substitute
  hides: constraint semantics, default isolation level, type coercion, lock
  escalation.
- **A contention test is part of the regular suite,** not a one-off run by
  hand. Gate it on container availability (skip loudly, never silently) so it
  runs on every developer machine and in CI that has a container runtime.
  Mirror production configuration in the container: isolation level, lock
  timeout, and any flag that changes locking behavior — list each with its
  value in the test, so drift is visible.
- **Test-infrastructure dependency versions come from the registry, not from
  memory.** Container-backed test libraries track the container runtime they
  drive, and a remembered version can be a major behind and silently
  incompatible with the runtime installed today. Look the current version up
  before declaring it, and check what the build actually resolves: a
  framework's dependency bundle (BOM, platform, lockfile) can pin an older
  major than the one you declared, so override it explicitly and verify the
  resolved version with the build tool's dependency report. (Illustrative:
  in JVM projects, Testcontainers 2.x is required with recent Docker, while
  Spring Boot and Quarkus BOMs may still resolve 1.x unless pinned.)
- Assume any concurrency bug invisible in casual testing WILL appear under
  real load. A quiet environment proves nothing about contention behavior.

## Schema & code design
- **Zero, one, or infinity.** If a design hardcodes exactly two (or N fixed)
  special cases, every code path duplicates — writes, expiry, validation,
  display — each with its own edge cases. Prefer the generic model (one code
  path over N records) even when the data model looks like overkill:
  complexity lives in code paths, not in model generality.
- Counterweight, so this rule isn't applied blindly either: generalizing has
  costs (indirection, aggregation, migration of existing access paths). The
  test is the **end state**, not the diff — pick whichever model leaves fewer
  branches and less duplicated logic after the dust settles, and prefer a
  one-time refactor over permanent compounding duplication.

## In-process concurrency (threads / async tasks)
- **Shared mutable state is the root cause; concurrency only exposes it.**
  Prefer, in order: no sharing (each worker owns its data), immutable sharing
  (read-only after construction), message passing (transfer ownership instead
  of sharing), and only then locking.
- **Check-then-act is a race.** Any pattern of "read a value, decide, then
  write" is broken under concurrency unless the read+decision+write happens
  atomically (a single atomic operation, a lock spanning all three, or a
  compare-and-swap loop). This includes "check if exists then create",
  "check balance then debit", "check flag then proceed".
- **Never hold a lock across a slow or unbounded operation** (network calls,
  disk I/O, waiting on another lock). Lock scope should cover state mutation
  only. Holding locks during I/O turns latency spikes into system-wide stalls.
- **Lock ordering must be global and consistent.** If any code path acquires
  A then B, no path may acquire B then A. Document the order where multiple
  locks exist; deadlocks between threads follow the exact same cycle-wait
  mechanics as database deadlocks.
- Concurrency bugs are probabilistic: a passing test proves the schedule
  tested, not the code. Stress with forced interleaving where possible, and
  treat "works on my machine" as zero evidence.

## Multi-instance concurrency (2+ copies of the same application)
- **Design every instance as if it is never alone.** Anything that works
  because "there's only one of us" — in-memory caches used as truth,
  scheduled jobs firing on every instance, local counters, "I'll check then
  insert" — breaks the day a second instance starts. Assume N instances from
  day one, even while running one.
- **Process memory is a cache, never the source of truth.** Authoritative
  state lives in shared storage; anything held locally must be safely
  reloadable, evictable, and tolerant of being stale.
- **Mutual exclusion across instances requires a shared arbiter** (a lock or
  lease in the shared storage layer, or single-consumer semantics from a
  queue). An in-process lock only excludes threads of the same instance.
  Leases must expire: a crashed holder must not block the system forever —
  which implies every holder must tolerate losing a lease it thinks it holds.
- **Idempotency is mandatory, not optional.** Messages, jobs, webhooks and
  retries are delivered at-least-once in any realistic system. Every consumer
  must produce the same end state when reprocessing the same input (natural
  idempotency, dedup keys, or conditional writes).
- **Let the storage layer be the final arbiter of invariants.** Uniqueness,
  referential integrity, and "exactly one active X" must be enforced by
  constraints in shared storage — application-level checks are advisory,
  because two instances can pass the same check simultaneously.
- **Concurrent modification needs explicit conflict strategy:** optimistic
  versioning (write succeeds only if the version read is still current) for
  low contention; arbiter-based exclusion for high contention. "Last write
  wins" is a decision too — make it consciously, never by accident.
- **Never trust clocks across machines.** Wall-clock timestamps from
  different instances are not ordered. Ordering requires a single sequencer,
  monotonic versions, or explicit causality — not comparing timestamps.
- **State change and its side effects can't be atomic across two systems.**
  If updating storage and emitting an event/notification must both happen,
  design for the gap: record the intent atomically with the state change and
  deliver from that record, or make the delivery reconcilable. Otherwise one
  of the two will eventually be lost.

- **Test multi-instance behavior with real multiplicity.** Run two or more
  copies of the consumer/job/scheduler against the same ephemeral,
  container-backed store and queue, and assert exactly-once outcomes,
  lease handover after a simulated crash, and idempotent reprocessing.
  A single instance against a mock proves none of this.

## Failure handling & external calls
- **Every external call gets a timeout.** No exceptions. An unbounded wait
  is a resource leak scheduled for the worst possible moment.
- **Retries need three companions:** backoff (don't hammer a struggling
  dependency), a retry budget/limit, and idempotency on the receiving side.
  Retrying a non-idempotent operation duplicates its effect.
- **Fail fast and loud at boundaries; be resilient inside.** Validate inputs
  where data enters the system and reject explicitly. Past the boundary,
  code should be able to trust its inputs — scattered defensive re-checks
  hide design confusion.
- **Partial failure is the normal case in any distributed operation.** For
  every multi-step process, answer at design time: what state remains if we
  crash between step N and N+1, and what detects and repairs it?

## Evolution & compatibility
- **Change shared contracts in expand → migrate → contract phases.** Schemas,
  message formats and APIs are consumed by code you don't deploy atomically
  with (old instances during rollout, external consumers). Add the new form,
  migrate readers/writers, only then remove the old. Never break in one step.
- **Every change must be safe to roll back.** If a deployment writes data the
  previous version can't read, rollback is gone as an option — that's a
  choice to be made explicitly, not discovered during an incident.

## Code quality (general)
- **Single source of truth for every fact.** Any knowledge duplicated in two
  places will eventually disagree; derive, don't copy. This applies to data,
  config, and business rules encoded in code.
- **Make invalid states unrepresentable where the language allows it.**
  Prefer designs where wrong combinations can't be constructed over designs
  that validate them after the fact.
- **Depth over surface in interfaces:** a good module hides a lot behind a
  small interface. If callers must understand the internals to use it
  correctly, the abstraction is a liability.
- **Errors are part of the interface.** Every function's failure modes are as
  much its contract as its return value: make them explicit, never swallow
  them silently, and never use exceptions/errors for expected control flow.
- **Optimize only measured bottlenecks.** Design for clarity first;
  performance work without measurement is guessing, and usually wrong about
  where the cost is.

## Data access & query patterns
- **Round trips dominate cost, not data volume.** Each query pays fixed
  latency (network, parsing, planning) regardless of size. One query
  returning 200 rows is dramatically cheaper than 200 queries returning one
  row each. Optimize for fewer round trips first, smaller payloads second.
- **The number of queries must be independent of the result size.** If
  loading N records triggers N (or N×M) additional queries — the classic
  N+1 — the design is broken regardless of how fast each query is. A list
  screen that is fine with 10 records will fall over with 10,000. The test:
  does query count grow with data? If yes, fix the access pattern, not the
  individual queries.
- **A query inside an iteration is the smell to hunt.** Any data access
  occurring per-element of a loop — directly, or hidden behind a lazily
  loaded relationship, a computed property, or a serializer touching
  relations — must be replaced by declaring the needed data upfront and
  fetching it in a bounded number of batched queries before iterating.
- **Declare the full data need at the entry point of the operation.** Decide
  what the use case requires (which records, which relations, which fields)
  and fetch it deliberately. Data access decided implicitly, deep inside
  rendering or serialization, is how hidden query storms are born.
- **Aggregate where the data lives.** Counting, summing, grouping, filtering
  and sorting belong to the storage layer, which is built for them — not to
  application code iterating over rows it fetched only to discard. Fetching
  a collection to compute its size is the same disease as N+1.
- **Counterweights, so this isn't applied blindly:**
    - fewer round trips ≠ one giant query: joining multiple independent
      collections in a single query multiplies rows combinatorially; a small
      constant number of batched queries (one per collection) is often
      cheaper than one exploding join. The target is *bounded*, not *one*;
    - don't over-fetch either: loading entire records and full relation trees
      "just in case" trades the round-trip problem for a payload/memory
      problem. Fetch the fields the use case needs;
    - unbounded result sets are their own failure: any query whose result
      grows with data needs pagination or streaming — "load everything and
      filter in memory" fails exactly like N+1, just all at once.
- **Verify, don't trust the abstraction.** Any layer that hides data access
  also hides access patterns. For every non-trivial flow, inspect what is
  actually executed (query logs, counters, tracing — whatever the platform
  exposes) and assert the expected query count where the tooling allows.
  The abstraction's convenience is real; its cost model is invisible until
  you look.