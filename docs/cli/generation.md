# Project Generation

Sources: `vyne/cli/generation.py`, `vyne/cli/new.py`,
`vyne/cli/templates/` (template resources).

## The problem

Scaffolding writes many files. A crash halfway leaves a broken project.
The generator solves this with a durable, recoverable transaction
(GEN-14).

## Transaction phases

```text
1. SCAN       — build an immutable plan with target snapshots
2. STAGE      — copy/encode all files into a same-filesystem staging dir
3. REVALIDATE — check target snapshots have not changed since scan
4. PUBLISH    — rename staging into place (with backups for existing)
5. COMMIT     — remove backups (success) or restore from backups (failure)
6. RECOVER    — detect interrupted published/backed-up states next run
                and complete or restore deterministically
```

Every input and destination is checked before any target mutation. No
fallible mutation occurs after publication.

## ManagedFile

Each generated path is a `ManagedFile`:

- `relative` — path relative to the project root
- `content` (bytes) or `source_dir` (directory copy)
- `policy` — how to handle an existing file that differs:
  - `ERROR` — raise
  - `SKIP` — leave the existing file untouched
  - `REPLACE` — overwrite via staging + backup

Security invariants:

- no `..` segments
- no absolute paths
- no symlink intermediates that resolve outside the target

Symlink escapes through managed parents are checked during plan
validation.

## Templates

The literal project files scaffolded by `vyne new` live in
`vyne/cli/templates/` (Gradle build files, settings, manifest, gradle
properties). They ship as package resources so generation works from an
installed wheel; `vyne.cli.templates.load(name)` reads one template.

## Android host packaging

`setup.py` assembles the Android host into `vyne/base_project` during
wheel builds:

- gradlew and wrapper
- `android/host/src/main` -> `base_project/android-host/src/main`

The generated `ExtensionRegistrant.kt` is per-project (it references the
project's extensions), so it is excluded from the packaged base.

## Extension registrant

`vyne build` regenerates `ExtensionRegistrant.kt` from the discovered
`extensions/*/extension.toml` files:

- journaled (transactional)
- byte-identical skip when nothing changed

## Failure injection

The generator is covered by failure-injection tests
(`test_generation_fault_matrix.py`, `test_generation_transaction.py`,
`test_generated_python_project.py`) that verify recovery from
interrupted phases.

## Related

- [commands.md](commands.md) — the CLI surface
- [testing.md](../testing/testing.md) — generation test suites
