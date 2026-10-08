/**
 * CheckupAuto public-asset cache plugin.
 * Only the immutable, SHA-256-pinned public vehicle GLB is eligible.
 * HTML, authenticated endpoints, bookings, payments and reports NEVER enter this cache.
 * No service worker, credentials, third-party CDN or runtime dependency.
 */
export const VEHICLE_GLB_SHA256 = "3e30e528349a236c808c3310a0bf4f2b1290a15eea2ca8c850f2233d79f7d5a1";
export const VEHICLE_GLB_PATH = "/assets/3d/CyberCheckVehicle_Photo3D.glb";
export const VEHICLE_GLB_URL = VEHICLE_GLB_PATH + "?v=" + VEHICLE_GLB_SHA256;
const CACHE_NAME = "checkupauto-public-model-v1";
const MAX_BYTES = 4 * 1024 * 1024;

function verifiedTarget(value) {
  const target = new URL(value, location.href);
  // Exact URL allowlist. Nothing dynamic, private or cross-origin is cacheable.
  if (target.origin !== location.origin ||
      target.pathname !== VEHICLE_GLB_PATH ||
      target.search !== "?v=" + VEHICLE_GLB_SHA256 ||
      target.hash || target.username || target.password) {
    throw new Error("public_cache_asset_not_allowed");
  }
  return target;
}

async function boundedBuffer(response) {
  if (!response.ok || response.status !== 200 || response.type === "opaque") {
    throw new Error("public_cache_http_invalid");
  }
  const media = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  if (!["model/gltf-binary", "application/octet-stream"].includes(media)) {
    throw new Error("public_cache_media_invalid");
  }
  const declared = Number(response.headers.get("content-length") || 0);
  if (!Number.isFinite(declared) || declared > MAX_BYTES || declared < 0) {
    throw new Error("public_cache_size_invalid");
  }
  const stream = response.body;
  if (!stream || !stream.getReader) {
    const data = await response.arrayBuffer();
    if (data.byteLength > MAX_BYTES) throw new Error("public_cache_size_invalid");
    return data;
  }
  const reader = stream.getReader();
  const blocks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BYTES) {
        await reader.cancel();
        throw new Error("public_cache_size_invalid");
      }
      blocks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const data = new Uint8Array(total);
  let offset = 0;
  for (const block of blocks) {
    data.set(block, offset);
    offset += block.byteLength;
  }
  return data.buffer;
}

async function checkDigest(buffer) {
  if (buffer.byteLength < 20 || !globalThis.crypto?.subtle?.digest) {
    throw new Error("public_cache_digest_unavailable");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", buffer);
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== VEHICLE_GLB_SHA256) throw new Error("public_cache_digest_mismatch");
  return buffer;
}

async function tryCache() {
  if (!("caches" in globalThis)) return null;
  try { return await caches.open(CACHE_NAME); }
  catch (_error) { return null; }
}

export async function getPublicVehicleGLB(url = VEHICLE_GLB_URL) {
  const target = verifiedTarget(url);
  // Never send an account cookie even when the visitor happens to be signed in.
  const request = new Request(target.href, {
    mode: "same-origin", credentials: "omit", cache: "force-cache", redirect: "error"
  });
  const cache = await tryCache();
  if (cache) {
    try {
      const response = await cache.match(request);
      if (response) return await checkDigest(await boundedBuffer(response));
    } catch (_error) {
      try { await cache.delete(request); } catch (_ignored) {}
    }
  }
  const response = await fetch(request);
  const buffer = await checkDigest(await boundedBuffer(response));
  if (cache) {
    try {
      await cache.put(request, new Response(buffer.slice(0), {
        headers: { "Content-Type": "model/gltf-binary", "Content-Length": String(buffer.byteLength) }
      }));
      // Max one verified model per cache version; never remove unrelated caches.
      for (const old of await cache.keys()) {
        if (old.url !== request.url) await cache.delete(old);
      }
    } catch (_error) {
      // Quota / private mode: still render the fetched, digest-verified model.
    }
  }
  return buffer;
}
