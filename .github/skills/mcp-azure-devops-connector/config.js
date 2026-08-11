export const CONNECTOR = {
	id: "azure devops",
	displayName: "Azure DevOps",
	serverName: "azure-devops",
	supportedAuthModes: ["token", "oauth"],
	defaultAuthMode: "token",
	tokenEnv: ["AZURE_DEVOPS_TOKEN"],
	optionalEnv: ["AZURE_DEVOPS_URL"],
	oauthStatusKey: "azure devops",
};
