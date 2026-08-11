import { config } from "dotenv";

config({ quiet: true });

const TOKEN_ENV = "CONFLUENCE_TOKEN";
const ENDPOINT_ENV = "CONFLUENCE_URL";
const DEFAULT_ENDPOINT = "** https://wiki.example.com";

export function getToken() {
  const token = process.env[TOKEN_ENV] || "";
  if (!token) {
    throw new Error(`Missing ${TOKEN_ENV} for confluence connector.`);
  }
  return token;
}

export function getBaseUrl() {
  return process.env[ENDPOINT_ENV] || DEFAULT_ENDPOINT;
}
