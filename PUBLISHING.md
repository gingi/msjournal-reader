# Publishing to ClawHub (journal-reader)

This repository contains dev artifacts (virtualenvs, local `.env`, caches, etc.).

For ClawHub, publish the trimmed bundle under:

- `publish/journal-reader/`

Build it with:

```bash
./scripts/build_publish_bundle.sh
```

That folder excludes:
- `.env` (secrets)
- `.venv*` (virtualenvs)
- `tests/`, `tmp/`, caches

## Example

From the repo root:

```bash
clawhub publish ./publish/journal-reader \
  --slug journal-reader \
  --name "journal-reader" \
  --version 0.1.0 \
  --tags latest \
  --changelog "Initial public release"
```

Then users can install via:

```bash
clawhub install journal-reader
```

Notes:
- Bump `--version` with semver for updates.
- Consider using `clawhub sync` once you’re happy with the workflow.
