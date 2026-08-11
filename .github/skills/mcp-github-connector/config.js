export const CONNECTOR = {
	id: "github",
	displayName: "GitHub",
	serverName: "github",
	supportedAuthModes: ["token", "oauth"],
	defaultAuthMode: "oauth",
	tokenEnv: ["GITHUB_TOKEN"],
	optionalEnv: [],
	oauthStatusKey: "github",
};
