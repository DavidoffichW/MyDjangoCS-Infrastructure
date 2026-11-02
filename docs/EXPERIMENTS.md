# Adversarial experiments

The laboratory is useful only if it can show what survives a failure, not merely that the
happy path returns `200`. These case studies describe the tested setup, injected pressure,
observed durable state, and limit of each conclusion.

The suite combines Django `TransactionTestCase`, independent database connections, real
subprocess termination, property-based inputs, HTTP tests, and Chromium workflows. An
intentionally raised exception is described as an exception; only tests that terminate a
child process are described as crash experiments.

## Competing idempotent submissions

**Question.** Can two independent requests with the same idempotency scope and key create two
authoritative jobs?

`test_identical_concurrent_admission_returns_one_authoritative_job` opens independent SQLite
connections in two threads, releases both submissions at a barrier, and submits the same
canonical command under `concurrent-key`. Both calls return, but the database contains one
job and one admitted event. One response reports creation and the other reports the existing
authoritative job.

`test_conflicting_concurrent_admission_has_one_winner_and_one_conflict` repeats the setup
with different command bodies under the same key. Exactly one request commits. The other
receives `IdempotencyConflict`; the database still contains one job and one admission event.
Sequential HTTP coverage in
`test_duplicate_and_conflicting_posts_have_distinct_outcomes` confirms the same distinction
through the HTMX endpoint: an equivalent decimal spelling is a duplicate, while a different
input is an HTTP 409 conflict.

The guard is the database uniqueness constraint plus canonical command digest, not HTMX
request synchronization. The claim is scoped to one SQLite database and the declared key
scope; it is not a global distributed idempotency service.

## Order is part of a command

**Question.** Could canonical key sorting accidentally erase the order of scientific or
workflow operations?

`test_reordered_operations_change_command_identity` admits a two-step workflow, moves the
second operation before the first, and admits it again. The snapshots and command digests
differ. Canonicalization orders object keys; it does not sort arrays whose order is semantic.

`test_workflow_mutation_does_not_change_admitted_snapshot` then edits an authoring row after
admission. Execution still follows the admitted snapshot and produces the original value.
`test_direct_admitted_command_mutation_is_rejected` confirms both model validation and the
database trigger reject attempts to rewrite that snapshot.

This protects admitted commands from later authoring changes. It does not make an editable
draft immutable before admission.

## Competing claims and stale finalization

**Question.** SQLite ignores `SELECT FOR UPDATE`; what stops two workers from accepting the
same job?

`test_competing_claims_have_one_controlled_winner` uses independent connections and a
barrier. The claim function enters a short `BEGIN IMMEDIATE` transaction and performs a
conditional update from `admitted` to `running`. One caller records attempt 1; the other
receives `InvalidTransition`. The database contains one running attempt and the ordered
events `admitted, running`.

`test_competing_execution_requests_have_one_successful_attempt` extends the experiment
through calculation and finalization. One request reaches succeeded and the other is
rejected; only one execution attempt exists.

The scientific path adds claim generations and owner tokens. In
`test_stale_attempt_cannot_finalize_after_owner_confirmed_recovery`, recovery fences the old
claim and a later attempt receives new ownership. Finalization with the old claim cannot
match the job row and fails without changing the new lifecycle. This is fencing inside the
tested single-host store, not a lease protocol for distributed workers.

## Result bytes published before database finalization

**Question.** What happens when an immutable result survives but the transaction that would
make it authoritative does not?

`test_published_result_without_database_commit_is_recoverable_orphan` starts a child process
against a temporary database and artifact directory. The child claims and computes a job,
publishes the result bytes, and exits with code 91 before the result row and succeeded
transition commit.

After restart, the observations are precise:

- the job remains `running`;
- no result identity or successful attempt is recorded;
- SQLite contains the three registered source/state artifacts;
- the store contains one additional digest;
- reconciliation reports exactly one orphan.

