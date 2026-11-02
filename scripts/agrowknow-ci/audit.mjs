import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import policy from './zod-mitigation.json' with { type: 'json' };

export function validateAudit(report, reviewed = policy, now = Date.now()) {
  assert(report.advisories && report.metadata?.vulnerabilities, 'Incomplete dependency report');
  assert(now < Date.parse(reviewed.expires), 'Reviewed Zod backport requires renewal');
  const findings = Object.values(report.advisories).filter((row) =>
    ['high', 'critical'].includes(row.severity),
  );
  assert.equal(
    findings.length,
    report.metadata.vulnerabilities.high + report.metadata.vulnerabilities.critical,
    'Inconsistent audit totals',
  );
  for (const row of findings) {
    assert.equal(
      row.github_advisory_id,
      'GHSA-mrhx-c7xc-m3w5',
      `Unmitigated advisory: ${row.github_advisory_id}`,
    );
    assert.equal(row.module_name, 'zod');
    assert(
      row.findings?.length && row.findings.every((item) => item.version === reviewed.version),
      'Unexpected Zod version',
    );
  }
}

function main() {
  const targets = process.argv.slice(2);
  assert(targets.length, 'Supply each authoritative Expo app directory');
  const digest = (file) =>
    createHash('sha256').update(readFileSync(file, 'utf8').replace(/\r\n/g, '\n')).digest('hex');
  for (const target of targets) {
    const directory = path.resolve(target);
    assert(
      directory.startsWith(process.cwd() + path.sep),
      'Audit target must be inside the checkout',
    );
    const app = createRequire(path.join(directory, 'package.json'));
    const expo = createRequire(app.resolve('expo/package.json'));
    const cli = createRequire(expo.resolve('@expo/cli'));
    const installed = cli.resolve('zod/package.json');
    assert.equal(JSON.parse(readFileSync(installed, 'utf8')).version, policy.version);
    for (const [file, expected] of Object.entries(policy.files))
      assert.equal(
        digest(path.join(path.dirname(installed), file)),
        expected,
        `Unverified backport: ${file}`,
      );
    const regression = spawnSync(
      process.execPath,
      [fileURLToPath(new URL('./zod-regression.cjs', import.meta.url)), directory],
      { stdio: 'inherit', timeout: 30000 },
    );
    assert(
      !regression.error && regression.status === 0,
      'Zod source/compatibility regression failed',
    );
  }
  const audit =
    process.platform === 'win32'
      ? spawnSync('cmd.exe', ['/d', '/s', '/c', 'pnpm audit --prod --json'], {
          cwd: targets.length === 1 ? path.resolve(targets[0]) : process.cwd(),
          encoding: 'utf8',
          timeout: 120000,
        })
      : spawnSync('pnpm', ['audit', '--prod', '--json'], {
          cwd: targets.length === 1 ? path.resolve(targets[0]) : process.cwd(),
          encoding: 'utf8',
          timeout: 120000,
        });
  assert(!audit.error && [0, 1].includes(audit.status), 'Dependency audit did not complete');
  validateAudit(JSON.parse(audit.stdout));
  console.log(
    'No unmitigated high/critical dependencies. The exact Zod 3 backport and 104 compatibility cases are verified per app.',
  );
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
