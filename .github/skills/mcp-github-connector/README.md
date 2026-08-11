# MCP GitHub Connector

Reusable MCP connector helper for GitHub integrations.

## Usage

```bash
node .github/skills/mcp-github-connector/index.js --command=help
```

## Commands

- `help`: List available commands and required configuration
- `validate-mcp-config`: Validate `.mcp.json` and auth readiness

## Security

- Do not put secrets in prompts.
- Use preflight commands for token collection or OAuth completion.
