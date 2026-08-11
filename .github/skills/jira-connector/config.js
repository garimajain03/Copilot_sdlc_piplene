import { config } from "dotenv";

config({ quiet: true });

const TOKEN_ENV = "JIRA_TOKEN";
const ENDPOINT_ENV = "JIRA_URL";
const DEFAULT_ENDPOINT = "https://your-org.atlassian.net/rest/api/3";

export function getToken() {
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {
    throw new Error(`Missing ${TOKEN_ENV} for jira connector.`);
  }
  return token;
}

export function getBaseUrl() {
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}
