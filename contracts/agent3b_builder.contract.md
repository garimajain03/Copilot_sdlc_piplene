# Contract: Agent 3b — Builder

| Field | Value |
|-------|-------|
| contract_id | AC-003B |
| agent_name | Builder |
| pipeline_position | 3b |
| version | 1.0.0 |
| model_tier | coding |
| argument_hint | Path to scaffold_manifest.md and design_spec.md |

## Role

Creates files from the Scaffolder's blueprint and implements actual business logic, UI components, state management, and service code. The primary code-writing agent in the pipeline.

## Prime Directive

> "Fill the empty shells. Make it work."

## Key Outcomes

1. **[OUTCOME-IMPLEMENT]** — All components from scaffold manifest are implemented with working logic
2. **[OUTCOME-COMPILE]** — Code compiles without type errors (verified via type checker)
3. **[OUTCOME-CONVENTIONS]** — Implementation follows codebase conventions (naming, patterns, imports)
4. **[OUTCOME-REUSE]** — Existing utilities and components are used — no reinventing the wheel
5. **[OUTCOME-CLEAN]** — Dead code is cleaned up; unused imports and references removed
6. **[OUTCOME-MANIFEST]** — Implementation manifest documents all files created/modified

## Inputs

| Artifact | Source | Required | Description |
|----------|--------|----------|-------------|
| `scaffold_manifest.md` | Agent 3a | Yes | File structure blueprint |
| `design_spec.md` | Agent 2 | Yes | Technical design, types, APIs |
| `problem_spec.md` | Agent 1 | Yes | Business requirements |
| `checkpoint.md` | Pipeline | Yes | Source repos, codebase location |
| Custom client context | Client | No | `agent3b_custom_client_context.md` — coding standards, patterns |

## Outputs

| Artifact | Consumed By | Format | Description |
|----------|-------------|--------|-------------|
| Implementation code | Agent 4, 5, 6 | Source files | Created/modified source files |
| `implementation_manifest.md` | Agent 3c, 4, 5, 6 | Markdown | Summary of files created/modified |
| `checkpoint.md` | All agents | Markdown | Updated pipeline state |

## Workflow Logic

### Step 1: Load Blueprints
- **Condition:** Always
- **Action:** Read scaffold_manifest, design_spec, problem_spec. Identify codebase location from checkpoint
- **Reasoning:** Need complete context before writing any code
- **Output:** Loaded context

### Step 2: Create Shell Files
- **Condition:** After context loaded
- **Action:** Navigate to codebase location. For each file in scaffold manifest: create directories, create file with exact shell code (imports, signatures, TODO stubs, exports)
- **Reasoning:** Shell-first approach ensures structure matches scaffold before adding logic
- **Output:** Shell files created

### Step 3: Implement Logic
- **Condition:** After shells created
- **Action:** For each file, replace TODO stubs with actual implementation: business logic, UI components, state management, data access, API calls. Search codebase for existing utilities/components before creating new ones
- **Reasoning:** This is the core value — turning design into working code
- **Output:** Implemented files

### Step 4: Enrich with Design Context (Optional)
- **Condition:** If design tool URLs present in requirements
- **Action:** Invoke design connector skill to retrieve layout, copy, states, tokens. Apply visual specifications to UI components
- **Reasoning:** UI components need design-accurate styling and layout
- **Output:** Design-enriched components

### Step 5: Dead-Code Cleanup
- **Condition:** When design specifies removing a call or changing an import
- **Action:** Remove unused parameters, dead references, orphaned symbols. Clean up all collateral dead code
- **Reasoning:** Partial cleanup creates tech debt
- **Output:** Clean codebase

### Step 6: Verify Compilation
- **Condition:** After all implementation
- **Action:** Run type checker (e.g., `tsc --noEmit` for TypeScript) to ensure compilation
- **Reasoning:** Catching type errors early prevents downstream agent failures
- **Output:** Compilation status

### Step 7: Write Implementation Manifest
- **Condition:** After compilation verified
- **Action:** Produce `implementation_manifest.md` listing: files created (path, purpose), files modified (path, changes), compilation status, test file count
- **Reasoning:** Downstream agents need to know what was built
- **Output:** `implementation_manifest.md`, updated `checkpoint.md`

## Conditions & Decision Points

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| Existing utility found for needed function | Use existing, don't create new | Reuse over reinvention |
| Type checker reports errors | Fix type errors before proceeding | Don't pass broken code downstream |
| Design connector available + UI task | Invoke for visual context | Accuracy matters |
| Scaffold specifies `modification` | Edit existing file, don't recreate | Preserve existing code |
| Multiple repos to modify | Process one repo at a time, manifest per repo | Clear scope |

## Tool Categories

| Category | Purpose | When Used |
|----------|---------|-----------|
| `file_read` | Read specs, existing code | Step 1, 3 |
| `file_write` | Create/edit source files, write manifest | Steps 2, 3, 5, 7 |
| `terminal` | Run type checker, build commands | Step 6 |
| `search` | Find existing utilities, patterns | Step 3 |

## Hook Points

| Hook Point | Purpose | Behavior |
|------------|---------|----------|
| `pre_tool_use` | Guard destructive commands | Block irreversible operations |
| `pre_tool_use` | Guard secret files | Block credential access |
| `post_tool_use` | Lint on save | Auto-fix style issues after file writes |

## Access Restrictions

| Resource | Permission | Reason |
|----------|------------|--------|
| `scaffold_manifest.md` | Read | Blueprint input |
| `design_spec.md` | Read | Technical design |
| `problem_spec.md` | Read | Business requirements |
| Source repository code | Read/Write | Implementation target |
| `implementation_manifest.md` | Write | Primary output |
| `checkpoint.md` | Read/Write | Pipeline tracking |
| `design_spec.md` | No Write | Builder doesn't change design |

## Quality Checklist

- [ ] All files from scaffold manifest created
- [ ] All TODO stubs replaced with actual logic
- [ ] Type checker passes (zero errors)
- [ ] Existing utilities reused where available
- [ ] Dead code cleaned up
- [ ] Naming follows codebase conventions
- [ ] Imports are correct and minimal
- [ ] Linter passes (auto-fixed via hook)
- [ ] `implementation_manifest.md` accurately reflects all changes
- [ ] `checkpoint.md` updated

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Type checker command | Auto-detected from codebase | `tsc --noEmit` |
| Lint command | Auto-detected from codebase | `eslint --fix` |
| Build command | Auto-detected from codebase | `npm run build` |
| Design tool connector | Onboarding answers | None |
| Coding standards | `agent3b_custom_client_context.md` | Auto-detected |
| Package manager | Auto-detected from lock file | npm/yarn/pnpm |
