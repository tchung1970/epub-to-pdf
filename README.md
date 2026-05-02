# epub-to-pdf

A small self-hosted web app that converts EPUB ebooks to PDF in the browser.
Drag a file in, click **Convert to PDF**, download the result. Conversion is
done server-side by Calibre's `ebook-convert`.

Live instance: <https://ai.tchung.org/epub-to-pdf/>

## Architecture

```
browser ──HTTPS──▶ nginx (443) ──/epub-to-pdf/──▶ Flask (127.0.0.1:5001) ──▶ ebook-convert
```

- `web.py` — Flask app. Two endpoints: `GET /` serves `index.html`,
  `POST /convert` takes a `multipart/form-data` upload named `file`, runs
  `ebook-convert`, and streams the PDF back. Health check at `/healthz`.
- `index.html` — single-file frontend (vanilla JS, no build step). Resolves
  `/convert` *relative to the page*, so it works both at `/` and behind a
  reverse-proxy subpath like `/epub-to-pdf/`.
- Upload limit: 25 MB. Conversion timeout: 300 s.

## Requirements

- Python 3 + Flask (`apt install python3-flask`)
- Calibre 7.x (`apt install --no-install-recommends calibre`) — supplies
  `/usr/bin/ebook-convert`
- Linux service host (the deploy notes below assume Ubuntu 24.04 + nginx +
  systemd, with a TLS cert already provisioned)

## Local development

```bash
python3 web.py          # serves on http://127.0.0.1:5001
```

Then open <http://127.0.0.1:5001/> in a browser.

## Deployment

The repository is laid out for the simple "single-file Flask app behind nginx
on a shared VM" pattern. There is no container or CI — deployment is `scp` +
`systemctl`.

### 1. Install dependencies (once)

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends calibre python3-flask
```

### 2. Copy the app

```bash
sudo mkdir -p /var/www/html/epub-to-pdf
sudo scp web.py index.html user@host:/var/www/html/epub-to-pdf/
```

### 3. Install the systemd unit

Copy [`deploy/epub-to-pdf.service`](deploy/epub-to-pdf.service) to
`/etc/systemd/system/epub-to-pdf.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now epub-to-pdf.service
```

### 4. Wire up nginx

Add the contents of [`deploy/nginx-location.conf`](deploy/nginx-location.conf)
inside the relevant `server { ... }` block of your nginx config (e.g.
`/etc/nginx/sites-enabled/default`), then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

To serve at the apex instead of a subpath, change `location /epub-to-pdf/`
to `location /` and drop the trailing slash on `proxy_pass`.

### 5. Smoke test

```bash
curl -s https://your.host/epub-to-pdf/healthz
# {"ebook_convert":"/usr/bin/ebook-convert","ok":true}
```

## Notes

### Calibre as root needs `--no-sandbox`

Calibre 7.x renders PDF through QtWebEngine's bundled Chromium, which refuses
to run as root without `--no-sandbox`. The systemd unit therefore sets:

```
Environment=QTWEBENGINE_DISABLE_SANDBOX=1
Environment=QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox
```

If you change the unit to run under a non-root `User=`, both env vars can be
removed.

### Production WSGI

`web.py` uses Flask's built-in dev server, which logs a warning at startup.
For a personal-scale deployment that's fine; if you want to silence the
warning or get better concurrency, swap the unit's `ExecStart` to gunicorn:

```
ExecStart=/usr/bin/gunicorn -b 127.0.0.1:5001 -w 2 -t 600 web:app
```

(`apt install gunicorn` on Ubuntu.)

### Conversion options

The exact `ebook-convert` flags live in `web.py`. Defaults aim to match
the look of a typical EPUB reader rather than an A4 document:

- **6"×9" trade-paperback page** (`--custom-size 6inx9in`). Calibre
  rejects `--paper-size custom`, so `--paper-size` is left at `letter`
  and gets overridden by `--custom-size`.
- **54 pt margins** all around (~0.75").
- **Empty header template** to suppress Calibre's default top rule.
- **Centered page number footer** via the `_PAGENUM_` placeholder.

Tweak in `web.py` if you want A4, larger margins, etc.

## Layout

```
.
├── README.md
├── web.py                       # Flask backend
├── index.html                   # Frontend
└── deploy/
    ├── epub-to-pdf.service      # systemd unit
    └── nginx-location.conf      # nginx reverse-proxy block
```
