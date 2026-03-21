#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const {
  PACKAGE_VERSION,
  binaryUrl,
  ensureDir,
  ensureExecutable,
  fetchToFile,
  installedBinaryPath,
} = require("./unolock-agent-common");

async function main() {
  const dest = installedBinaryPath();
  if (fs.existsSync(dest)) {
    ensureExecutable(dest);
    return;
  }
  ensureDir(path.dirname(dest));
  process.stderr.write(`Installing UnoLock agent ${PACKAGE_VERSION} for ${process.platform}/${process.arch}...\n`);
  await fetchToFile(binaryUrl(PACKAGE_VERSION), dest);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
}
