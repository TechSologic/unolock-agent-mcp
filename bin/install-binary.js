#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawnSync } = require("child_process");

const common = require("./unolock-agent-common");

function removeExistingPath(fsImpl, target) {
  if (!fsImpl.existsSync(target)) {
    return;
  }
  fsImpl.rmSync(target, { recursive: true, force: true });
}

function extractArchive(archivePath, destDir) {
  if (process.platform === "win32") {
    const result = spawnSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `Expand-Archive -LiteralPath '${archivePath.replace(/'/g, "''")}' -DestinationPath '${destDir.replace(/'/g, "''")}' -Force`,
      ],
      { stdio: "pipe" },
    );
    if (result.status !== 0) {
      throw new Error((result.stderr && result.stderr.toString().trim()) || "Failed to extract UnoLock agent archive.");
    }
    return;
  }
  const result = spawnSync("tar", ["-xzf", archivePath, "-C", destDir], { stdio: "pipe" });
  if (result.status !== 0) {
    throw new Error((result.stderr && result.stderr.toString().trim()) || "Failed to extract UnoLock agent archive.");
  }
}

async function installBinary(options = {}) {
  const fsImpl = options.fsImpl || fs;
  const commonImpl = options.commonImpl || common;
  const extractImpl = options.extractImpl || extractArchive;
  const dest = commonImpl.installedBinaryPath();
  const installDir = commonImpl.installedBinaryDir();
  const tempRoot = fsImpl.mkdtempSync(path.join(os.tmpdir(), "unolock-agent-install-"));
  const archivePath = path.join(tempRoot, commonImpl.platformAssetInfo().asset);
  process.stderr.write(
    `Installing UnoLock agent ${commonImpl.PACKAGE_VERSION} for ${process.platform}/${process.arch}...\n`,
  );
  try {
    await commonImpl.fetchToFile(commonImpl.binaryUrl(commonImpl.PACKAGE_VERSION), archivePath);
    removeExistingPath(fsImpl, installDir);
    commonImpl.ensureDir(commonImpl.installRoot());
    await extractImpl(archivePath, commonImpl.installRoot());
    commonImpl.ensureExecutable(dest);
  } finally {
    removeExistingPath(fsImpl, tempRoot);
  }
}

async function main() {
  await installBinary();
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
}

module.exports = {
  installBinary,
  main,
};
