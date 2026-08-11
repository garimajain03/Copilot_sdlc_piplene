#!/usr/bin/env node
import axios from "axios";
import { getBaseUrl, getToken } from "./config.js";

function parseArgs() {
  const parsed = {};
  for (const arg of process.argv.slice(2)) {
    if (!arg.startsWith("--")) continue;
    const idx = arg.indexOf("=");
    const key = idx === -1 ? arg.slice(2) : arg.slice(2, idx);
    const value = idx === -1 ? "true" : arg.slice(idx + 1);
    parsed[key] = value;
  }
  return parsed;
}

function output(data, success = true, exitCode = 0) {
  const payload = success ? { success: true, data } : { success: false, error: data };
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  process.exitCode = exitCode;
}

async function callApi(path, method = "GET", body = null) {
  const response = await axios({
    method,
    url: `${getBaseUrl().replace(/\/+$/, "")}/${String(path || "").replace(/^\/+/, "")}`,
    headers: {
      Authorization: `Bearer ${getToken()}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    data: body,
  });
  return response.data;
}

async function main() {
  const args = parseArgs();
  const command = args.command || "help";

  try {
    if (command === "help") {
      output({
        connector: "github",
        requiredEnv: ["GITHUB_TOKEN"],
        commands: ["help", "test-connection", "request"],
      });
      return;
    }

    if (command === "test-connection") {
      const data = await callApi(args.path || "");
      output({ connector: "github", ok: true, data });
      return;
    }

    if (command === "request") {
      const method = String(args.method || "GET").toUpperCase();
      const body = args.body ? JSON.parse(args.body) : null;
      const data = await callApi(args.path || "", method, body);
      output({ connector: "github", data });
      return;
    }

    output(`Unknown command: ${command}`, false, 1);
  } catch (error) {
    const message = error?.response?.data || error?.message || String(error);
    output(message, false, 1);
  }
}

void main();