The recovery command requires confirmed worker termination, marks the attempt interrupted,
and fences the claim. An explicit requeue and new execution then complete normally. Because
the operation is deterministic, the previously orphaned bytes may be byte-identical to the
later valid result, but identity of bytes does not retroactively make the first lifecycle
successful.

`test_state_publication_without_database_registration_is_reconciled_as_orphan` exercises the
same boundary earlier in the pipeline: a process exits after publishing evidence, manifest,
and state bytes but before registering the research run. Reconciliation reports three
orphans and invents no authority rows.

## Process termination at transaction boundaries

The crash suites place explicit `os._exit()` points around authoritative changes and reopen
the stores from a new process.

| Boundary | Test | Durable observation |
| --- | --- | --- |
| before claim commit | `test_process_exit_before_claim_commit_rolls_back_every_claim_record` | no running transition or attempt survives |
| after claim commit | `test_process_exit_after_claim_fails_closed_until_recovery` | job remains running and cannot be replayed without recovery |
| during calculation | `test_process_termination_during_calculation_leaves_no_result` | claim survives; no result survives |
| before finalization | `test_process_termination_before_finalization_leaves_no_result` | no successful result or event appears |
| after successful commit | `test_process_exit_after_success_commit_preserves_one_result` | one succeeded job and one succeeded attempt remain |
| during recovery | `test_process_termination_during_recovery_rolls_back_reconciliation` | recovery transition rolls back; job remains running |

The parallel scientific suite repeats the artifact-specific boundaries and verifies claim
fencing. These tests establish fail-closed behavior for the listed local persistence points.
They do not simulate sudden power loss below SQLite or the filesystem, storage-controller
faults, or distributed partitions.

## Corruption and missing blocks

**Question.** Can database metadata or cached JSON hide damaged authoritative bytes?

`test_reconciliation_reports_corruption_and_orphans_without_deleting` publishes registered
artifacts, damages one, adds an unregistered block, and runs reconciliation. The registered
record is marked corrupt and the unknown digest is reported. Reconciliation does not delete
either by default.

`test_corrupt_result_artifact_fails_closed_before_cache` damages a succeeded result artifact
and requests it through the HTTP endpoint. The verifier detects the mismatch before HTML is
rendered or cached. There is no fallback to the job's JSON field. Binary coverage in
`test_checksum_and_length_corruption_are_rejected` independently confirms that a changed
record payload and a truncated message both fail decoding.

The store checks known identities and finite bounds. It does not provide replication or
self-healing; an operator needs a valid source to restore missing content.

## Memory conflicts and stale handles

**Question.** Can callers observe aliasing and lifetime violations rather than silently
sharing mutable byte arrays?

`test_readers_conflict_with_writer_and_release` holds a shared borrow, then verifies that an
exclusive borrow and release both fail. `test_cross_thread_readers_are_allowed_and_writer_is_rejected`
holds readers in two threads and observes the same controlled writer rejection.
`test_expired_borrow_cannot_access_or_mutate` keeps a token past its context and confirms both
read and write fail. `test_complete_lifecycle_and_generation_reuse` releases an allocation,
reuses its slot, and shows the old generation cannot access the new bytes.

Property-based `test_owned_bytes_round_trip_property` checks arbitrary bounded byte payloads
through allocation, exclusive write, shared read, sealing, and release. These are runtime
protocol checks for cooperative Python code. They do not prevent a malicious extension from
accessing process memory and do not approximate Rust's compile-time proof.

## Independent deterministic replay

**Question.** Is a repeat result stable across processes and operational records?

`test_independent_processes_replay_to_identical_results` executes the same deterministic
workflow in separate processes and compares the committed results. The foundation-level
reference experiment goes further by using two distinct idempotency keys and job UUIDs while
expecting one scientific result identity:

```text
result:sha256:7d32c02fdb42164d1d1f681906afbe27c380240ec61dc57ba62923ced7adf291
```

