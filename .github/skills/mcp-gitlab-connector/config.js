export const CONNECTOR = {
	id: "gitlab",
	displayName: "GitLab",
	serverName: "gitlab",
	supportedAuthModes: ["token", "oauth"],
	defaultAuthMode: "token",
	tokenEnv: ["GITLAB_TOKEN"],
	optionalEnv: [],
	oauthStatusKey: "gitlab",
};
