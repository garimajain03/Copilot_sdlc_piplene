# Contract: Skill - Design Connector

| Field | Value |
|-------|-------|
| contract_id | SC-DESIGN |
| skill_name | Design Connector |
| category | design |
| version | 1.0.0 |

## Role

Retrieves implementation-ready design context from design tools. Provides layout, interaction states, copy placement, design tokens, variables, and screenshots for frontend/mobile UI work.

## Supported Design Tools (Pluggable)

| Tool | Implementation | Detection |
|------|---------------|-----------|
| Figma | Figma MCP server / REST API | Design URLs contain `figma.com` |
| Sketch | Sketch API | Design URLs contain `sketch.com` |
| Adobe XD | XD API | Design URLs contain `xd.adobe.com` |

## Capabilities (Abstract)

| Capability | Description | Agents Using |
|------------|-------------|-------------|
| `check` | Verify design tool is reachable | Builder, Orchestrator |
| `get-design-context` | Layout, states, copy placement | Builder, Design Architect |
| `get-tokens` | Design tokens, spacing, colors, typography | Builder, Scaffolder |
| `get-screenshot` | Visual screenshot of design | Design Architect |

## Configuration

| Setting | Source |
|---------|--------|
| Design tool type | Auto-detected from URLs in tickets |
| MCP server endpoint | Setup script |
| Auth | Design tool app + Dev Mode |

## Customization Points

| Point | How Customized | Default |
|-------|---------------|---------|
| Design tool | Auto-detected | Figma |
| Token format | `skill_design_custom.md` | CSS variables |
| Screenshot resolution | `skill_design_custom.md` | 2x |

