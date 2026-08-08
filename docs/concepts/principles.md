# Principles: What Vyne Is

## The idea

Vyne is a framework for writing Android native UI in Python.

The core principle is:

> Python owns everything that matters. Kotlin stays thin.

Python owns:

- application state
- component execution
- element identity
- reconciliation (diffing)
- event dispatch
- animation policy
- the ordered native operation stream

Kotlin (Android) owns only:

- native View objects
- measurement and layout
- drawing
- input delivery
- accessibility
- animation frames (mechanical integration)

## The stack

```text
examples/app.py
-> vyne Python framework
-> Chaquopy-managed CPython
-> direct typed Kotlin transactions
-> native-view renderer
-> Android native views
```

Chaquopy embeds CPython (Python 3.14) into the Android app. Python calls
Kotlin methods directly through typed calls. There is no JSON message
envelope and no binary codec on the production path.

## Why this split

Python is the right owner for logic:

- components and state are programming concepts
- diffing is a tree algorithm
- event policy is decision-making

Kotlin is the right owner for platform work:

- Views are Android objects
- measurement and drawing are platform APIs
- frames are driven by the display clock

A thin native side means one framework logic, one place to fix bugs, and
one code path. It also means the renderer is mechanical: it trusts the
Python diff and executes it.

## Consequences

- The Python side is the single source of truth for what the UI is.
- The native side never invents policy. It preflights, applies, and
  reports.
- Errors fail loudly with clear paths (MODEL-02). Nothing is silently
  ignored.
- All values that cross the bridge are immutable and bridge-safe.
- At most one commit is in flight. The native side always answers.

## Status

The framework is an early alpha. APIs may change.

## Related

- [data-flow.md](data-flow.md) — how a render moves through the stack
- [core-model.md](core-model.md) — the data types in the pipeline
- [contributing/design-rules.md](../contributing/design-rules.md) — the invariants that protect this principle
