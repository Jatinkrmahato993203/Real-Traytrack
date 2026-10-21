"""
db — MySQL storage layer, split by area:

  core          connection pool, transactions, UTC time helpers
  migrations    versioned schema migrations (run on startup)
  seed          first-start data and back-fills
  activity      append-only activity log (live admin feed)
  colleges      colleges, contacts, mess halls
  complaints    complaints, follow-up, votes, ratings, student privacy
  alerts        alerts and their workflow
  inspections   checklist, inspections, photos, schedule
  staff         staff accounts
  notifications delivery record of every notification
  compliance    licences, certificates, test reports with expiry
  security      shared login lockout and job locks

Everything public is re-exported here, so callers use `import db` and
`db.get_alert(...)` without caring which module it lives in.
"""

from .core import *  # noqa: F401,F403
from .core import transaction, fetch_all, fetch_one, execute, utcnow, now_iso, to_db, ping, reset_pool, LEVELS  # noqa: F401
from .migrations import run_migrations, current_version  # noqa: F401
from .seed import seed  # noqa: F401
from .activity import (  # noqa: F401
    log_activity, get_activity, latest_activity_id, complaint_photo_url,
)
from .colleges import *  # noqa: F401,F403
from .complaints import *  # noqa: F401,F403
from .alerts import *  # noqa: F401,F403
from .inspections import *  # noqa: F401,F403
from .staff import *  # noqa: F401,F403
from . import notifications, compliance, security  # noqa: F401
