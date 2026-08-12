# Project Generation

Sources: `vyne/cli/generation.py`, `vyne/cli/new.py`,
`vyne/cli/templates/` (template resources).

## The model

Scaffolding writes many files, so a crash must never leave a broken
project.  The generator stages every file into a temporary sibling
directory on the same filesystem and publishes the whole tree with a
single `os.replace` — atomic on POSIX, no partial states (GEN-14).

Generation follows an empty-target rule:

- the target must not exist, or be an empty directory
- a non-empty target is refused unless `--force` replaces it entirely
- existing files are never merged, preserved, or edited in place

There are no journals, backups, or per-file merge policies: an empty
target cannot conflict, and a forced replacement cannot partially fail.

## PlanBuilder

```python
builder = PlanBuilder(target)
builder.add_file("app.py", "...")
builder.add_file("android/gradlew", gradlew_bytes)
plan = builder.preflight()   # stages into a temp sibling; target untouched
plan.apply(force=force)      # os.replace(staging, target)
plan.cleanup()               # removes staging debris
```

Security invariants (checked at `add_file` time):

- no `..` segments
- no absolute paths

Symlink-escape attacks are moot: the target must be empty, so nothing
pre-existing inside it can be traversed, and a symlink target is
refused outright.

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

- single-file atomic write (temp sibling + `os.replace`)
- byte-identical skip when nothing changed

## Coverage

The generator is covered by `test_generation_transaction.py` and the
CLI acceptance tests (`test_acceptance_cli.py`,
`test_generated_python_project.py`).

## Related

- [commands.md](commands.md) — the CLI surface
- [testing.md](../testing/testing.md) — generation test suites
