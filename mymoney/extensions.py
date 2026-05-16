"""Flask extensions instantiated at module scope, initialized in create_app()."""

from __future__ import annotations

from flask_wtf.csrf import CSRFProtect


csrf = CSRFProtect()
