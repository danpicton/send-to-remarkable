# Send to reMarkable

A small self-hosted PWA: share or paste an article URL, choose PDF or EPUB and a
folder, then send it through your existing rmfakecloud server. You can also just
download the file. There is no database, reading history, registration system or queue.

Python 3.12+, FastAPI, Trafilatura, WeasyPrint, EbookLib, plain HTML/CSS/JavaScript.
Python packages are managed with **uv**. The project is AGPL-3.0 licensed, matching
[EbookLib's licence](https://github.com/aerkalov/ebooklib/blob/master/LICENSE.txt).
Dependencies retain their own licences. This is an independent project. When
sharing a hosted or modified build, make its corresponding source available to
its users (for example, link your source repository from the deployment).

## Run locally

On Debian/Ubuntu, install the renderer's native libraries and fonts:

```sh
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
uv sync
cp .env.example .env
```

Edit `.env` with your server settings. For local development, set
`APP_BASE_URL=http://localhost:8000` and `AUTH_MODE=development`, then run:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open **http://localhost:8000** (not `127.0.0.1`; the configured Host must match).
Omit rmfakecloud credentials to use local downloads only. Development mode disables
authentication; keep it bound to loopback. Production requires HTTPS and either an authenticating
reverse proxy or the built-in session login. Use Linux for the resource-limited processing workers.

## Use it

1. Paste a public HTTP(S) article URL.
2. Optionally enter an **Article title**, or click **Use page title** to load and edit
   the HTML title. Leaving it blank uses the page title automatically.
3. Choose PDF (A5 pages, serif text, metadata and page numbers) or EPUB (reflowable
   XHTML, metadata and navigation).
4. Choose **Send to reMarkable** and a destination, or **Download locally**.
5. Press the action button. After conversion a download link remains available,
   including when an upload fails. Successful upload means rmfakecloud accepted
   the document; the tablet still needs to synchronise.

Titles apply to document headings, metadata and filenames. Filenames preserve spaces,
accents and punctuation; path separators and control characters become spaces,
straight double quotes become typographic double quotes, and names are limited to
180 UTF-8 bytes plus the extension. Titles are not saved as browser preferences.

Format, delivery mode and folder are stored only in this browser's `localStorage`.
Other devices have independent preferences. URLs and article contents are not
stored there. If a successful folder refresh shows that the saved folder was
deleted, it selects root and updates the preference. A connection failure does
not erase the saved folder. Clearing browser storage resets preferences.

The browser holds one converted file in memory until the next conversion or page
close. Closing or refreshing loses it; there is no server-side document library.
If an upload times out, check rmfakecloud or the tablet before retrying to avoid
creating duplicates. The web API's folder check cannot prevent a simultaneous
folder deletion by another client.

## Mobile sharing and bookmarklet

Serve at an HTTPS origin root (subpath hosting is not supported). Certificates
must be trusted by the device. Localhost is an exception for development.

**Android Chrome:** sign in through your proxy, open the app and choose Install
app/Add to Home screen. Share an article from your browser and choose **Send to
reMarkable**. The manifest's GET share target accepts `url`, `text`, and `title`;
URL takes precedence. Sharing only fills the form, never triggers an upload.
Installation and OS share-sheet availability must be checked on your device.

After upgrading from a shortcut-only installation, open the site online, sign in,
reload once so the updated service worker controls the page, and remove the old
shortcut. Install again from Chrome or Brave's menu. Confirm it opens standalone
and appears in Android's app settings, then share a URL to it from another app.
Test both a cold launch and a text-only shared URL.

The manifest link uses `crossorigin="use-credentials"` so an authenticating proxy
receives the browser session when the browser discovers the manifest (required
even on the same origin). Manifest and PNG icons bypass the service-worker cache
so installation metadata stays current. In remote DevTools, check Application →
Manifest for errors and confirm the manifest/icon responses are JSON/PNG, not
a proxy login page. HTTPS must have a certificate trusted by the phone.

See [Chrome's share-target documentation](https://developer.chrome.com/docs/capabilities/web-apis/web-share-target).

**iPhone/iPad:** install to the Home Screen if desired. Where native share-target
support is unavailable, create an Apple Shortcut:

1. Enable **Show in Share Sheet**, accepting URLs and Safari web pages.
2. Use **Get URLs from Input**, then **Get Item from List → First Item**.
3. **URL Encode** that URL.
4. Build Text: `https://reader.example.internal/?url=` followed by the encoded URL.
5. Use **Open URLs** with that text. Name the shortcut “Send to reMarkable”.

Sign in to the proxy in Safari first. Share an article, select the shortcut, then
choose the format/destination in the app. Browser support varies; see the
[share_target compatibility table](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest/Reference/share_target#browser_compatibility).

**Desktop bookmarklet:** expand **Share from your browser** in the app and drag
the bookmarklet link to the bookmarks toolbar. Alternatively use **copy the
bookmarklet**, create a bookmark and paste it into the bookmark's URL field.
Click that bookmark while viewing an article. The target uses the allowed origin
you opened the app on, so each hostname generates a bookmarklet for itself.
Some websites/browser policies block bookmarklets; paste/share the URL instead.
The app also accepts `/?url=<encoded-URL>` directly.

The service worker caches only an explicit shell asset list. Offline, it can show
the form; extraction and sending require a connection. API responses, documents,
query URLs and login redirects are not cached. Bump the cache version in `sw.js`
when changing shell files in a release. Proxy login redirects can interrupt
sharing or installation; sign in first and try again.

## Configuration

Copy `.env.example`. Environment variables override `.env`. Never put real secrets
in the repository. Credentials belong to an existing rmfakecloud web user.

| Variable | Default | Meaning |
|---|---|---|
| `APP_BASE_URL` | `http://localhost:8000` | Single-origin fallback when `APP_ALLOWED_ORIGINS` is unset |
| `APP_ALLOWED_ORIGINS` | unset | JSON array of exact public origins; overrides `APP_BASE_URL` |
| `AUTH_MODE` | `proxy` | `proxy` requires identity header; `session` enables built-in login; `development` is local-only |
| `AUTH_SESSION_SECRET` | empty | Session mode: stable random signing key, at least 32 characters |
| `AUTH_SESSION_DAYS` | `30` | Session mode: fixed login lifetime in days (1–90) |
| `AUTH_HEADER` | `X-Auth-Request-User` | Identity header set by trusted authenticating ingress |
| `RMFAKECLOUD_URL` | empty | Trusted server base URL, without `/ui/api` |
| `RMFAKECLOUD_USERNAME` | empty | Web login email/user ID |
| `RMFAKECLOUD_PASSWORD` | empty | Web login password; server-side only |
| `RMFAKECLOUD_VERIFY_TLS` | `true` | Verify server TLS; never silently disabled |
| `RMFAKECLOUD_CA_BUNDLE` | unset | Custom PEM CA bundle; preferred for private certificates |
| `FETCH_TIMEOUT` | `20` | Seconds for the whole fetch, including redirects and DNS |
| `CONVERSION_TIMEOUT` | `40` | Seconds before killing the extraction/rendering worker |
| `RMFAKECLOUD_TIMEOUT` | `20` | Seconds per login/list/upload request |
| `MAX_PAGE_BYTES` | `4194304` | Maximum HTML download size (4 MiB) |
| `MAX_DOCUMENT_BYTES` | `20971520` | Maximum generated/uploaded file (20 MiB) |
| `MAX_ARTICLE_CHARS` | `200000` | Extracted HTML length bound |
| `MAX_CONVERSIONS` | `2` | Active processing/upload operations; excess gets 429 |
| `WORKER_MEMORY_MB` | `768` | Linux address-space limit per worker |
| `TEMP_DIR` | `/tmp/send-to-remarkable` | Temporary jobs, removed after success/failure/timeout |

One instance can serve any configured set of hostnames. For example, in `.env`:

```dotenv
APP_ALLOWED_ORIGINS='["https://reader.example.net","https://reader.other.example.net"]'
```

Use full origins (scheme, hostname and optional port), without paths or wildcards.
Configure one public scheme per host/port so the app can identify the correct
public origin behind TLS termination. The list replaces the single-origin fallback;
localhost is not implicitly allowed when a list is set. Existing deployments using
only `APP_BASE_URL` continue to work. Multi-origin support requires v0.1.1 or newer.

Route each hostname to the same Service, with HTTPS and authentication on every
ingress route. Preserve the incoming Host. Bookmarklets use the matching allowed
origin; PWA/share-target routes are relative and stay on that hostname. Preferences,
proxy sessions and PWA installations remain separate per browser origin, even on
the same device. There is no preference synchronisation across hostnames.

Allowlisting multiple origins does not enable cross-origin API calls: a POST must
still come from the exact public origin corresponding to its request Host.

Keep one Uvicorn worker per pod; limits are per process. Kubernetes example uses
one conversion at a time within a 1 GiB memory limit. Increase container memory
if you increase concurrency. Resource limits are protective bounds, not a promise
that all articles below the input limit will fit.

## Built-in login

Set `AUTH_MODE=session` to use a single-account login form instead of proxy
authentication. Sign in with the configured `RMFAKECLOUD_USERNAME` and
`RMFAKECLOUD_PASSWORD`. Set `AUTH_SESSION_SECRET` to a stable, randomly generated
secret of at least 32 characters through your normal secret-management workflow.
All configured public origins must use HTTPS. Proxy mode remains the default.

Sessions last 30 days by default (`AUTH_SESSION_DAYS`), with no sliding renewal.
The signed cookie is Secure, HttpOnly, SameSite=Strict, and host-only; sessions are
also bound to the public origin. They survive app restarts if the signing key and
credentials stay unchanged. Changing either credential or the signing key
invalidates existing sessions. Sign out removes this browser's cookie; a copied
cookie remains usable until expiry or credential/key rotation.

Login attempts are limited to five per minute across the account, per process.
Keep one worker and one replica; this in-memory throttle resets on restart.
The app shell, health check, and login/session endpoints are public; other API
routes require a valid session and ignore proxy identity headers. Login/logout
POSTs have the same origin and custom-header checks as other POSTs. Credentials
and API responses are never cached by the service worker.

For an existing Basic Auth deployment, configure and roll out a compatible app
image with session mode and its signing key first, then remove the Basic Auth
middleware from the ingress. Retain HTTPS, request limits, and network isolation.
Home and meshnet hostnames have independent sessions. Shared article URLs remain
in the form while signing in.

## API

All `/api/*` responses use `Cache-Control: no-store`. Errors are
`{"error":{"code":"…","message":"…"}}`. The API intentionally has no CORS access.
For POSTs send `Origin: <the configured public origin matching the request Host>` and
`X-Requested-With: SendToRemarkable`, plus authentication through your proxy.

| Endpoint | Request / response |
|---|---|
| `GET /api/health` | Unauthenticated liveness: `{"status":"ok"}`; does not contact cloud |
| `GET /api/config` | Allowed public origin matching this request's Host; no credentials |
| `GET /api/folders` | `{"folders":[{"id":"","name":"Root","path":"/","parent":""},…]}` |
| `POST /api/extract` | JSON `{"url":"https://…"}` → sanitised HTML and article metadata |
| `POST /api/convert` | JSON `{"url":"https://…","format":"pdf","title":"Optional title"}` → attachment bytes |
| `POST /api/send` | Multipart `file` (PDF/EPUB) and `folder` (ID, empty for root) → `{"id":"…","name":"…"}` |

The send endpoint accepts an already converted file. This avoids doing conversion
twice and lets the UI preserve the exact file when rmfakecloud is unavailable.
Uploaded filenames and file signatures are checked; this is not a general PDF/EPUB
security scanner. Only authenticated, trusted personal users should have access.

[rmfakecloud API notes](docs/rmfakecloud-api.md) record the inspected upstream
revision, payload casing and response shapes. No official-cloud API assumptions
are used. TLS errors, authentication failures, malformed responses, missing
folders and timeouts receive distinct errors without upstream response bodies.

## Security and limits

Do **not** publish an unauthenticated arbitrary-URL fetcher, even on a home LAN.
Production authentication uses the built-in session login or your existing proxy
(e.g. an OIDC forward-auth service). In proxy mode, The proxy must **strip any incoming identity header**,
authenticate the user, and set `AUTH_HEADER` itself. Restrict the Service/Pod so
only that proxy can reach it; a spoofable header on an exposed port is not auth.
Configure the proxy to forward the original Host unchanged. The app does not trust
forwarded-host headers. Allow `/api/health` for cluster probes, and keep other
API routes protected. Preserve or restore shared query parameters after login.

Additional protections:

- Public HTTP(S), ports 80/443 only. Reject userinfo, local/special IPs, legacy
  numeric addresses and IPv6 transition mechanisms. Validate every DNS result at
  connection time and pass the validated IPs directly to aiohttp's connector;
  every redirect is checked again. No environment proxies, browser cookies,
  automatic redirects or DNS cache in the article client.
- Five-redirect, download-size, total-time and read-time limits. Requests advertise
  `Accept-Encoding: identity`; compressed responses are rejected in v1, avoiding
  decompression bombs. Sites that insist on compression currently fail clearly.
- HTML allowlist removes scripts, handlers, styles, frames, SVG, images and other
  embedded resources. Metadata is escaped. WeasyPrint's resource fetcher denies
  **all** external, local-file and data-URI requests. Links remain clickable, but
  nothing follows them while processing. Review links before opening them.
- Parsing/rendering runs in a terminable subprocess with address-space, CPU and
  file-size limits. The subprocess does not inherit cloud credentials. No queue;
  admission limits, small JSON bodies and bounded multipart bodies limit work.
- Same-origin POST validation plus a custom header, strict Host validation, no
  CORS, CSP, framing denial, no-referrer, and no API cache. Origin checks complement
  authentication; they do not replace it. The service worker stores no API data.

Use the example NetworkPolicy as defence in depth. It allows public IPv4 web
traffic, cluster DNS, and the selected rmfakecloud pods. It denies public IPv6
until you deliberately add an equivalent policy. Adapt it for your CNI, node-local
DNS and topology. CNI NAT/policy behaviour varies: verify enforcement. Because both
clients are in one pod, the trusted rmfakecloud exception also exists at the pod
network layer; the public fetcher's application checks remain essential. Stronger
isolation would require a separate fetch service/egress proxy and is outside v1.

Trusted DNS must not maliciously map global IPs into private networks; app-level
checks cannot defend against arbitrary routing/NAT or compromised native libraries.
Keep dependencies/images patched. The worker is resource-limited, not a separate
security sandbox. The supplied container runs non-root and can use a read-only root
filesystem. Temporary jobs are cleaned after normal completion, cancellation and
timeout; a process/pod crash may leave files until the ephemeral volume is removed.
No access log is enabled in the container, but configure ingress logs to avoid
recording shared URL query strings and never log request bodies or secrets.

## Container and Kubernetes

The [CI and container workflow](.github/workflows/ci.yml) runs Python/JavaScript
tests and lint on `main`, pull requests and version tags. It builds and smoke-tests
the amd64 runtime as a non-root user, with a read-only filesystem and no network,
including PDF/EPUB generation through the isolated worker.

Pushing a version tag publishes **linux/amd64** and **linux/arm64** images to
`ghcr.io/danpicton/send-to-remarkable`, after those checks pass. For example:

```sh
git tag -a v0.1.1 -m 'Release 0.1.1'
git push origin v0.1.1
```

That publishes `:0.1.1`, `:0.1`, `:latest`, and `:sha-<full-commit-SHA>`. Prerelease
tags such as `v0.2.0-rc.1` publish only the prerelease and commit tags; they do not
move `latest` or `0.2`. Only tag-push events publish; manual workflow runs validate
without publishing. Publish stable tags in release order, because a stable tag
updates `latest`. Use a version or image digest in Kubernetes for reproducibility.

The workflow uses GitHub's built-in `GITHUB_TOKEN` with `packages: write` only in
the publish job; no personal access token or repository secret is needed. Actions
are pinned to commits, with monthly Dependabot updates. On the first publish,
GHCR may create a private package even for a public repository. In the package's
settings, set visibility to public if you want anonymous pulls; otherwise configure
your cluster's image pull credentials. The image's source label links it to the
repository. Forks automatically publish under their own owner/repository name.

After publishing v0.1.1, use
`ghcr.io/danpicton/send-to-remarkable:0.1.1`. To build it yourself:

```sh
docker build -t your-registry/send-to-remarkable:0.1.1 .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env \
  --read-only --tmpfs /tmp:rw,nosuid,size=128m \
  --memory=1g --cpus=2 -e MAX_CONVERSIONS=1 \
  your-registry/send-to-remarkable:0.1.1
```

The multi-stage image installs locked dependencies with uv, includes Pango/fonts,
runs as UID 10001 and has an HTTP health check. It requires no persistent volume.

For Kubernetes, edit `deploy/kubernetes/workload.yaml` and
`network-policy.yaml` for your image, HTTPS origin, cloud URL and cluster labels.
Create namespace `reader`, then create the Secret using your normal secret workflow
(`secret.example.yaml` shows the keys). Apply the workload and policy. The example
Service is ClusterIP only. Route your **existing authenticating HTTPS ingress** to
`reader/send-to-remarkable:80`, preserving Host and injecting the identity header.
No new ingress controller, cert-manager or storage is required.

Set ingress body limit to at least **21 MiB**, request-body timeout at most **15 s**,
and upstream response timeout to at least **150 s**. Rate-limit the endpoint at
ingress (e.g. a few conversion requests per minute for personal use). Block direct
NodePort/LoadBalancer exposure. For cloud TLS with a private CA, mount its PEM file
and set `RMFAKECLOUD_CA_BUNDLE`; leave verification on. Plain HTTP cloud traffic is
only appropriate on a trusted cluster network. Verify network policy permits the
actual configured cloud address; the example uses rmfakecloud port 3000.

## Tests and manual verification

```sh
uv sync --frozen
uv run pytest
uv run ruff check .
node --test tests/*.test.mjs
```

Python tests use local HTML fixtures and mocked network transports: URL and DNS
validation, redirects and limits, metadata/semantic extraction, PDF contents,
EPUB XML/container/navigation, worker timeout/cleanup/concurrency, rmfakecloud
login and multipart contract, stale folders, API errors and cross-site protection.
Node's built-in tests cover preference isolation, shared inputs, bookmarklet
behaviour, retained downloads and service-worker cache boundaries; no npm install
is required. In restricted sandboxes that block local socket writes, a conditional
test-only timer wakes Python's event loop for subprocess/thread completion; it is
inactive on normal hosts and does not alter application results or deadlines.
Native Pango libraries are needed for PDF tests. EPUB structural tests are not a
full EPUBCheck certification.

Optional manual end-to-end test (requires your real rmfakecloud and tablet):

1. Sign in to the app through HTTPS ingress. Confirm unauthenticated API calls and
   direct Service access are denied; spoofing the identity header must not bypass
   ingress authentication. Verify NetworkPolicy blocks internal article URLs.
2. Convert a conventional public article to PDF and EPUB. Open both locally; check
   headings, byline, links, page breaks, EPUB navigation and accents/non-ASCII text.
3. Compare folder paths with rmfakecloud's web UI. Send each format to a nested
   folder and root. Confirm the returned document ID in the cloud UI, then sync
   the tablet and open both files there. Check both formats on your firmware.
4. Stop/block rmfakecloud and convert again. Sending should fail while the exact
   converted file remains downloadable. Restore cloud connectivity and refresh.
5. Save a folder preference, remove that folder using rmfakecloud, and refresh.
   Verify root is selected. Also test a stale folder during upload.
6. Install the PWA on Android Chrome; share URLs from more than one browser/app.
   Check cold launch, proxy-login expiry, `text`-only shares and offline shell.
   Confirm Cache Storage contains shell files only after converting/sending.
7. Use the desktop bookmarklet and iOS Shortcut. Set different preferences on two
   devices and verify they remain independent after reload.

Container builds, cluster policy enforcement, real rmfakecloud upload/sync, and
mobile installation require verification in the target environment. Automated
mocks are not a substitute for that integration check.

## Troubleshooting and v1 boundaries

- **401:** proxy did not inject the configured identity header, or login expired.
- **400 invalid host / 403 cross-site:** the hostname is missing from
  `APP_ALLOWED_ORIGINS` (or the `APP_BASE_URL` fallback), ingress rewrote Host/Origin,
  or a request crossed between origins. Each POST's Origin must match its Host.
- **Cloud authentication error:** check web username/password and server base URL.
  Confirm the web UI works and compare the documented source contract with your
  rmfakecloud version. Never include `/ui/api` in `RMFAKECLOUD_URL`.
- **TLS failure:** supply the correct CA bundle; `VERIFY_TLS=false` is an explicit
  opt-out for diagnosis, not the default. Article-site TLS is always verified.
- **No readable article:** extraction is heuristic. Paywalls, login-required pages,
  CAPTCHA screens and JavaScript-rendered content are not supported reliably.
- **Compression / size / timeout error:** that article is outside v1's bounds.
  Try another source; raise limits cautiously with matching container resources.
- **PDF fails:** check Pango/fonts and worker/container memory. EPUB uses less work.
- **429:** a conversion/upload is already using the configured capacity; retry later.
- **PWA not installable:** check HTTPS trust, manifest/icons, proxy redirects and
  DevTools → Application. A local hostname over plain HTTP is not sufficient.

Images are deliberately omitted. A future image stage belongs between extraction
and generation: fetch through the same public resolver, bound decoded pixels/bytes,
reject SVG/active types, re-encode validated raster data, and supply only those
in-memory assets to the renderer. A future Playwright extractor must have equivalent
network isolation for every browser request; simply navigating a validated URL is
not sufficient. The `Extractor` protocol allows alternatives without changing API
handlers. No browser engine or separate Readability service is required for v1.

See [architecture decisions](docs/architecture.md) for the design and risks.
