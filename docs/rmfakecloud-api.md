# rmfakecloud web API contract

Inspected upstream revision `962a73be4f7ad54aa0818987be34010c252a4753`.
This is a source-verified contract, not a claim of live-server or tablet testing.

The client appends `/ui/api` to `RMFAKECLOUD_URL` (configure the server origin,
optionally with a reverse-proxy path prefix, **not** `/ui/api` itself).

| Operation | Request | Response |
|---|---|---|
| Login | `POST /ui/api/login`, JSON `{"email":"…","password":"…"}` | HTTP 200, plain JWT string; also sets a cookie |
| List | `GET /ui/api/documents`, `Authorization: Bearer <JWT>` | `{"Entries":[…],"Trash":[…]}`; capitalised top-level keys |
| Upload | `POST /ui/api/documents/upload`, bearer token, multipart `parent` and `file` | HTTP 200, array of storage documents with capitalised `ID`, `Name`, `Parent`, `Type`, `Version` |

Folder nodes have lowercase `id`, `name`, `isFolder: true`, `children` (nested
array). Document nodes have a `type` and no `isFolder: true`. Only `Entries` is
traversed; `Trash` is excluded. Root is the empty parent string (upstream also
accepts `root`). IDs are passed through; labels display the full folder path.

The upload handler passes the multipart filename to `CreateDocument`. The filesystem
backend strips only the final extension and stores the remaining name as both `Name`
and the tablet metadata's `visibleName`; it does not require slugification. The app
therefore preserves spaces, Unicode and punctuation, removes path/control characters,
and bounds filenames to 180 UTF-8 bytes before the extension. Physical storage uses
UUIDs. Display and font coverage still require checking on the target tablet firmware.

Sources:

- [Routes](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/ui/routes.go)
- [Login, document listing and multipart handler](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/ui/handlers.go)
- [Cookie/bearer authentication and sync-version selection](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/ui/middleware.go)
- [Tree JSON structures](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/ui/viewmodel/models.go)
- [Document creation and visible name](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/storage/fs/documentcreator.go)
- [Upload response structure](https://github.com/ddvk/rmfakecloud/blob/962a73be4f7ad54aa0818987be34010c252a4753/internal/storage/storage.go)

Upstream selects sync 1.0 or 1.5 from the web JWT and notifies synchronisation
after upload. The application does not implement either tablet sync protocol.
The JWT is kept in memory, never persisted or forwarded to the browser. Cookies
are discarded; authentication middleware explicitly supports bearer tokens.
A 401 triggers one login and retry; other failures are not retried. Uploads can
return 409 for existing documents on versions supporting duplicate detection.

The client rejects a missing destination by listing folders immediately before
upload. A folder can still be deleted between that check and upstream accepting
the file; the web API offers no transaction for those operations. A timeout or
unexpected upload response can occur after the file was accepted. Check the tablet
or rmfakecloud web UI before resending.
