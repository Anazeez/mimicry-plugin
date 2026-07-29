const MAX_REFERENCE_BYTES = 20 * 1024 * 1024;
const MAX_REDIRECTS = 3;
const ALLOWED_MIME = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf"
]);

export class ReferenceInputError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ReferenceInputError";
    this.code = code;
  }
}

const isPrivateIpv4 = (hostname) => {
  const octets = hostname.split(".").map(Number);
  if (octets.length !== 4 || octets.some((value) => !Number.isInteger(value))) return false;
  const [a, b] = octets;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    a >= 224
  );
};

const assertPublicHttps = (value) => {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new ReferenceInputError("REF_URL_INVALID", "Reference URL is invalid");
  }
  if (url.protocol !== "https:") {
    throw new ReferenceInputError("REF_HTTPS_REQUIRED", "Reference URL must use HTTPS");
  }
  const hostname = url.hostname.toLowerCase();
  if (
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname.endsWith(".local") ||
    hostname === "[::1]" ||
    hostname === "::1" ||
    hostname.startsWith("[fc") ||
    hostname.startsWith("[fd") ||
    hostname.startsWith("[fe80:") ||
    isPrivateIpv4(hostname)
  ) {
    throw new ReferenceInputError(
      "REF_PRIVATE_ADDRESS",
      "Reference URL must not target a private address"
    );
  }
  return url;
};

const detectMime = (bytes) => {
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 12 &&
    String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" &&
    String.fromCharCode(...bytes.slice(8, 12)) === "WEBP"
  ) {
    return "image/webp";
  }
  if (bytes.length >= 5 && String.fromCharCode(...bytes.slice(0, 5)) === "%PDF-") {
    return "application/pdf";
  }
  throw new ReferenceInputError("REF_TYPE_UNSUPPORTED", "Reference file type is unsupported");
};

const readBounded = async (response) => {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REFERENCE_BYTES) {
    throw new ReferenceInputError("REF_TOO_LARGE", "Reference exceeds 20 MiB");
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_REFERENCE_BYTES) {
      await reader.cancel();
      throw new ReferenceInputError("REF_TOO_LARGE", "Reference exceeds 20 MiB");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
};

const hex = (buffer) =>
  Array.from(new Uint8Array(buffer), (value) => value.toString(16).padStart(2, "0")).join("");

export async function downloadReference(referenceFile, fetchImpl = fetch) {
  let url = assertPublicHttps(referenceFile.download_url);
  let response;
  for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
    response = await fetchImpl(url, {
      method: "GET",
      redirect: "manual",
      headers: { accept: "image/png,image/jpeg,image/webp,application/pdf" }
    });
    if (![301, 302, 303, 307, 308].includes(response.status)) break;
    if (redirect === MAX_REDIRECTS) {
      throw new ReferenceInputError("REF_TOO_MANY_REDIRECTS", "Reference redirected too many times");
    }
    const location = response.headers.get("location");
    if (!location) {
      throw new ReferenceInputError("REF_REDIRECT_INVALID", "Reference redirect has no location");
    }
    url = assertPublicHttps(new URL(location, url).toString());
  }
  if (!response?.ok) {
    throw new ReferenceInputError(
      "REF_DOWNLOAD_FAILED",
      `Reference download failed with HTTP ${response?.status ?? 0}`
    );
  }
  const bytes = await readBounded(response);
  const mimeType = detectMime(bytes);
  const declaredMime = referenceFile.mime_type?.split(";", 1)[0]?.trim().toLowerCase();
  const responseMime = response.headers
    .get("content-type")
    ?.split(";", 1)[0]
    ?.trim()
    .toLowerCase();
  if (
    (declaredMime && declaredMime !== mimeType) ||
    (responseMime && ALLOWED_MIME.has(responseMime) && responseMime !== mimeType)
  ) {
    throw new ReferenceInputError("REF_MIME_MISMATCH", "Reference MIME does not match its bytes");
  }
  if (!ALLOWED_MIME.has(mimeType)) {
    throw new ReferenceInputError("REF_TYPE_UNSUPPORTED", "Reference file type is unsupported");
  }
  const digest = hex(await crypto.subtle.digest("SHA-256", bytes));
  return {
    bytes,
    mimeType,
    digest,
    filename: String(referenceFile.file_name || `reference.${mimeType.split("/").at(-1)}`)
  };
}
