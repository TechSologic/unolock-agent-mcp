const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");

const common = require("../../bin/unolock-agent-common.js");
const wrapper = require("../../bin/unolock-agent.js");

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
