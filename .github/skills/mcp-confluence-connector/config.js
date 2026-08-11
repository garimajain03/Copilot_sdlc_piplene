export const CONNECTOR = {
  id: "confluence",
  displayName: "Confluence",
  serverName: "atlassian-confluence",
  supportedAuthModes: ["token", "oauth"],
  defaultAuthMode: "token",
  tokenEnv: ["ATLASSIAN_TOKEN"],
  optionalEnv: ["ATLASSIAN_URL"],
  oauthStatusKey: "confluence",
};
