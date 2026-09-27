import fs from 'node:fs';
import crypto from 'node:crypto';

const API = 'https://api.appstoreconnect.apple.com';

function b64url(data) {
  return Buffer.from(data)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

export function makeToken({ keyId, issuerId, privateKey, now = Math.floor(Date.now() / 1000) }) {
  if (!/^[A-Za-z0-9]{10}$/.test(keyId)) throw new Error('invalid_key_id');
  if (!/^[0-9A-Fa-f-]{36}$/.test(issuerId)) throw new Error('invalid_issuer_id');

  const header = b64url(JSON.stringify({ alg: 'ES256', kid: keyId, typ: 'JWT' }));
  const payload = b64url(JSON.stringify({
    iss: issuerId,
    iat: now,
    exp: now + 1100,
    aud: 'appstoreconnect-v1',
  }));
  const signingInput = `${header}.${payload}`;
  const signature = crypto.sign(
    'sha256',
    Buffer.from(signingInput),
    { key: privateKey, dsaEncoding: 'ieee-p1363' },
  );
  if (signature.length !== 64) throw new Error('invalid_es256_signature');
  return `${signingInput}.${b64url(signature)}`;
}

function query(params) {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      result.set(key, String(value));
    }
  }
  return result.toString();
}

class AppStoreConnect {
  constructor({ keyId, issuerId, keyPath, fetchImpl = fetch }) {
    this.keyId = keyId;
    this.issuerId = issuerId;
    this.privateKey = fs.readFileSync(keyPath, 'utf8');
    this.fetchImpl = fetchImpl;
  }

  token() {
    return makeToken({
      keyId: this.keyId,
      issuerId: this.issuerId,
      privateKey: this.privateKey,
    });
  }

  async request(method, path, body = null) {
    const response = await this.fetchImpl(API + path, {
      method,
      headers: {
        Authorization: `Bearer ${this.token()}`,
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    const raw = await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = { raw: raw.slice(0, 1000) };
      }
    }

    if (!response.ok) {
      const detail = (payload?.errors || [])
        .map(item => item.detail || item.title)
        .filter(Boolean)
        .join('; ');
      throw new Error(
        `asc_http_${response.status}${detail ? ':' + detail : ''}`,
      );
    }
    return payload;
  }
}

function uniqueResource(payload, label) {
  const rows = payload?.data;
  if (!Array.isArray(rows) || rows.length !== 1) {
    throw new Error(`${label}_not_unique`);
  }
  return rows[0];
}

export async function ensureInternalGroup(asc, { bundleId, groupName }) {
  const apps = await asc.request(
    'GET',
    `/v1/apps?${query({
      'filter[bundleId]': bundleId,
      'fields[apps]': 'name,bundleId',
      limit: 2,
    })}`,
  );
  const app = uniqueResource(apps, 'app');

  const groups = await asc.request(
    'GET',
    `/v1/betaGroups?${query({
      'filter[app]': app.id,
      'filter[name]': groupName,
      'filter[isInternalGroup]': 'true',
      limit: 2,
    })}`,
  );

  let group;
  if (Array.isArray(groups?.data) && groups.data.length === 1) {
    group = groups.data[0];
    if (group.attributes?.hasAccessToAllBuilds !== true) {
      group = (
        await asc.request(
          'PATCH',
          `/v1/betaGroups/${encodeURIComponent(group.id)}`,
          {
            data: {
              type: 'betaGroups',
              id: group.id,
              attributes: {
                hasAccessToAllBuilds: true,
                feedbackEnabled: true,
              },
            },
          },
        )
      ).data;
    }
  } else if (Array.isArray(groups?.data) && groups.data.length === 0) {
    group = (
      await asc.request('POST', '/v1/betaGroups', {
        data: {
          type: 'betaGroups',
          attributes: {
            name: groupName,
            isInternalGroup: true,
            hasAccessToAllBuilds: true,
            feedbackEnabled: true,
          },
          relationships: {
            app: { data: { type: 'apps', id: app.id } },
          },
        },
      })
    ).data;
  } else {
    throw new Error('beta_group_not_unique');
  }

  return { app, group };
}

export async function waitForBuild(
  asc,
  { appId, buildNumber, timeoutSeconds = 1800, intervalSeconds = 30 },
) {
  const deadline = Date.now() + timeoutSeconds * 1000;

  while (Date.now() < deadline) {
    const builds = await asc.request(
      'GET',
      `/v1/builds?${query({
        'filter[app]': appId,
        'filter[version]': buildNumber,
        'fields[builds]': 'version,processingState,uploadedDate,buildAudienceType',
        limit: 2,
      })}`,
    );
    const rows = Array.isArray(builds?.data) ? builds.data : [];
    if (rows.length > 1) throw new Error('build_not_unique');

    if (rows.length === 1) {
      const build = rows[0];
      const state = build.attributes?.processingState;
      if (state === 'VALID') return build;
      if (state === 'FAILED' || state === 'INVALID') {
        throw new Error(`build_processing_${state.toLowerCase()}`);
      }
    }

    await new Promise(resolve =>
      setTimeout(resolve, intervalSeconds * 1000),
    );
  }

  throw new Error('build_processing_timeout');
}

export async function attachBuild(asc, { groupId, buildId }) {
  const existing = await asc.request(
    'GET',
    `/v1/betaGroups/${encodeURIComponent(groupId)}/builds?${query({
      'filter[id]': buildId,
      limit: 1,
    })}`,
  );
  if (
    Array.isArray(existing?.data) &&
    existing.data.some(item => item.id === buildId)
  ) {
    return false;
  }

  await asc.request(
    'POST',
    `/v1/betaGroups/${encodeURIComponent(groupId)}/relationships/builds`,
    { data: [{ type: 'builds', id: buildId }] },
  );
  return true;
}

function argsFrom(argv) {
  return Object.fromEntries(
    argv.map(arg => {
      const index = arg.indexOf('=');
      return index < 0
        ? [arg, true]
        : [arg.slice(0, index), arg.slice(index + 1)];
    }),
  );
}

async function selfTest() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ec', {
    namedCurve: 'P-256',
  });
  const token = makeToken({
    keyId: 'ABCDEFGHIJ',
    issuerId: '12345678-1234-1234-1234-123456789abc',
    privateKey,
    now: 1700000000,
  });
  const [header, payload, signature] = token.split('.');
  if (!header || !payload || !signature) throw new Error('self_test_token_parts');

  const signatureBytes = Buffer.from(
    signature.replace(/-/g, '+').replace(/_/g, '/'),
    'base64',
  );
  const valid = crypto.verify(
    'sha256',
    Buffer.from(`${header}.${payload}`),
    { key: publicKey, dsaEncoding: 'ieee-p1363' },
    signatureBytes,
  );
  if (!valid) throw new Error('self_test_signature');
  console.log('APPSTORE_TESTFLIGHT_SELF_TEST_OK');
}

