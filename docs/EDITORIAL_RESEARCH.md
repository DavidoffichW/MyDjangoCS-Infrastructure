# Editorial research note

The v0.1.0 editorial pass changed explanation and release metadata, not runtime behavior.
Its purpose was to make the system's central reliability question visible before presenting
its modules.

## Practices applied

The README now begins with a concrete lifecycle problem and follows one synthetic
investigation through the system. This problem-first structure was informed by the way the
following architecture studies introduce a small system through the constraint it must
solve, then expose component responsibilities and failure modes:

- [SQLAlchemy](https://aosabook.org/en/v2/sqlalchemy.html), for keeping lower-level contracts
  available beneath a higher-level composition surface;
- [DBDB: Dog Bed Database](https://aosabook.org/en/500L/dbdb-dog-bed-database.html), for using
  immutable structures and small persistence layers to make recovery understandable;
- [A Continuous Integration System](https://aosabook.org/en/500L/a-continuous-integration-system.html),
  for explaining component responsibilities alongside failure handling; and
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html), for keeping durability
  assumptions and commit boundaries chronological.

The memory discussion cites the official
[Rust ownership and borrowing chapter](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)
to clarify the source of the vocabulary and, equally importantly, the limit of the analogy:
this Python arena performs runtime checks and does not inherit compile-time lifetime
guarantees.

The HTTP explanation follows Django's documented callable middleware chain and
short-circuit behavior rather than treating middleware as an application service
([Django 5.2 middleware](https://docs.djangoproject.com/en/5.2/topics/http/middleware/)).

Finally, the document set separates explanatory reading from working reference material.
The README and architecture chapter develop understanding; contracts and conformance vectors
remain compact and precise. This follows the explanation/reference distinction described by
[Diátaxis](https://diataxis.fr/reference-explanation/).

## How the practices were used

- One fictional four-sensor experiment provides continuity across evidence, identity,
  admission, execution, artifacts, jobs, cache, and replay.
- The worked Alpha and Bravo means appear beside the policies that produce them, not as
  unexplained screenshots or claims.
- Database UUIDs, semantic identities, immutable artifacts, mutable lifecycle rows, and
  cache entries are named separately whenever they could be confused.
- The architecture chapter presents a chronological request path and a complete failure
  narrative for the filesystem/SQLite gap.
- The experiments chapter names actual tests, observed states, and the boundary of every
  claim.
- Windows and Linux commands explain what each operation demonstrates instead of presenting
  an undifferentiated setup block.

No wording or code was copied from the external references. They were used as examples of
clear technical exposition and are cited so readers can inspect the underlying discussions.
The restricted WellNet materials remain outside this repository and were not used as public
editorial content.
