export const CONNECTOR = {
	id: "jira",
	displayName: "Jira",
	serverName: "atlassian-jira",
	supportedAuthModes: ["token", "oauth"],
	defaultAuthMode: "token",
	tokenEnv: ["ATLASSIAN_TOKEN"],
	optionalEnv: ["ATLASSIAN_URL"],
	oauthStatusKey: "jira",
};
