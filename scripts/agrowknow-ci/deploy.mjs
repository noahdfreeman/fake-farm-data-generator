import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { appendFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { load } from './config.mjs';
import { sourceCommit, verify, verifyRemote } from './artifact.mjs';
import { authorize, integrity } from './run.mjs';

const root = process.cwd();
const config = await load(root);
await integrity(root);
assert(
  ['netlify', 'cloudflare-pages'].includes(config.release.provider),
  'This product retains its existing release path',
);
assert.equal(process.env.AGROWKNOW_WEB_RELEASE_ENABLED, 'true', 'New release path is disabled');
await authorize(process.env.AGROWKNOW_CI_RUN_ID, config, root);
const directory = path.join(root, '.codex/agrowknow-release');
const manifest = await verify(directory, {
  product: config.product,
  commit: sourceCommit(root),
  production: true,
});

function cli(binary, args) {
  const result = spawnSync(binary, args, {
    encoding: 'utf8',
    maxBuffer: 20 * 1024 * 1024,
    env: process.env,
  });
  assert(
    !result.error && result.status === 0,
    'Hosting CLI failed; inspect provider deployment logs',
  );
  return result.stdout;
}
const netlify = (...args) => JSON.parse(cli('npx', ['--yes', 'netlify-cli@23.14.0', ...args]));
const netlifyApi = (method, data) => netlify('api', method, '--data', JSON.stringify(data));
const site = process.env.AGROWKNOW_SITE_ID;
let candidate;
const receipt = {
  product: config.product,
  commit: manifest.commit,
  provider: config.release.provider,
  published: false,
};
await mkdir('.codex/agrowknow-ci', { recursive: true });
try {
  if (config.release.provider === 'netlify') {
    assert(
      /^[a-f0-9-]{36}$/.test(site ?? '') && process.env.NETLIFY_AUTH_TOKEN,
      'Missing scoped Netlify target or token',
    );
    const before = netlifyApi('getSite', { site_id: site });
    assert.equal(
      before.custom_domain,
      new URL(config.release.origin).hostname,
      'Wrong Netlify destination',
    );
    assert(before.published_deploy?.id, 'Cannot identify current production deployment');
    candidate = netlify(
      'deploy',
      '--no-build',
      '--site',
      site,
      '--dir',
      directory,
      '--message',
      `AgrowKnow ${manifest.commit}`,
      '--json',
    );
    const candidateURL = new URL(candidate.deploy_url);
    assert(candidateURL.hostname.endsWith('.netlify.app'), 'Unexpected candidate host');
    receipt.candidate = candidate.deploy_id;
    await verifyRemote(candidateURL, manifest);
    await authorize(process.env.AGROWKNOW_CI_RUN_ID, config, root);
    const published = netlify(
      'deploy',
      '--no-build',
      '--prod',
      '--site',
      site,
      '--dir',
      directory,
      '--message',
      `AgrowKnow ${manifest.commit}`,
      '--json',
    );
    receipt.deployment = published.deploy_id;
  } else {
    const project = process.env.AGROWKNOW_PAGES_PROJECT;
    assert(/^[a-z0-9][a-z0-9-]+$/.test(project ?? ''), 'Missing Cloudflare Pages project');
    assert(
      process.env.CLOUDFLARE_ACCOUNT_ID && process.env.CLOUDFLARE_API_TOKEN,
      'Missing scoped Cloudflare credentials',
    );
    const publish = (branch) => {
      const result = cli('pnpm', [
        'dlx',
        'wrangler@4.156.2',
        'pages',
        'deploy',
        directory,
        '--project-name',
        project,
        '--branch',
        branch,
        '--commit-hash',
        manifest.commit,
      ]);
      const matches = [...result.matchAll(/https:\/\/[a-z0-9-]+\.[a-z0-9-]+\.pages\.dev/g)].map(
        ([url]) => new URL(url),
      );
      const url = matches.find((value) => value.hostname.endsWith(`.${project}.pages.dev`));
      assert(url, 'Cloudflare did not return the expected deployment URL');
      return url;
    };
    const candidateURL = publish(`agrowknow-candidate-${manifest.commit.slice(0, 12)}`);
    receipt.candidate = candidateURL.href;
    await verifyRemote(candidateURL, manifest);
    await authorize(process.env.AGROWKNOW_CI_RUN_ID, config, root);
    const publishedURL = publish('main');
    await verifyRemote(publishedURL, manifest);
  }
  for (let attempt = 0; ; attempt++) {
    try {
      await verifyRemote(config.release.origin, manifest);
      break;
    } catch (error) {
      if (attempt === 4) throw error;
      await new Promise((resolve) => setTimeout(resolve, 10000));
    }
  }
  receipt.published = true;
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(
      process.env.GITHUB_STEP_SUMMARY,
      `Verified ${config.product} ${manifest.commit} at ${config.release.origin}\n`,
    );
} catch (error) {
  receipt.failed = true;
  // No schema downgrade or data restore is ever part of web recovery.
  throw error;
} finally {
  await writeFile('.codex/agrowknow-ci/deployment.json', JSON.stringify(receipt, null, 2) + '\n');
}
