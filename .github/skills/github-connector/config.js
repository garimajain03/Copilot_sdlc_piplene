import { config } from "dotenv";

config({ quiet: true });

const TOKEN_ENV = "GITHUB_TOKEN";
const ENDPOINT_ENV = "GITHUB_URL";
const DEFAULT_ENDPOINT = "https://api.github.com";

export function getToken() {
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {
    throw new Error(`Missing ${TOKEN_ENV} for github connector.`);
  }
  return token;
}

export function getBaseUrl() {
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}
