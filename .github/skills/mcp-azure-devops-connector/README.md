# MCP Azure DevOps Connector

Reusable MCP connector helper for Azure DevOps integrations.

## Usage

```bash
node .github/skills/mcp-azure-devops-connector/index.js --command=help
```

## Commands

- `help`: List available commands and required configuration
- `validate-mcp-config`: Validate `.mcp.json` and auth readiness

## Security

- Do not put secrets in prompts.
- Use preflight commands for token collection or OAuth completion.
