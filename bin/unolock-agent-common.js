#!/usr/bin/env node
"use strict";

const fs = require("fs");
const https = require("https");
const path = require("path");

const packageJson = require("../package.json");

const PACKAGE_VERSION = packageJson.version;
const REPO = "TechSologic/unolock-agent";

function platformAssetInfo() {
  const platform = process.platform;
  const arch = process.arch;
  if (platform === "linux" && arch === "x64") {
    return { asset: "unolock-agent-linux-x86_64", executable: "unolock-agent-linux-x86_64" };
  }
  if (platform === "darwin" && arch === "arm64") {
    return { asset: "unolock-agent-macos-arm64", executable: "unolock-agent-macos-arm64" };
  }
  if (platform === "darwin" && arch === "x64") {
    return { asset: "unolock-agent-macos-x86_64", executable: "unolock-agent-macos-x86_64" };
  }
  if (platform === "win32" && arch === "x64") {
    return { asset: "unolock-agent-windows-amd64.exe", executable: "unolock-agent-windows-amd64.exe" };
  }
  throw new Error(`Unsupported platform for UnoLock agent binary: ${platform}/${arch}`);
}

function installRoot() {
  return path.join(__dirname, "..", "vendor");
}

function installedBinaryPath() {
  const { executable } = platformAssetInfo();
  return path.join(installRoot(), executable);
}

function binaryUrl(releaseVersion = PACKAGE_VERSION) {
  if (process.env.UNOLOCK_AGENT_BINARY_URL) {
    return process.env.UNOLOCK_AGENT_BINARY_URL;
  }
  const { asset } = platformAssetInfo();
  return `https://github.com/${REPO}/releases/download/v${releaseVersion}/${asset}`;
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o755 });
}

function ensureExecutable(dest) {
  if (process.platform !== "win32" && fs.existsSync(dest)) {
    fs.chmodSync(dest, 0o755);
  }
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
        reject(new Error(`Failed to download UnoLock agent binary: HTTP ${response.statusCode}`));
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
          ensureExecutable(dest);
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

module.exports = {
  PACKAGE_VERSION,
  binaryUrl,
  ensureDir,
  ensureExecutable,
  fetchToFile,
  installRoot,
  installedBinaryPath,
  platformAssetInfo,
};
