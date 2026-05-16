"""WSGI entry point — for ``gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app``.

``flask --app mymoney run`` uses the factory directly via the ``mymoney``
package import, so this file is only used by production-shaped servers.
"""

from __future__ import annotations

import os

from werkzeug.middleware.proxy_fix import ProxyFix

from mymoney import create_app


app = create_app()

# When deploying behind nginx/Caddy, set MYMONEY_BEHIND_PROXY=1 so Flask trusts
# the X-Forwarded-* headers for one hop.
#
# WARNING: only enable this when the app is provably behind a trusted reverse
# proxy that strips/sets those headers itself. If the app is exposed directly
# (e.g. accidentally bound to 0.0.0.0 without a proxy), clients can spoof
# X-Forwarded-For / X-Forwarded-Proto and defeat IP-based rate limiting,
# logging, and HTTPS detection.
if os.environ.get("MYMONEY_BEHIND_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
