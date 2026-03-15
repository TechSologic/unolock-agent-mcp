#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const https = require("https");
const { spawn } = require("child_process");

const PACKAGE_VERSION = "0.1.16";
const FALLBACK_BINARY_VERSION = "0.1.16";
const REPO = "TechSologic/unolock-agent-mcp";

function platformAssetInfo() {
  const platform = process.platform;
  const arch = process.arch;
  if (platform === "linux" && arch === "x64") {
    return { asset: "unolock-agent-mcp-linux-x86_64", executable: "unolock-agent-mcp-linux-x86_64" };
  }
  if (platform === "darwin" && arch === "arm64") {
    return { asset: "unolock-agent-mcp-macos-arm64", executable: "unolock-agent-mcp-macos-arm64" };
  }
  if (platform === "darwin" && arch === "x64") {
    return { asset: "unolock-agent-mcp-macos-x86_64", executable: "unolock-agent-mcp-macos-x86_64" };
  }
  if (platform === "win32" && arch === "x64") {
    return { asset: "unolock-agent-mcp-windows-amd64.exe", executable: "unolock-agent-mcp-windows-amd64.exe" };
  }
  throw new Error(`Unsupported platform for UnoLock Agent MCP binary: ${platform}/${arch}`);
}

function cacheRoot() {
  if (process.platform === "win32") {
    return process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  }
  return process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
}

function metadataPath() {
  return path.join(cacheRoot(), "unolock-agent-mcp", "release.json");
}

function binaryPath(releaseVersion) {
  const { executable } = platformAssetInfo();
  return path.join(cacheRoot(), "unolock-agent-mcp", releaseVersion, executable);
}

function binaryUrl(releaseVersion) {
  if (process.env.UNOLOCK_AGENT_MCP_BINARY_URL) {
    return process.env.UNOLOCK_AGENT_MCP_BINARY_URL;
  }
  const { asset } = platformAssetInfo();
  return `https://github.com/${REPO}/releases/download/v${releaseVersion}/${asset}`;
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o755 });
}

function fetchToFile(url, dest) {
  return new Promise((resolve, reject) => {
    const temp = `${dest}.download`;
    const request = https.get(url, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        fetchToFile(response.headers.location, dest).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`Failed to download UnoLock Agent MCP binary: HTTP ${response.statusCode}`));
        return;
      }
      const file = fs.createWriteStream(temp, { mode: 0o755 });
      response.pipe(file);
      file.on("finish", () => {
        file.close((closeErr) => {
          if (closeErr) {
            reject(closeErr);
            return;
          }
          fs.renameSync(temp, dest);
          if (process.platform !== "win32") {
            fs.chmodSync(dest, 0o755);
          }
          resolve();
        });
      });
      file.on("error", (error) => {
        file.close(() => {
          try {
            fs.unlinkSync(temp);
          } catch {}
          reject(error);
        });
      });
    });
    request.on("error", reject);
  });
}

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    const request = https.get(
      url,
      {
        headers: {
          "Accept": "application/vnd.github+json",
          "User-Agent": "unolock-agent-mcp-npm-wrapper"
        }
      },
      (response) => {
        if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
          response.resume();
          fetchJson(response.headers.location).then(resolve, reject);
          return;
        }
        if (response.statusCode !== 200) {
          response.resume();
          reject(new Error(`Failed to query UnoLock Agent MCP latest release: HTTP ${response.statusCode}`));
          return;
        }
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
        });
        response.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.on("error", reject);
  });
}

function normalizeVersion(value) {
  if (!value || typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return trimmed.startsWith("v") ? trimmed.slice(1) : trimmed;
}

function readReleaseMetadata() {
  try {
    return JSON.parse(fs.readFileSync(metadataPath(), "utf8"));
  } catch {
    return null;
  }
}

function writeReleaseMetadata(releaseVersion) {
  ensureDir(path.dirname(metadataPath()));
  fs.writeFileSync(
    metadataPath(),
    JSON.stringify(
      {
        releaseVersion,
        checkedAt: Date.now()
      },
      null,
      2
    ),
    "utf8"
  );
}

async function resolveReleaseVersion() {
  const override = normalizeVersion(process.env.UNOLOCK_AGENT_MCP_BINARY_VERSION);
  if (override) {
    return override;
  }
  const metadata = readReleaseMetadata();
  try {
    const payload = await fetchJson(`https://api.github.com/repos/${REPO}/releases/latest`);
    const latest = normalizeVersion(payload && payload.tag_name);
    if (latest) {
      writeReleaseMetadata(latest);
      return latest;
    }
  } catch (error) {
    if (metadata && typeof metadata.releaseVersion === "string" && fs.existsSync(binaryPath(metadata.releaseVersion))) {
      return metadata.releaseVersion;
    }
    process.stderr.write(`Warning: ${error.message}. Falling back to bundled release ${FALLBACK_BINARY_VERSION}.\n`);
  }
  writeReleaseMetadata(FALLBACK_BINARY_VERSION);
  return FALLBACK_BINARY_VERSION;
}

async function ensureBinary() {
  const releaseVersion = await resolveReleaseVersion();
  const dest = binaryPath(releaseVersion);
  if (fs.existsSync(dest)) {
    return { dest, releaseVersion };
  }
  ensureDir(path.dirname(dest));
  process.stderr.write(`Downloading UnoLock Agent MCP ${releaseVersion} for ${process.platform}/${process.arch}...\n`);
  await fetchToFile(binaryUrl(releaseVersion), dest);
  return { dest, releaseVersion };
}

async function main() {
  const { dest, releaseVersion } = await ensureBinary();
  const forwardedArgs = process.argv.length > 2 ? process.argv.slice(2) : ["mcp"];
  const child = spawn(dest, forwardedArgs, {
    stdio: "inherit",
    env: {
      ...process.env,
      UNOLOCK_AGENT_MCP_INSTALL_CHANNEL: "npm-wrapper",
      UNOLOCK_AGENT_MCP_WRAPPER_VERSION: PACKAGE_VERSION,
      UNOLOCK_AGENT_MCP_BINARY_VERSION: releaseVersion
    }
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
  child.on("error", (error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
