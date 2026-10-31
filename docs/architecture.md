# Architecture and decisions

One FastAPI process serves static HTML/JS and a small API. No database, document
library, background queue, or persistent storage. Use uv and a committed lockfile.

The first vertical slice is safe fetching: HTTP(S), standard ports, public unicast
addresses only. An aiohttp resolver validates *all* DNS answers at connection time
and gives those addresses directly to the connector; numeric URLs are checked too.
Each redirect is checked anew. No environment proxies, cookies, automatic redirects,
or secondary resource downloads. Compressed responses are rejected initially to
avoid decompression bombs. Bounds apply to bytes, redirects and total fetch time.

Extraction accepts fetched HTML through an extractor protocol; Trafilatura returns
metadata and semantic content, followed by an HTML allowlist. Renderers separately
produce PDF with WeasyPrint and EPUB with EbookLib. Images are omitted. PDF fetching
is denied, including local files and data URIs. Untrusted parsing/rendering runs in
a short-lived subprocess with a wall deadline and Linux memory/CPU/file limits.
A non-queuing concurrency gate bounds work; temporary directories are cleaned up.

The browser first converts and receives a file, then optionally uploads that same
file via a multipart /api/send request. This intentionally refines the proposed
send endpoint: an upload failure cannot lose the already converted download.
Documents live only in the request and browser memory; there are no download IDs
or persistent caches. Format, folder and delivery are stored in localStorage.

The rmfakecloud client uses its web API, not the official reMarkable protocol.
Credentials/tokens stay server-side. List folders immediately before upload to
reject stale destinations. Never blindly retry an ambiguous upload failure.

Require an authenticating ingress in production, with a configured identity header
that ingress strips and sets. Default deny when that header is absent. Explicit
local-development mode is allowed. Allowlist exact public origins, validate Host,
require same-origin POSTs plus a custom request header, and do not enable CORS.
`APP_ALLOWED_ORIGINS` accepts a JSON list, with `APP_BASE_URL` as the legacy fallback.
Host selects a configured origin including its public scheme; forwarded headers
cannot override it. Bookmarklets use that origin; PWA routes remain relative.
Browser preferences and installations are independent per origin. NetworkPolicy
adds defence in depth but cannot distinguish the fetcher and rmfakecloud client in
one pod. The application must therefore keep those clients strictly separate.

PWA cache contains only an explicit list of public shell files. API bodies, shared
URL query strings, converted files and authentication redirects are never cached.
A GET share target only prefills the form; sending always requires a user action.

Risks: article heuristics miss unusual/JS-only pages; native renderer vulnerabilities
still require patching and container limits; folder deletion can race an upload;
an upload timeout may mean success at the server. Real tablet sync, mobile install,
and deployment-specific ingress authentication require manual end-to-end testing.
