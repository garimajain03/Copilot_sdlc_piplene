import { config } from "dotenv";

config({ quiet: true });

const TOKEN_ENV = "AZURE_DEVOPS_TOKEN";
const ENDPOINT_ENV = "AZURE_DEVOPS_URL";
const DEFAULT_ENDPOINT = "https://dev.azure.com";

export function getToken() {
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {
    throw new Error(`Missing ${TOKEN_ENV} for azure devops connector.`);
  }
  return token;
}

export function getBaseUrl() {
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}
