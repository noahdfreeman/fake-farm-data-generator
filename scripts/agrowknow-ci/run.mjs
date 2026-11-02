import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { appendFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildEnvironment, digest, inside, load, phases } from './config.mjs';
import { seal, sourceCommit } from './artifact.mjs';

export async function integrity(root = process.cwd()) {
  const lock = JSON.parse(
    await readFile(path.join(root, '.agrowknow/framework-lock.json'), 'utf8'),
  );
  assert.equal(lock.version, '1.0.0', 'Unsupported framework version');
  for (const [name, expected] of Object.entries(lock.files)) {
    assert.equal(
      digest((await readFile(await inside(root, name), 'utf8')).replace(/\r\n/g, '\n')),
      expected,
      `Framework drift: ${name}`,
    );
  }
}

export async function output(values) {
  if (process.env.GITHUB_OUTPUT) {
    for (const [key, value] of Object.entries(values))
      await appendFile(process.env.GITHUB_OUTPUT, `${key}=${value}\n`);
  }
}

export function authorizeRun(run, currentHead, config, { repository, commit, ref }) {
  assert.equal(ref, 'refs/heads/main', 'Release is main-only');
  assert.equal(
    run.repository.full_name.toLowerCase(),
    repository.toLowerCase(),
    'Cross-repository run',
  );
  assert.equal(run.head_repository.full_name.toLowerCase(), repository.toLowerCase(), 'Fork run');
  assert.equal(run.head_branch, 'main', 'CI run must be on main');
  assert.equal(run.head_sha, commit, 'CI run does not match checkout');
  assert.equal(run.path, config.ciWorkflow, 'Unexpected CI workflow');
  assert(
    ['push', 'workflow_dispatch'].includes(run.event),
    'Pull request and workflow_run artifacts cannot publish',
  );
  assert.equal(run.status, 'completed', 'CI is unfinished');
  assert.equal(run.conclusion, 'success', 'CI did not pass');
  assert.equal(currentHead, commit, 'Refusing obsolete main release');
  return commit;
}

export async function authorize(runId, config, root = process.cwd()) {
  assert(/^\d+$/.test(runId ?? ''), 'A successful CI run ID is required');
  const repository = process.env.GITHUB_REPOSITORY;
  assert(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository ?? ''), 'Missing repository context');
  const api = (suffix) =>
    JSON.parse(execFileSync('gh', ['api', `repos/${repository}/${suffix}`], { encoding: 'utf8' }));
  return authorizeRun(api(`actions/runs/${runId}`), api('branches/main').commit.sha, config, {
    repository,
    commit: sourceCommit(root),
    ref: process.env.GITHUB_REF,
  });
}

async function main() {
  const root = process.cwd();
  const config = await load(root);
  await integrity(root);
  const command = process.argv[2] ?? 'validate';
  if (command === 'authorize') {
    await authorize(process.argv[3], config, root);
    console.log('Successful CI, exact source and current main verified.');
    return;
  }
  const build = buildEnvironment(config, process.env.AGROWKNOW_PUBLIC_BUILD_ENV);
  await output({
    product: config.product,
    provider: config.release.provider,
    'artifact-directory': config.artifact?.directory ?? '',
    'has-artifact': Boolean(config.artifact),
  });
  if (command === 'validate') {
    console.log(
      `${config.product}: framework 1.0.0 verified; ${config.mode} CI; build ${build.eligible ? 'production eligible' : 'validation only'}.`,
    );
    return;
  }
  assert(command === 'all' || phases.includes(command), 'Unknown CI phase');
  const env = {
    ...process.env,
    ...build.values,
    ...(build.eligible ? config.productionEnv : {}),
    CI: 'true',
    EXPO_NO_DOTENV: '1',
  };
  for (const phase of command === 'all' ? phases : [command]) {
    for (const script of config.commands[phase]) {
      console.log(`Running ${config.product} ${phase}: ${script}`);
      const result =
        process.platform === 'win32'
          ? spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
              cwd: root,
              env,
              stdio: 'inherit',
            })
          : spawnSync('bash', ['--noprofile', '--norc', '-eo', 'pipefail', '-c', script], {
              cwd: root,
              env,
              stdio: 'inherit',
            });
      if (result.error) throw result.error;
      assert.equal(result.status, 0, `${phase} failed; subsequent phases and sealing stopped`);
    }
  }
  if (command === 'all' && config.artifact) {
    await seal(await inside(root, config.artifact.directory), {
      product: config.product,
      commit: sourceCommit(root),
      deploymentEligible: build.eligible,
      configurationSha256: build.configurationSha256,
    });
    console.log('Exact checked artifact sealed.');
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
