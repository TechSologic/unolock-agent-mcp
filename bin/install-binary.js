#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const common = require("./unolock-agent-common");

async function installBinary(options = {}) {
  const fsImpl = options.fsImpl || fs;
  const commonImpl = options.commonImpl || common;
  const dest = commonImpl.installedBinaryPath();
  if (fsImpl.existsSync(dest)) {
    fsImpl.unlinkSync(dest);
  }
  commonImpl.ensureDir(path.dirname(dest));
  process.stderr.write(
    `Installing UnoLock agent ${commonImpl.PACKAGE_VERSION} for ${process.platform}/${process.arch}...\n`,
  );
  await commonImpl.fetchToFile(commonImpl.binaryUrl(commonImpl.PACKAGE_VERSION), dest);
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
