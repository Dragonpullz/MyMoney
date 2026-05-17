"""Refresh: POST /refresh accepts MCP dump JSON file(s), runs the importer and
summary builder, then invalidates in-process caches.

Security:
- CSRF-protected (Flask-WTF, wired in create_app()).
- Only ``.json`` files accepted (allow-list, not deny-list).
- Each upload saved into a per-request tempdir with secure_filename().
- Resolved path must stay inside the tempdir (path-traversal defense).
- subprocess.run([...], shell=False) with a fixed arg list — no user-controlled
  strings are ever interpolated into a shell.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, request, url_for
from werkzeug.utils import secure_filename

from ..auth import requires_login
from ..data import invalidate_cache


bp = Blueprint("refresh", __name__)

ALLOWED_EXTENSIONS = {".json"}


def _save_uploads(upload_root: Path) -> list[Path]:
    saved: list[Path] = []
    for file_storage in request.files.getlist("dumps"):
        if not file_storage or not file_storage.filename:
            continue
        name = secure_filename(file_storage.filename)
        if not name:
            raise ValueError("Invalid filename in upload.")
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_storage.filename}")
        target = (upload_root / name).resolve()
        # Path traversal defense: resolved target must live inside upload_root.
        try:
            target.relative_to(upload_root.resolve())
        except ValueError:
            raise ValueError("Rejected path outside upload directory.")
        file_storage.save(target)
        saved.append(target)
    return saved


def _run(cmd: list[str]) -> None:
    # shell=False is the default for list args; pass it explicitly for clarity.
    # Capture stderr so we can log it server-side without surfacing it to the
    # user (could contain local paths / internals).
    subprocess.run(
        cmd,
        check=True,
        shell=False,
        cwd=current_app.config["ANALYSIS_DIR"].parent,
        capture_output=True,
        text=True,
    )


@bp.route("/refresh", methods=["POST"])
@requires_login
def refresh():
    analysis_dir: Path = current_app.config["ANALYSIS_DIR"]
    importer = analysis_dir / "Import-BankSyncDump.py"
    summary_builder = analysis_dir / "Build-Summary.py"

    with tempfile.TemporaryDirectory(prefix="mymoney-upload-") as tmp:
        upload_root = Path(tmp)
        try:
            saved = _save_uploads(upload_root)
        except ValueError as exc:
            flash(f"Upload rejected: {exc}", "error")
            return redirect(url_for("home.index"))

        if not saved:
            flash("No dump files uploaded.", "error")
            return redirect(url_for("home.index"))

        try:
            _run([sys.executable, str(importer), "-Files", *map(str, saved)])
            _run([sys.executable, str(summary_builder)])
        except subprocess.CalledProcessError as exc:
            # Log the full stderr server-side; tell the user only the exit code.
            current_app.logger.error(
                "Refresh subprocess failed: cmd=%r returncode=%s stderr=%s",
                exc.cmd, exc.returncode, (exc.stderr or "").strip(),
            )
            flash(f"Refresh failed (exit {exc.returncode}). Check server logs.", "error")
            return redirect(url_for("home.index"))

    invalidate_cache()
    flash(f"Refreshed from {len(saved)} dump file(s).", "success")
    return redirect(url_for("home.index"))
