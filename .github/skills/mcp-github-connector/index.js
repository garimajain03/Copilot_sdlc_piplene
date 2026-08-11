#!/usr/bin/env node
import fs from "fs";
import path from "path";
import { CONNECTOR } from "./config.js";

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

function loadJson(jsonPath) {
	if (!fs.existsSync(jsonPath)) {
		throw new Error(`MCP config not found: ${jsonPath}`);
	}
	return JSON.parse(fs.readFileSync(jsonPath, "utf8"));
}

function findServer(payload, serverName) {
	const servers = payload?.mcpServers;
	if (!servers || typeof servers !== "object") return null;
	return servers[serverName] || null;
}

function checkTokenEnv(requiredEnv) {
	return requiredEnv.filter((name) => !String(process.env[name] || "").trim());
}

function checkOauthStatus(statusPath, oauthStatusKey) {
	if (!fs.existsSync(statusPath)) return false;
	const payload = JSON.parse(fs.readFileSync(statusPath, "utf8"));
	return Boolean(payload?.completed?.[oauthStatusKey]?.completed_at);
}

function normalizeValue(value) {
	return String(value || "")
		.trim()
		.toLowerCase()
		.replace(/[_-]+/g, " ")
		.replace(/\s+/g, " ");
}

function loadSelectedAuthModes(inventoryPath, connectorId, category, supportedModes, defaultMode) {
	if (!fs.existsSync(inventoryPath)) {
		return { modes: [defaultMode], source: "default(no-inventory)" };
	}

	const payload = JSON.parse(fs.readFileSync(inventoryPath, "utf8"));
	const connectors = Array.isArray(payload?.connectors) ? payload.connectors : [];
	const normalizedId = normalizeValue(connectorId);
	const normalizedCategory = normalizeValue(category);
	const selected = new Set();

	for (const row of connectors) {
		if (normalizeValue(row?.mode) !== "mcp") continue;
		if (normalizeValue(row?.platform) !== normalizedId) continue;
		if (normalizedCategory && normalizeValue(row?.category) !== normalizedCategory) continue;
		const auth = normalizeValue(row?.auth);
		if (supportedModes.includes(auth)) selected.add(auth);
	}

	const modes = [...selected];
	return modes.length ? { modes, source: "inventory" } : { modes: [defaultMode], source: "default(no-match)" };
}

function validateMcpConfig(args) {
	const cwd = process.cwd();
	const mcpJson = path.resolve(cwd, args["mcp-json"] || "outputs/agents-repo/.mcp.json");
	const oauthStatus = path.resolve(cwd, args["oauth-status"] || ".github/sdlc-pipeline/mcp_oauth_status.json");
	const inventoryPath = path.resolve(cwd, args.inventory || ".github/sdlc-pipeline/connector_inventory.json");
	const category = String(args.category || "").trim();

	const payload = loadJson(mcpJson);
	const server = findServer(payload, CONNECTOR.serverName);
	if (!server) throw new Error(`Server '${CONNECTOR.serverName}' is missing from ${mcpJson}`);

	const selection = loadSelectedAuthModes(
		inventoryPath,
		CONNECTOR.id,
		category,
		CONNECTOR.supportedAuthModes || ["token", "oauth"],
		CONNECTOR.defaultAuthMode || "token"
	);

	const selectedAuthModes = selection.modes;
	const requiresToken = selectedAuthModes.includes("token");
	const requiresOauth = selectedAuthModes.includes("oauth");
	const missingEnv = requiresToken ? checkTokenEnv(CONNECTOR.tokenEnv || []) : [];
	const oauthCompleted = requiresOauth ? checkOauthStatus(oauthStatus, CONNECTOR.oauthStatusKey) : null;

	const result = {
		connector: CONNECTOR.id,
		displayName: CONNECTOR.displayName,
		selectedAuthModes,
		authModeSource: selection.source,
		category: category || "all",
		serverName: CONNECTOR.serverName,
		mcpJson,
		oauthStatus,
		inventoryPath,
		requiredEnv: requiresToken ? CONNECTOR.tokenEnv || [] : [],
		missingEnv,
		oauthCompleted,
		serverConfigured: true,
		ready: (!requiresToken || missingEnv.length === 0) && (!requiresOauth || oauthCompleted === true),
	};

	return result;
}

async function main() {
	const args = parseArgs();
	const command = args.command || "help";

	try {
		if (command === "help") {
			output({
				connector: CONNECTOR.id,
				serverName: CONNECTOR.serverName,
				supportedAuthModes: CONNECTOR.supportedAuthModes,
				defaultAuthMode: CONNECTOR.defaultAuthMode,
				options: ["--inventory=<path>", "--category=<pm|scm|knowledge>"],
				commands: ["help", "validate-mcp-config"],
			});
			return;
		}

		if (command === "validate-mcp-config") {
			const data = validateMcpConfig(args);
			output(data, true, data.ready ? 0 : 1);
			return;
		}

		output(`Unknown command: ${command}`, false, 1);
	} catch (error) {
		output(error?.message || String(error), false, 1);
	}
}

void main();
