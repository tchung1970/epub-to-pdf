#!/usr/bin/env python3
"""
epub-to-pdf web app — Upload an EPUB and download a converted PDF.

Backed by Calibre's `ebook-convert`. Runs on 127.0.0.1:5001 behind nginx
which proxies https://ai.tchung.org/epub-to-pdf/ to this service.
"""

import io
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory, abort

APP_DIR = Path(__file__).parent
EBOOK_CONVERT = shutil.which("ebook-convert") or "/usr/bin/ebook-convert"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
CONVERT_TIMEOUT = 300  # seconds

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/healthz")
def healthz():
    return jsonify(ok=True, ebook_convert=EBOOK_CONVERT)


@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("file")
    if f is None or f.filename == "":
        return jsonify(error="No file uploaded"), 400

    orig_name = Path(f.filename).name
    if not orig_name.lower().endswith(".epub"):
        return jsonify(error="Only .epub files are supported"), 400

    job_dir = Path(tempfile.mkdtemp(prefix="epub2pdf-"))
    try:
        in_path = job_dir / f"in-{uuid.uuid4().hex}.epub"
        out_path = job_dir / f"out-{uuid.uuid4().hex}.pdf"
        f.save(in_path)

        cmd = [
            EBOOK_CONVERT,
            str(in_path),
            str(out_path),
            # 6"x9" trade-paperback page (Calibre takes pts: 1in = 72pt).
            "--paper-size", "custom",
            "--custom-size", "432x648",
            "--pdf-page-margin-top", "54",
            "--pdf-page-margin-bottom", "54",
            "--pdf-page-margin-left", "54",
            "--pdf-page-margin-right", "54",
            # Suppress Calibre's default running header (the blue rule at top).
            "--pdf-header-template", "<div></div>",
            "--pdf-footer-template",
            "<div style='text-align:center; font-size:9pt; color:#666;'>_PAGENUM_</div>",
            "--pretty-print",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CONVERT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return jsonify(error="Conversion timed out"), 504

        if proc.returncode != 0 or not out_path.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-10:]
            return jsonify(
                error="Conversion failed",
                detail="\n".join(tail),
            ), 500

        # Read into memory so we can clean the temp dir before returning.
        pdf_bytes = out_path.read_bytes()

        download_name = Path(orig_name).with_suffix(".pdf").name
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=download_name,
        )
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit"), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
