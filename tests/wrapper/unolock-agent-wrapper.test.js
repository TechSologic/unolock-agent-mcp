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
  assert.equal(path.basename(path.dirname(dest)), "vendor");
});

test("wrapper exposes a direct reinstall message when binary is missing", () => {
  assert.match(wrapper.installedBinaryError(), /npm install -g @techsologic\/unolock-agent/);
});

test("installBinary replaces an existing packaged binary during install", async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "unolock-agent-install-"));
  const dest = path.join(tempRoot, "vendor", "unolock-agent-test");
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, "old-binary");

  let fetchedUrl = null;
  await installer.installBinary({
    fsImpl: fs,
    commonImpl: {
      PACKAGE_VERSION: "9.9.9",
      installedBinaryPath: () => dest,
      ensureDir: (dir) => fs.mkdirSync(dir, { recursive: true }),
      binaryUrl: (version) => `https://example.test/${version}`,
      fetchToFile: async (url, finalDest) => {
        fetchedUrl = url;
        fs.writeFileSync(finalDest, "new-binary");
      },
    },
  });

  assert.equal(fetchedUrl, "https://example.test/9.9.9");
  assert.equal(fs.readFileSync(dest, "utf8"), "new-binary");
  fs.rmSync(tempRoot, { recursive: true, force: true });
});