The expected Alpha and Bravo means are also calculated independently in
`test_time_window_means_match_independent_decimal_calculation`. A stable digest alone would
only prove stable serialization; the independent Decimal calculation tests the arithmetic
contract.

Determinism holds for the declared schemas, Decimal policy, supported operations, and
environment assumptions. It is not a claim that arbitrary external libraries, time sources,
or side effects are reproducible.

## HTML and HTMX cache isolation

**Question.** Can a cached fragment be returned as a full page, or can mutable job state be
mistaken for a result?

`test_result_cache_separates_full_page_and_htmx_fragment` requests the same successful job as
ordinary HTML and as HTMX. Each representation produces its own miss then hit. The full page
contains a document shell; the fragment does not. Both responses carry `Vary: HX-Request`,
and the cache key includes the representation variant.

`test_mutable_job_state_is_never_served_as_result` requests an admitted job and receives a
409 without cache headers. `test_failed_and_interrupted_jobs_never_enter_result_cache`
repeats the check for both terminal failure and recovered interruption.
`test_cache_reset_and_distinct_immutable_results_do_not_cross_contaminate` proves two result
artifacts keep distinct entries and that clearing the cache causes a harmless miss.

The test uses Django's local-memory cache and private responses. Shared proxy behavior and
multi-tenant authorization are outside the accepted deployment model.

## Middleware and browser behavior

The request trace is tested for normal views, HTMX fragments, CSRF rejection, a deliberate
guard short circuit, converted view exceptions, converted inner-middleware exceptions,
invalid correlation IDs, and concurrent request contexts. Domain events remain separate
from middleware observations.

Six Chromium cases exercise the complete browser and server path:

- build and execute a dynamic workflow;
- observe a controlled operation failure and recover;
- double-submit while retaining server-side idempotency and enforce CSRF;
- edit, add, reorder, remove, and reject stale form state;
- use ordinary HTML forms without JavaScript;
- open, admit, execute, and verify the scientific workbench.

Browser coverage checks behavior through a real HTTP server. It is not a cross-browser or
accessibility certification.

## Experiment matrix

| Hypothesis | Injected pressure | Required invariant | Evidence | Limitation |
| --- | --- | --- | --- | --- |
| one key identifies one admitted command | concurrent equal and conflicting submissions | one authority row; conflict on changed body | `test_adversarial` admission cases | one SQLite database |
| only one worker owns a claim | concurrent claims and execution | one running/successful attempt | claim and execution race cases | single-host fencing |
| publication does not imply authority | terminate after artifact publication | orphan reported; no success | `test_scientific_crash_recovery` | no disk-controller fault model |
| stale workers cannot finalize | recover then use old claim | conditional finalization rejects old token | `test_scientific_integration` | positive stop confirmation is external |
| corruption is not hidden | alter result bytes | read fails before cache | `test_scientific_http` | no automatic repair |
| mutable aliasing is controlled | overlapping borrow/release attempts | conflicts and stale handles fail | `test_memory_binary_store` | cooperative runtime checks |
| replay is semantically stable | independent jobs/processes | equal independently checked output | foundation and crash tests | supported deterministic operations only |
| representations do not cross | page/fragment requests and cache reset | separate keys, `Vary`, no mutable caching | `test_http` cache cases | local-memory cache |

## Qualification record

The released v0.1.0 source commit,
`f59da3b0722195db350c2856ceaedc36ec1b6fb9`, passed GitHub Actions run
[41281782301](https://github.com/DavidoffichW/MyDjangoCS-Infrastructure/actions/runs/41281782301):
Windows and Ubuntu on Python 3.12 and 3.13, including 108 Django tests, six
Chromium tests, Ruff, dependency checks, and migration checks.

Later documentation changes still need their own CI run before merge. A green
run establishes the checked commit, not every future revision.
