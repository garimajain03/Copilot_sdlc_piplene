# Contract: Hook — Lint on Save

| Field | Value |
|-------|-------|
| contract_id | HC-LINT |
| hook_name | Lint on Save |
| event | post_tool_use |
| version | 1.0.0 |

## Purpose

After any file write/edit operation, automatically runs the project's configured linter with auto-fix enabled. Catches style issues immediately rather than accumulating them.

## Trigger Conditions

- Fires after `file_write` / `file_edit` tool completes successfully
- Only on source code files (language-specific extensions)

## Guard Logic

### File Extension Filter (Configurable)

| Language | Extensions |
|----------|------------|
| JavaScript/TypeScript | `.js`, `.ts`, `.jsx`, `.tsx` |
| Python | `.py` |
| CSS/SCSS | `.css`, `.scss`, `.less` |
| HTML/Templates | `.html`, `.vue`, `.svelte` |

### Lint Command Resolution

1. Check project config for linter (auto-detected from codebase scan)
2. Run linter with `--fix` flag on the saved file
3. Report remaining unfixable issues

## Exit Codes

| Code | Meaning | Agent Behavior |
|------|---------|----------------|
| `0` | Clean — no issues or all auto-fixed | Normal |
| `2` | Unfixable lint errors remain | Errors fed to agent for manual fix |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Linter tool | Auto-detected from codebase | ESLint |
| Lint command | Auto-detected from package.json scripts | `npx eslint --fix` |
| File extensions | Auto-detected | Language-specific |
| Disable for certain paths | `hook_lint_custom.md` | None |
