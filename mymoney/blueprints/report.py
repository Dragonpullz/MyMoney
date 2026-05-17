"""Monthly report: render the Markdown produced by Build-MonthlyReport.py.

Rendered with markdown + bleach allow-list to defend against HTML injection
even from our own report generator.
"""

from __future__ import annotations

import re
from pathlib import Path

import bleach
import markdown as md
from flask import Blueprint, abort, current_app, render_template

from ..auth import requires_login


bp = Blueprint("report", __name__)


# Conservative allow-list. Tables come from the markdown 'tables' extension.
_ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img",
]
_ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "th": ["align"],
    "td": ["align"],
}


def _safe_month(month: str) -> str:
    if not re.match(r"^\d{4}-\d{2}$", month):
        abort(404)
    return month


@bp.route("/report/<month>")
@requires_login
def show(month: str):
    month = _safe_month(month)
    reports_dir: Path = current_app.config["ANALYSIS_DIR"] / "reports"
    report_path = (reports_dir / f"{month}.md").resolve()

    if not report_path.exists():
        return render_template("report.html", month=month, body=None, missing=True)

    # Path traversal defense: resolved path must live under reports_dir.
    # _safe_month already rejects "../" via regex, but defense in depth.
    try:
        report_path.relative_to(reports_dir.resolve())
    except ValueError:
        abort(404)

    text = report_path.read_text(encoding="utf-8")
    html = md.markdown(text, extensions=["tables", "fenced_code"])
    safe_html = bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)
    return render_template("report.html", month=month, body=safe_html, missing=False)
