# MCP Confluence Connector

Reusable MCP connector helper for Confluence integrations.

## Usage

```bash
node .github/skills/mcp-confluence-connector/index.js --command=help
```

## Commands

- `help`: List available commands and required configuration
- `validate-mcp-config`: Validate `.mcp.json` and auth readiness

## Security

- Do not put secrets in prompts.
- Use preflight commands for token collection or OAuth completion.
