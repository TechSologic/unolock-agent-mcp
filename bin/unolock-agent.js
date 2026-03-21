#!/usr/bin/env node
"use strict";

const fs = require("fs");
const { spawn } = require("child_process");

const {
  PACKAGE_VERSION,
  ensureExecutable,
  installedBinaryPath,
} = require("./unolock-agent-common");

const TOP_LEVEL_USAGE = `usage: unolock-agent [-h] [--version] {register,set-agent-pin,list-spaces,get-current-space,set-current-space,list-records,list-notes,list-checklists,get-record,create-note,update-note,append-note,rename-record,create-checklist,set-checklist-item-done,add-checklist-item,remove-checklist-item,list-files,get-file,download-file,upload-file,rename-file,replace-file,delete-file,tpm-diagnose,tpm-check,self-test,mcp} ...

UnoLock Agent commands.

positional arguments:
  register               Register a one-time UnoLock Agent Key URL and PIN on this device.
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

function installedBinaryError() {
  return (
    "UnoLock Agent is not installed correctly. Reinstall it with `npm install -g @techsologic/unolock-agent` " +
    "or use a GitHub release binary."
  );
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

  const dest = installedBinaryPath();
  if (!fs.existsSync(dest)) {
    throw new Error(installedBinaryError());
  }
  ensureExecutable(dest);

  const child = spawn(dest, forwardedArgs, {
    stdio: "inherit",
    env: {
      ...process.env,
      UNOLOCK_AGENT_INSTALL_CHANNEL: "npm-install",
      UNOLOCK_AGENT_BINARY_VERSION: PACKAGE_VERSION,
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

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
} else {
  module.exports = {
    PACKAGE_VERSION,
    TOP_LEVEL_USAGE,
    installedBinaryError,
    installedBinaryPath,
    main,
  };
}