async function main() {
  const args = argsFrom(process.argv.slice(2));
  if (args['--self-test']) return selfTest();

  const required = [
    '--key-id',
    '--issuer-id',
    '--key-path',
    '--bundle-id',
    '--build-number',
    '--group-name',
  ];
  for (const key of required) {
    if (!args[key]) {
      throw new Error(`missing_${key.slice(2).replaceAll('-', '_')}`);
    }
  }

  const asc = new AppStoreConnect({
    keyId: args['--key-id'],
    issuerId: args['--issuer-id'],
    keyPath: args['--key-path'],
  });

  const { app, group } = await ensureInternalGroup(asc, {
    bundleId: args['--bundle-id'],
    groupName: args['--group-name'],
  });

  const build = await waitForBuild(asc, {
    appId: app.id,
    buildNumber: args['--build-number'],
    timeoutSeconds: Number(args['--timeout-seconds'] || 1800),
  });

  const attached = await attachBuild(asc, {
    groupId: group.id,
    buildId: build.id,
  });

  const testers = await asc.request(
    'GET',
    `/v1/betaGroups/${encodeURIComponent(group.id)}/betaTesters?limit=1`,
  );
  const testerCount = Number(testers?.meta?.paging?.total ?? 0);

  console.log(JSON.stringify({
    ok: true,
    appId: app.id,
    groupId: group.id,
    groupName: group.attributes?.name || args['--group-name'],
    buildId: build.id,
    buildNumber: build.attributes?.version,
    processingState: build.attributes?.processingState,
    buildAttached: attached,
    internalTesterCount: testerCount,
  }));

  if (testerCount === 0) {
    console.error(
      '::warning::TestFlight internal group has no testers yet',
    );
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(error => {
    console.error(String(error?.stack || error));
    process.exit(1);
  });
}
