import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, realpath } from 'node:fs/promises';
import path from 'node:path';

// Some repositories test their exported HTML, so build once before those checks.
export const phases = ['install', 'build', 'check', 'audit', 'browser', 'native'];
export const digest = (value) => createHash('sha256').update(value).digest('hex');

export function relativePath(value) {
  assert(typeof value === 'string' && value.length > 0, 'Missing relative path');
  assert(
    !value.includes('\\') && !value.includes(':') && !value.startsWith('/'),
    'Absolute paths are forbidden',
  );
  assert(
    value.split('/').every((part) => part && part !== '.' && part !== '..'),
    'Unsafe path',
  );
  return value;
}

export async function inside(root, name) {
  relativePath(name);
  const target = await realpath(path.resolve(root, name));
  const base = await realpath(root);
  assert(target.startsWith(base + path.sep), 'Path escapes the repository');
  return target;
}

export function validate(config) {
  assert.equal(config.schemaVersion, 1, 'Unsupported CI contract');
  assert(/^[a-z][a-z0-9-]+$/.test(config.product), 'Invalid product identifier');
  assert(['standard', 'integrated'].includes(config.mode), 'Invalid CI mode');
  assert(/^\.github\/workflows\/[a-z0-9-]+\.yml$/.test(config.ciWorkflow), 'Invalid CI workflow');
  assert(
    Array.isArray(config.requiredChecks) && config.requiredChecks.includes('AgrowKnow CI passed'),
    'Missing common gate',
  );
  for (const phase of phases) {
    assert(Array.isArray(config.commands[phase]), `Missing ${phase} command list`);
    assert(
      config.commands[phase].every((command) => typeof command === 'string' && command.trim()),
      `Invalid ${phase} command`,
    );
  }
  if (config.mode === 'standard') {
    assert(
      config.commands.check.length && config.commands.build.length,
      'Standard CI requires checks and build',
    );
  }
  for (const [key, value] of Object.entries(config.publicEnv ?? {})) {
    assert(
      key.startsWith('EXPO_PUBLIC_') && typeof value === 'string',
      'Only public client defaults are permitted',
    );
  }
  for (const [key, value] of Object.entries(config.productionEnv ?? {})) {
    assert(
      ['CONTEXT', 'FIELDCAST_DEPLOY_ENV'].includes(key) && value === 'production',
      'Invalid production build control',
    );
  }
  if (config.artifact) {
    relativePath(config.artifact.directory);
    assert(
      config.artifact.directory.split('/').some((part) => /^dist(?:-|$)/.test(part)),
      'Artifact must be generated dist output',
    );
  }
  const release = config.release;
  assert(
    ['netlify', 'cloudflare-pages', 'existing', 'none'].includes(release.provider),
    'Unsupported release adapter',
  );
  assert.equal(release.recovery, 'forward-only', 'Web recovery requires a reviewed forward repair');
  if (release.provider !== 'none') {
    const origin = new URL(release.origin);
    assert(
      origin.protocol === 'https:' &&
        origin.pathname === '/' &&
        !origin.search &&
        !origin.hash &&
        !origin.username &&
        !origin.password,
      'Release requires an HTTPS origin',
    );
  }
  assert(Array.isArray(release.requiredEnv), 'Missing production build contract');
  for (const key of release.requiredEnv)
    assert(key.startsWith('EXPO_PUBLIC_'), 'Production build inputs must be public');
  if (['netlify', 'cloudflare-pages'].includes(release.provider))
    assert(config.artifact, 'Release requires a sealed artifact');
  return config;
}

export async function load(root = process.cwd()) {
  return validate(JSON.parse(await readFile(path.join(root, '.agrowknow/ci.json'), 'utf8')));
}

export function buildEnvironment(config, raw = '{}') {
  const supplied = JSON.parse(raw || '{}');
  assert(
    supplied && typeof supplied === 'object' && !Array.isArray(supplied),
    'Public build input must be an object',
  );
  for (const [key, value] of Object.entries(supplied)) {
    assert(
      key.startsWith('EXPO_PUBLIC_') && typeof value === 'string',
      'Build inputs must be EXPO_PUBLIC_ strings',
    );
    assert(
      !/(?:sk_live_|sk_test_|whsec_|sb_secret_)/.test(value),
      'Server credential in public build input',
    );
    for (const [token] of value.matchAll(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g)) {
      try {
        assert.notEqual(
          JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString()).role,
          'service_role',
          'Service-role build input',
        );
      } catch (error) {
        if (error.code === 'ERR_ASSERTION') throw error;
      }
    }
  }
  const eligible = config.release.requiredEnv.every((key) => {
    const value = supplied[key];
    return (
      typeof value === 'string' &&
      value.trim() &&
      !/localhost|127\.0\.0\.1|replace.me|placeholder|fixture|\.invalid|example\.(?:com|test)|your.project/i.test(
        value,
      )
    );
  });
  const values = { ...config.publicEnv, ...supplied };
  return {
    values,
    eligible,
    configurationSha256: digest(JSON.stringify(Object.entries(values).sort())),
  };
}
