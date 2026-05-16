"""Auth stub. No-op in dev (single-user localhost). Wire Flask-Login here when
flipping MYMONEY_AUTH=on. See INTERFACE_PLAN.md."""

from __future__ import annotations

from functools import wraps

from flask import abort, current_app


def requires_login(view):
    """Decorator applied to every protected route.

    Today: no-op when AUTH_ENABLED is False (the default in DevConfig).
    Tomorrow: swap the body for Flask-Login's @login_required.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_ENABLED", False):
            return view(*args, **kwargs)
        # Placeholder until Flask-Login is wired up. Refuse loudly rather than
        # silently allowing access if someone flips the flag prematurely.
        abort(401)

    return wrapper
