# Domain Docs

Pixel Pet is a single-context repository.

## Read before engineering work

- Root `CONTEXT.md` contains canonical behavior language and verification decisions.
- Root `docs/adr/` contains architectural decisions when present.
- Lowercase `context.md` is implementation history, not the canonical glossary.

Use terms from `CONTEXT.md` in issues, PRDs, tests, and architecture proposals. Do not substitute terms listed under `_Avoid_`.

If a proposed change conflicts with an ADR, identify the conflict explicitly rather than silently overriding it.
