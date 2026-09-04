import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const testsDirectory = join(root, "tests");
const tests = readdirSync(testsDirectory)
  .filter((name) => /^test_.*\.js$/.test(name))
  .sort()
  .map((name) => join(testsDirectory, name));

if (tests.length === 0) {
  console.error("No JavaScript tests found in tests/test_*.js");
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...tests], {
  cwd: root,
  stdio: "inherit",
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
