import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash, webcrypto } from "node:crypto";

const source = readFileSync(new URL("./public-asset-cache.js", import.meta.url), "utf8");
const lib = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const model = readFileSync(new URL("./3d/CyberCheckVehicle_Photo3D.glb", import.meta.url));
const origin = "https://cache.checkupauto.test";
const absoluteURL = origin + lib.VEHICLE_GLB_URL;

function installEnvironment() {
  const saved = {
    location: globalThis.location, caches: globalThis.caches,
    fetch: globalThis.fetch, crypto: globalThis.crypto
  };
  Object.defineProperty(globalThis, "location", { value: new URL(origin), configurable: true });
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  const entries = new Map();
  const cache = {
    async match(req) { return entries.get(req.url)?.clone(); },
    async put(req, response) { entries.set(req.url, response.clone()); },
    async delete(req) { return entries.delete(req.url); },
    async keys() { return [...entries.keys()].map(url => new Request(url)); }
  };
  globalThis.caches = { async open(name) {
    assert.equal(name, "checkupauto-public-model-v1");
    return cache;
  }};
  const requests = [];
  globalThis.fetch = async req => {
    requests.push(req);
    return new Response(model.slice(0), {
      status: 200,
      headers: { "Content-Type": "model/gltf-binary", "Content-Length": String(model.length) }
    });
  };
  return {
    cache, entries, requests,
    restore() {
      for (const [key, val] of Object.entries(saved)) {
        if (key === "location" || key === "crypto")
          Object.defineProperty(globalThis, key, { value: val, configurable: true });
        else globalThis[key] = val;
      }
    }
  };
}

test("asset SHA256 is the deployed model SHA256, preventing stale content", () => {
  assert.equal(createHash("sha256").update(model).digest("hex"), lib.VEHICLE_GLB_SHA256);
  assert.match(lib.VEHICLE_GLB_URL, /^\/assets\/3d\/CyberCheckVehicle_Photo3D\.glb\?v=[0-9a-f]{64}$/);
});

test("first public model request stores only verified bytes, next load is offline-cache hit", async () => {
  const env = installEnvironment();
  try {
    const first = await lib.getPublicVehicleGLB();
    const second = await lib.getPublicVehicleGLB();
    assert.equal(Buffer.compare(Buffer.from(first), model), 0);
    assert.equal(Buffer.compare(Buffer.from(second), model), 0);
    assert.equal(env.requests.length, 1);
    assert.equal(env.requests[0].credentials, "omit");
    assert.equal(env.requests[0].method, "GET");
    assert.equal(env.requests[0].mode, "same-origin");
    assert.equal(env.requests[0].cache, "force-cache");
    assert.deepEqual([...env.entries.keys()], [absoluteURL]);
  } finally { env.restore(); }
});

test("no cross-origin / API / account / payment / unversioned URL can reach cache or fetch", async () => {
  const env = installEnvironment();
  try {
    for (const path of [
      "https://example.invalid/assets/3d/CyberCheckVehicle_Photo3D.glb?v=" + lib.VEHICLE_GLB_SHA256,
      origin + "/api/customer/me",
      origin + "/api/booking/availability",
      origin + "/payment/payline/checkout",
      origin + "/compte",
      origin + lib.VEHICLE_GLB_PATH,
      origin + lib.VEHICLE_GLB_URL + "&extra=1",
      origin + lib.VEHICLE_GLB_URL + "#fragment",
    ]) {
      await assert.rejects(lib.getPublicVehicleGLB(path), /public_cache_asset_not_allowed/);
    }
    assert.equal(env.requests.length, 0);
    assert.equal(env.entries.size, 0);
  } finally { env.restore(); }
});

test("corrupted cache entry is discarded and verified bytes are re-fetched", async () => {
  const env = installEnvironment();
  try {
    env.entries.set(absoluteURL, new Response(new Uint8Array(40), {
      headers: { "Content-Type": "model/gltf-binary" }
    }));
    assert.equal(Buffer.compare(Buffer.from(await lib.getPublicVehicleGLB()), model), 0);
    assert.equal(env.requests.length, 1);
    assert.deepEqual([...env.entries.keys()], [absoluteURL]);
  } finally { env.restore(); }
});

test("mismatching server model is refused without caching", async () => {
  const env = installEnvironment();
  try {
    globalThis.fetch = async req => {
      env.requests.push(req);
      const wrong = Buffer.from(model);
      wrong[30] ^= 1;
      return new Response(wrong, { headers: { "Content-Type": "model/gltf-binary" } });
    };
    await assert.rejects(lib.getPublicVehicleGLB(), /public_cache_digest_mismatch/);
    assert.equal(env.entries.size, 0);
  } finally { env.restore(); }
});

test("oversized or unexpected MIME payload is refused without caching", async () => {
  const env = installEnvironment();
  try {
    for (const bad of [
      new Response("not a glb", { headers: {"Content-Type":"text/html"} }),
      new Response("too large", { headers: {"Content-Type":"model/gltf-binary", "Content-Length":"5000000"} }),
      new Response("not found", { status:404, headers: {"Content-Type":"model/gltf-binary"} }),
    ]) {
      globalThis.fetch = async () => bad.clone();
      await assert.rejects(lib.getPublicVehicleGLB());
      assert.equal(env.entries.size, 0);
    }
  } finally { env.restore(); }
});

test("private mode Cache Storage failure gracefully falls back to verified fetch", async () => {
  const env = installEnvironment();
  try {
    globalThis.caches.open = async () => { throw new Error("quota denied"); };
    const body = await lib.getPublicVehicleGLB();
    assert.equal(Buffer.compare(Buffer.from(body), model), 0);
    assert.equal(env.requests.length, 1);
  } finally { env.restore(); }
});

test("cached old versions are pruned without touching other Cache Storage namespaces", async () => {
  const env = installEnvironment();
  try {
    env.entries.set(origin + lib.VEHICLE_GLB_PATH + "?v=previous", new Response(model, {
      headers: {"Content-Type":"model/gltf-binary"}
    }));
    await lib.getPublicVehicleGLB();
    assert.deepEqual([...env.entries.keys()], [absoluteURL]);
  } finally { env.restore(); }
});
