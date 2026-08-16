# Repository agent asset ownership

Status as of 2026-08-16: personal/local tooling, excluded from the product PR.

- `.claude/` and `.codex/` are workstation configuration. In particular,
  `.codex/hooks.json` contains `/home/gtc/...` absolute paths and is not portable.
- `.agents/` and `skills-lock.json` are not product firmware inputs. They may be
  proposed later in a separate tooling PR only after the team explicitly adopts
  repository-managed skills, reviews their upstream sources and hashes, and
  defines an update owner.
- None of these paths may be used as a release, build, test, or evidence
  dependency while they remain locally owned.

The root `.gitignore` enforces this boundary. A future tooling PR must remove
only the relevant ignore entries and must not bundle that policy change with a
firmware/product PR.
