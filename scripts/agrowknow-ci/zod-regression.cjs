/* eslint @typescript-eslint/no-require-imports: "off" -- This regression exercises both CommonJS and ESM package entry points. */
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const app = createRequire(path.resolve(process.argv[2], 'package.json'));
const expo = createRequire(app.resolve('expo/package.json'));
const cli = createRequire(expo.resolve('@expo/cli'));
const packageRoot = path.dirname(cli.resolve('zod/package.json'));
const vulnerable = process.argv.includes('--expect-vulnerable');

async function main() {
  let cases = 0;
  for (const dialect of ['root', 'v3', 'v4', 'v4/mini', 'v4-mini']) {
    for (const format of ['require', 'import']) {
      const specifier = dialect === 'root' ? 'zod' : `zod/${dialect}`;
      const relative = dialect === 'root' ? 'index.js' : `${dialect}/index.js`;
      const z =
        format === 'require'
          ? cli(specifier)
          : await import(pathToFileURL(path.join(packageRoot, relative)).href);
      const mini = dialect.includes('mini');
      const v3 = dialect === 'root' || dialect === 'v3';
      const parse = (schema, input, async) =>
        mini
          ? z[async ? 'safeParseAsync' : 'safeParse'](schema, input)
          : schema[async ? 'safeParseAsync' : 'safeParse'](input);
      const schemas = [
        [
          'array max',
          () =>
            v3
              ? z.array(z.string()).max(2, 'too many')
              : z.array(z.string()).check(z.maxLength(2, 'too many')),
          false,
        ],
        [
          'array exact',
          () =>
            v3
              ? z.array(z.string()).length(2, 'too many')
              : z.array(z.string()).check(z.length(2, 'too many')),
          false,
        ],
        [
          'set max',
          () =>
            v3
              ? z.set(z.string()).max(2, 'too many')
              : z.set(z.string()).check(z.maxSize(2, 'too many')),
          true,
        ],
        [
          'set exact',
          () =>
            v3
              ? z.set(z.string()).size(2, 'too many')
              : z.set(z.string()).check(z.size(2, 'too many')),
          true,
        ],
      ];
      if (!v3)
        schemas.push([
          'map max',
          () => z.map(z.string(), z.string()).check(z.maxSize(2, 'too many')),
          'map',
        ]);
      if (!v3)
        schemas.push([
          'array refined before max',
          () =>
            z.array(z.string()).check(
              z.refine(() => true),
              z.maxLength(2, 'too many'),
            ),
          false,
        ]);
      for (const [kind, make, collection] of schemas) {
        for (const async of [false, true]) {
          let visited = 0;
          class CountedSet extends Set {
            *values() {
              for (const value of Set.prototype.values.call(this)) {
                visited++;
                yield value;
              }
            }
            [Symbol.iterator]() {
              return this.values();
            }
          }
          class CountedMap extends Map {
            *entries() {
              for (const value of Map.prototype.entries.call(this)) {
                visited++;
                yield value;
              }
            }
            [Symbol.iterator]() {
              return this.entries();
            }
          }
          const input =
            collection === 'map'
              ? new CountedMap(Array.from({ length: 4096 }, (_, i) => [i, i]))
              : collection
                ? new CountedSet(Array.from({ length: 4096 }, (_, i) => i))
                : new Proxy(Array(4096).fill(null), {
                    get(target, key, receiver) {
                      if (/^\d+$/.test(String(key))) visited++;
                      return Reflect.get(target, key, receiver);
                    },
                  });
          const schema = make();
          const result = await parse(schema, input, async);
          assert.equal(result.success, false, `${dialect}/${format}/${kind}: reject`);
          if (vulnerable)
            assert(visited > 0, `${dialect}/${format}/${kind}: original walks elements`);
          else {
            assert.equal(visited, 0, `${dialect}/${format}/${kind}: no element traversal`);
            assert.equal(result.error.issues.length, 1);
            assert.equal(result.error.issues[0].code, 'too_big');
            assert.equal(result.error.issues[0].message, 'too many');
          }
          const valid =
            collection === 'map'
              ? new Map([
                  ['field', 'Corn'],
                  ['model', 'NOAA'],
                ])
              : collection
                ? new Set(['Corn', 'Soybeans'])
                : ['Corn', 'Soybeans'];
          const control = await parse(schema, valid, async);
          assert.equal(control.success, true, `${dialect}/${format}/${kind}: legitimate input`);
          assert.deepEqual(control.data, valid);
          assert.equal((await parse(schema, null, async)).success, false);
          cases++;
        }
      }
      const bounded = v3 ? z.array(z.string()).max(2) : z.array(z.string()).check(z.maxLength(2));
      const nested = await parse(z.object({ fields: bounded }), { fields: Array(4096) }, false);
      if (!vulnerable) {
        assert.equal(nested.error.issues.length, 1);
        assert.deepEqual(nested.error.issues[0].path, ['fields']);
      }
      // Size gates must not preempt a preceding overwrite that makes data fit.
      if (!v3) {
        const rewrites = z.array(z.string()).check(
          z.overwrite((values) => values.slice(0, 2)),
          z.maxLength(2),
        );
        assert.deepEqual((await parse(rewrites, ['a', 'b', 'c'], false)).data, ['a', 'b']);
        const disabled = z.maxLength(2);
        disabled._zod.def.when = () => false;
        assert.equal(
          (await parse(z.array(z.string()).check(disabled), ['a', 'b', 'c'], false)).success,
          true,
        );
        // Match the published security fix: upper bounds protect raw collection
        // size, even if element/key transforms would later collapse duplicates.
        const transform = mini
          ? z.pipe(
              z.string(),
              z.transform(() => 'same'),
            )
          : z.string().transform(() => 'same');
        const set = z.set(transform).check(z.maxSize(2));
        const map = z.map(transform, z.string()).check(z.maxSize(2));
        assert.equal((await parse(set, new Set(['a', 'b']), false)).data.size, 1);
        assert.equal(
          (
            await parse(
              map,
              new Map([
                ['a', 'a'],
                ['b', 'b'],
              ]),
              false,
            )
          ).data.size,
          1,
        );
        if (!vulnerable) {
          assert.equal((await parse(set, new Set(['a', 'b', 'c']), false)).success, false);
          assert.equal(
            (
              await parse(
                map,
                new Map([
                  ['a', 'a'],
                  ['b', 'b'],
                  ['c', 'c'],
                ]),
                false,
              )
            ).success,
            false,
          );
        }
      }
      const unbounded = await parse(z.array(z.string()), ['a', 'b', 'c'], false);
      assert.equal(unbounded.success, true, 'unbounded collection API unchanged');
    }
  }

  // Exercise Expo's real consumers, including the Zod 3 schema representation
  // consumed by its optional MCP tunnel's zod-to-json-schema adapter.
  const server = path.join(
    path.dirname(cli.resolve('@expo/cli/package.json')),
    'build/src/start/server',
  );
  const { PluginSchema, DevToolsPluginOutputSchema } = require(
    path.join(server, 'DevToolsPlugin.schema.js'),
  );
  const { createMCPDevToolsExtensionSchema } = require(
    path.join(server, 'createMCPDevToolsExtensionSchema.js'),
  );
  const plugin = {
    packageName: 'fieldcast-fixture',
    packageRoot: '/fixture',
    cliExtensions: {
      description: 'FieldCast controls',
      entryPoint: 'cli.js',
      commands: [
        {
          name: 'inspect',
          title: 'Inspect',
          environments: ['cli', 'mcp'],
          parameters: [
            { name: 'field', type: 'text' },
            { name: 'season', type: 'number' },
          ],
        },
      ],
    },
  };
  const parsed = PluginSchema.parse(plugin);
  assert(Object.isFrozen(parsed.cliExtensions.commands[0].environments));
  assert.equal(
    PluginSchema.safeParse({ ...plugin, cliExtensions: { ...plugin.cliExtensions, commands: [] } })
      .success,
    false,
  );
  assert.equal(
    DevToolsPluginOutputSchema.safeParse([
      { type: 'text', text: 'Corn', level: 'info' },
      { type: 'image', url: 'https://example.com/map.png' },
      { type: 'audio', url: 'https://example.com/audio.mp3' },
    ]).success,
    true,
  );
  assert.equal(
    DevToolsPluginOutputSchema.safeParse([{ type: 'image', url: 'invalid' }]).success,
    false,
  );
  const mcp = createMCPDevToolsExtensionSchema(parsed);
  assert.equal(mcp._def.typeName, 'ZodObject', 'preserve v3 converter compatibility');
  assert.deepEqual(mcp.shape.command._def.values, ['inspect']);
  assert.equal(mcp.shape.field.unwrap()._def.typeName, 'ZodString');
  assert.equal(mcp.shape.season.unwrap()._def.typeName, 'ZodNumber');
  assert.deepEqual(mcp.parse({ command: 'inspect', field: 'Corn', season: 2027 }), {
    command: 'inspect',
    field: 'Corn',
    season: 2027,
  });
  for (const input of [
    { command: 'unknown' },
    { command: 'inspect', field: 42 },
    { command: 'inspect', extra: true },
  ]) {
    assert.equal(mcp.safeParse(input).success, false);
  }
  console.log(
    `${cases} Zod collection cases ${vulnerable ? 'reproduce original traversal' : 'reject before element traversal'}; normal collections and Expo plugin/MCP controls pass.`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
