import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { lstat, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { digest, relativePath } from './config.mjs';

export const manifestName = 'agrowknow-release.json';

export async function inventory(root, prefix = '') {
  const files = {};
  for (const item of (await readdir(path.join(root, prefix))).sort()) {
    const name = prefix ? `${prefix}/${item}` : item;
    relativePath(name);
    const target = path.join(root, name);
    const stat = await lstat(target);
    assert(!stat.isSymbolicLink(), 'Artifact must not contain symlinks');
    if (stat.isDirectory()) Object.assign(files, await inventory(root, name));
    else {
      assert(stat.isFile(), 'Artifact contains a special file');
      if (name === manifestName) continue;
      assert(
        !/(?:^|\/)(?:\.env(?:\..*)?|\.git|node_modules)(?:\/|$)/i.test(name),
        'Private file in artifact',
      );
      const bytes = await readFile(target);
      const text = bytes.toString('utf8');
      assert(
        !/(?:sk_live_|sk_test_|whsec_|sb_secret_)[A-Za-z0-9_]{8,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(
          text,
        ),
        'Server credential in artifact',
      );
      for (const [token] of text.matchAll(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g)) {
        try {
          assert.notEqual(
            JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString()).role,
            'service_role',
            'Service-role JWT in artifact',
          );
        } catch (error) {
          if (error.code === 'ERR_ASSERTION') throw error;
        }
      }
      Object.defineProperty(files, name, {
        value: { sha256: digest(bytes), bytes: bytes.length },
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
  }
  return files;
}

export function sourceCommit(root = process.cwd()) {
  const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
  if (process.env.GITHUB_SHA)
    assert.equal(commit, process.env.GITHUB_SHA, 'Checkout does not match workflow commit');
  return commit;
}

export async function seal(directory, metadata) {
  const files = await inventory(directory);
  assert(Object.keys(files).length, 'Cannot seal an empty artifact');
  const manifest = { schemaVersion: 1, ...metadata, files };
  await writeFile(path.join(directory, manifestName), JSON.stringify(manifest, null, 2) + '\n');
  return manifest;
}

export async function verify(directory, expected) {
  const manifest = JSON.parse(await readFile(path.join(directory, manifestName), 'utf8'));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.product, expected.product, 'Wrong product artifact');
  assert.equal(manifest.commit, expected.commit, 'Wrong commit artifact');
  if (expected.production)
    assert.equal(manifest.deploymentEligible, true, 'Validation-only artifact cannot be published');
  assert.deepEqual(await inventory(directory), manifest.files, 'Artifact changed after testing');
  return manifest;
}

export async function verifyRemote(base, manifest, request = fetch) {
  const url = new URL(base);
  assert.equal(url.protocol, 'https:', 'Remote verification requires HTTPS');
  const get = async (address) => {
    let current = new URL(address);
    for (let hop = 0; hop < 6; hop++) {
      const result = await request(current, {
        redirect: 'manual',
        cache: 'no-store',
        signal: AbortSignal.timeout(30000),
      });
      if (![301, 302, 303, 307, 308].includes(result.status)) return result;
      const location = result.headers?.get('location');
      assert(location, 'Redirect has no destination');
      const next = new URL(location, current);
      assert.equal(
        next.origin,
        url.origin,
        'Release verification cannot follow a foreign redirect',
      );
      current = next;
    }
    throw new Error('Release verification redirect limit exceeded');
  };
  const response = await get(new URL(manifestName, url));
  assert.equal(response.status, 200, 'Release receipt unavailable');
  assert.deepEqual(await response.json(), manifest, 'Remote release receipt differs');
  const entries = Object.entries(manifest.files).filter(
    ([name]) => !['_headers', '_redirects'].includes(name),
  );
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(6, entries.length) }, async () => {
      while (next < entries.length) {
        const [name, expected] = entries[next++];
        relativePath(name);
        const fileURL = new URL(name.split('/').map(encodeURIComponent).join('/'), url);
        fileURL.searchParams.set('agrowknow_release', manifest.commit);
        const result = await get(fileURL);
        assert.equal(result.status, 200, `Remote file unavailable: ${name}`);
        const bytes = Buffer.from(await result.arrayBuffer());
        assert.equal(digest(bytes), expected.sha256, `Remote bytes differ: ${name}`);
        assert.equal(bytes.length, expected.bytes, `Remote length differs: ${name}`);
      }
    }),
  );
}
