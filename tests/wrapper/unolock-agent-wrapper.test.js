const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");
const os = require("os");
const fs = require("fs");

const common = require("../../bin/unolock-agent-common.js");
const wrapper = require("../../bin/unolock-agent.js");
const installer = require("../../bin/install-binary.js");

test("binaryUrl targets the package version release asset", () => {
  const url = common.binaryUrl(common.PACKAGE_VERSION);
  assert.match(url, new RegExp(`/releases/download/v${common.PACKAGE_VERSION}/`));
});

test("installedBinaryPath points inside the package vendor directory", () => {
  const dest = common.installedBinaryPath();
  assert.equal(path.basename(path.dirname(path.dirname(dest))), "vendor");
});

test("wrapper exposes a direct reinstall message when binary is missing", () => {
  assert.match(wrapper.installedBinaryError(), /npm install -g @techsologic\/unolock-agent/);
});

test("wrapper usage includes sync commands", () => {
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-list/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-status/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-add/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-run/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-enable/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-disable/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-remove/);
  assert.match(wrapper.TOP_LEVEL_USAGE, /sync-restore/);
});

test("installBinary replaces an existing packaged binary during install", async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "unolock-agent-install-"));
  const installDir = path.join(tempRoot, "vendor", "unolock-agent-test");
  const dest = path.join(installDir, "unolock-agent-test");
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, "old-binary");

  let fetchedUrl = null;
  await installer.installBinary({
    fsImpl: fs,
    extractImpl: async (_archivePath, finalRoot) => {
      const extractedDir = path.join(finalRoot, "unolock-agent-test");
      fs.mkdirSync(extractedDir, { recursive: true });
      fs.writeFileSync(path.join(extractedDir, "unolock-agent-test"), "new-binary");
    },
    commonImpl: {
      PACKAGE_VERSION: "9.9.9",
      installRoot: () => path.join(tempRoot, "vendor"),
      installedBinaryDir: () => installDir,
      installedBinaryPath: () => dest,
      ensureDir: (dir) => fs.mkdirSync(dir, { recursive: true }),
      binaryUrl: (version) => `https://example.test/${version}`,
      platformAssetInfo: () => ({ asset: "unolock-agent-test.tar.gz" }),
      ensureExecutable: () => {},
      fetchToFile: async (url, finalDest) => {
        fetchedUrl = url;
        fs.writeFileSync(finalDest, "archive");
      },
    },
  });

  assert.equal(fetchedUrl, "https://example.test/9.9.9");
  assert.equal(fs.readFileSync(dest, "utf8"), "new-binary");
  fs.rmSync(tempRoot, { recursive: true, force: true });
});
