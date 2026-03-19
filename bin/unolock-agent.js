#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const https = require("https");
const { spawn } = require("child_process");

const PACKAGE_VERSION = "0.1.32";
const FALLBACK_BINARY_VERSION = "0.1.32";
const REPO = "TechSologic/unolock-agent";
const TOP_LEVEL_USAGE = `usage: unolock-agent [-h] [--version] {link-agent-key,set-agent-pin,list-spaces,get-current-space,set-current-space,list-records,list-notes,list-checklists,get-record,create-note,update-note,append-note,rename-record,create-checklist,set-checklist-item-done,add-checklist-item,remove-checklist-item,list-files,get-file,download-file,upload-file,rename-file,replace-file,delete-file,tpm-diagnose,tpm-check,self-test,mcp} ...

UnoLock Agent commands.

positional arguments:
  link-agent-key         Link a one-time UnoLock Agent Key URL and PIN to this device.
  set-agent-pin          Set the in-memory UnoLock agent PIN.
  list-spaces            List accessible UnoLock spaces.
  get-current-space      Show the current UnoLock space.
  set-current-space      Set the current UnoLock space.
  list-records           List notes and checklists in the current space.
  list-notes             List notes in the current space.
  list-checklists        List checklists in the current space.
  get-record             Get one note or checklist by record_ref.
  create-note            Create a note in the current space.
  update-note            Update an existing note.
  append-note            Append text to an existing note.
  rename-record          Rename a note or checklist.
  create-checklist       Create a checklist in the current space.
  set-checklist-item-done
                         Set one checklist item's done state.
  add-checklist-item     Add an item to a checklist.
  remove-checklist-item  Remove an item from a checklist.
  list-files             List Cloud files in the current space.
  get-file               Get metadata for one Cloud file.
  download-file          Download a Cloud file to the local filesystem.
  upload-file            Upload a local file into the current space.
  rename-file            Rename a Cloud file.
  replace-file           Replace a Cloud file with local content.
  delete-file            Delete a Cloud file.
  tpm-diagnose           Diagnose TPM/vTPM readiness for the UnoLock agent MCP.
  tpm-check              Fail-fast check for production-ready TPM/vTPM/platform-backed key access.
  self-test              Run a one-shot UnoLock Agent readiness check.
  mcp                    Run the UnoLock stdio MCP server.

options:
  -h, --help             show this help message and exit
  --version              show program's version number and exit
`;

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

function cacheRoot() {
  if (process.platform === "win32") {
    return process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  }
  return process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
}

function metadataPath() {
  return path.join(cacheRoot(), "unolock-agent", "release.json");
}

function binaryPath(releaseVersion) {
  const { executable } = platformAssetInfo();
  return path.join(cacheRoot(), "unolock-agent", releaseVersion, executable);
}

function binaryUrl(releaseVersion) {
  if (process.env.UNOLOCK_AGENT_BINARY_URL) {
    return process.env.UNOLOCK_AGENT_BINARY_URL;
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
          "User-Agent": "unolock-agent-npm-wrapper"
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
          reject(new Error(`Failed to query UnoLock agent latest release: HTTP ${response.statusCode}`));
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

function cachedReleaseVersion() {
  const override = normalizeVersion(process.env.UNOLOCK_AGENT_BINARY_VERSION);
  if (override) {
    return override;
  }
  const metadata = readReleaseMetadata();
  if (metadata && typeof metadata.releaseVersion === "string" && fs.existsSync(binaryPath(metadata.releaseVersion))) {
    return metadata.releaseVersion;
  }
  if (fs.existsSync(binaryPath(FALLBACK_BINARY_VERSION))) {
    return FALLBACK_BINARY_VERSION;
  }
  return null;
}

async function resolveReleaseVersion() {
  const cached = cachedReleaseVersion();
  if (cached) {
    return cached;
  }
  try {
    const payload = await fetchJson(`https://api.github.com/repos/${REPO}/releases/latest`);
    const latest = normalizeVersion(payload && payload.tag_name);
    if (latest) {
      writeReleaseMetadata(latest);
      return latest;
    }
  } catch (error) {
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
  process.stderr.write(`Downloading UnoLock agent ${releaseVersion} for ${process.platform}/${process.arch}...\n`);
  await fetchToFile(binaryUrl(releaseVersion), dest);
  return { dest, releaseVersion };
}

async function main() {
  const forwardedArgs = process.argv.length > 2 ? process.argv.slice(2) : [];
  if (forwardedArgs.length === 0 || forwardedArgs[0] === "-h" || forwardedArgs[0] === "--help") {
    process.stdout.write(TOP_LEVEL_USAGE);
    return;
  }
  if (forwardedArgs[0] === "--version") {
    process.stdout.write(`${PACKAGE_VERSION}\n`);
    return;
  }
  const { dest, releaseVersion } = await ensureBinary();
  const child = spawn(dest, forwardedArgs, {
    stdio: "inherit",
    env: {
      ...process.env,
      UNOLOCK_AGENT_INSTALL_CHANNEL: "npm-wrapper",
      UNOLOCK_AGENT_WRAPPER_VERSION: PACKAGE_VERSION,
      UNOLOCK_AGENT_BINARY_VERSION: releaseVersion
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
