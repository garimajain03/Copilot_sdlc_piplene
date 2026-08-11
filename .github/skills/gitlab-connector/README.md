# Gitlab Connector

Template-generated CLI connector for API integrations.

## Usage

```bash
node .github/skills/gitlab-connector/index.js --command=help
```

## Commands

- `help`: List available commands
- `test-connection`: Validate API token and endpoint
- `request`: Execute an authenticated request against the connector endpoint

## Security

- Keep tokens outside source code and prompts.
- Prefer encrypted token handling in preflight artifacts.