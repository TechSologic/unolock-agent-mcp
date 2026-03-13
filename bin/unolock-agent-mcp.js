#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const https = require("https");
const { spawn } = require("child_process");

const PACKAGE_VERSION = "0.1.13";
const BINARY_VERSION = "0.1.11";
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

function binaryPath() {
  const { executable } = platformAssetInfo();
  return path.join(cacheRoot(), "unolock-agent-mcp", BINARY_VERSION, executable);
}

function binaryUrl() {
  if (process.env.UNOLOCK_AGENT_MCP_BINARY_URL) {
    return process.env.UNOLOCK_AGENT_MCP_BINARY_URL;
  }
  const { asset } = platformAssetInfo();
  return `https://github.com/${REPO}/releases/download/v${BINARY_VERSION}/${asset}`;
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

async function ensureBinary() {
  const dest = binaryPath();
  if (fs.existsSync(dest)) {
    return dest;
  }
  ensureDir(path.dirname(dest));
  process.stderr.write(`Downloading UnoLock Agent MCP ${BINARY_VERSION} for ${process.platform}/${process.arch}...\n`);
  await fetchToFile(binaryUrl(), dest);
  return dest;
}

async function main() {
  const dest = await ensureBinary();
  const forwardedArgs = process.argv.length > 2 ? process.argv.slice(2) : ["mcp"];
  const child = spawn(dest, forwardedArgs, {
    stdio: "inherit",
    env: process.env
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
