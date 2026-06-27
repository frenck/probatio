# ADR-009: Call-time validation context

**Date**: 2026-06-27
**Status**: Accepted

**Context**: Some validation depends on runtime state that is not known when the
schema is built. The set of allowed entity ids, the current user's permissions, a
set of valid choices loaded from a database. Today there are two ways to express
that, both unsatisfying. You close over the state when you build the schema, which
makes the schema single-use and forces a rebuild per request. Or you rebuild the
schema on every call, paying the compile cost each time. voluptuous has no channel
for handing per-call state to validators, so neither does probatio.

mashumaro has the adjacent idea: a `context` object passed into (de)serialization
that hooks can read. The validation analog is to let one compiled schema validate
against state supplied per call.

**Decision**: Add an optional `context` to the call: `schema(data, context=...)`,
defaulting to `None` so `schema(data)` is unchanged. The context is any object,
opaque to probatio. It is exposed to validators that opt in through a documented
accessor (`current_context()`), backed by a `ContextVar` set for the duration of
the outermost call and reset on exit. A validator that does not need context never
mentions it and keeps the plain `validator(value)` shape.

**Rationale**:

- It keeps the validator contract intact. Every validator stays `validator(value)`,
  so existing validators and the voluptuous drop-in promise are untouched. The
  context arrives out of band through the accessor, not as a second argument that
  every nested validator would have to forward.
- A `ContextVar` is the correct primitive, and one we already use (the serde
  options in `serde/_config.py`). It is async- and thread-safe, and it makes the
  context visible to deeply nested validators without threading it through every
  intermediate call by hand. A thread-local would mishandle asyncio.
- It turns a per-call rebuild into a reuse. One compiled schema serves many calls
  with different state, which is the whole point of compiling a schema once.

**Consequences**: A new public accessor (`current_context()`) and a new optional
call argument, both additive. Points to fix in the design and the docs:

- **Absence.** When no context is set, `current_context()` returns `None`, and a
  validator that reads it decides what that means. A context-reading validator is
  therefore not standalone; it documents that it expects a context, and degrades
  honestly when there is none.
- **Re-entrancy.** The `ContextVar` is set at the outermost `Schema.__call__`.
  A nested `schema(data, context=other)` overrides within its own subtree and
  restores on exit; a nested call that passes no context inherits the outer one.
- **Contract.** The safe-validator invariant still binds: a context-reading
  validator must only ever raise `Invalid`.
- **Cost.** Setting and resetting a `ContextVar` happens only when a context is
  actually passed; `schema(data)` skips it entirely, so the common path pays
  nothing.
- **Stack budget.** The context-setting code lives in its own method, not inline
  in `__call__`, so it never adds a frame to the recursive `Self`/`$ref` path that
  the depth guard is tuned against. The context call sets the var once and
  re-enters the common path; the recursion below runs with the var already set.
