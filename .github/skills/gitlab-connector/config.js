import { config } from "dotenv";

config({ quiet: true });

const TOKEN_ENV = "GITLAB_TOKEN";
const ENDPOINT_ENV = "GITLAB_URL";
const DEFAULT_ENDPOINT = "https://gitlab.com/api/v4";

export function getToken() {
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {
    throw new Error(`Missing ${TOKEN_ENV} for gitlab connector.`);
  }
  return token;
}

export function getBaseUrl() {
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}
