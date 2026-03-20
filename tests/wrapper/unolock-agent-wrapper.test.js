const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");

const wrapper = require("../../bin/unolock-agent.js");

test("acquireInstallLock serializes concurrent installers", async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "unolock-wrapper-lock-"));
  process.env.XDG_CACHE_HOME = tempRoot;

  const releaseFirst = await wrapper.acquireInstallLock();
  const events = [];

  const second = (async () => {
    events.push("wait-start");
    const releaseSecond = await wrapper.acquireInstallLock();
    events.push("wait-acquired");
    releaseSecond();
  })();

  await wrapper.sleep(150);
  assert.deepEqual(events, ["wait-start"]);

  releaseFirst();
  await second;

  assert.deepEqual(events, ["wait-start", "wait-acquired"]);
  assert.equal(fs.existsSync(wrapper.installLockPath()), false);
  fs.rmSync(tempRoot, { recursive: true, force: true });
});

test("writeReleaseMetadata is atomic and readable", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "unolock-wrapper-meta-"));
  process.env.XDG_CACHE_HOME = tempRoot;

  wrapper.writeReleaseMetadata("0.1.99");
  const payload = JSON.parse(fs.readFileSync(wrapper.metadataPath(), "utf8"));
  assert.equal(payload.releaseVersion, "0.1.99");

  fs.rmSync(tempRoot, { recursive: true, force: true });
});
