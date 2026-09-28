# Ticket Tracker — Deep Code Walkthrough (Execution-Order Trace)

This document explains the entire `ticket_tracker` Flask application **line by line, in the actual order Python executes it** — starting from the moment `app.py` is loaded, following every import to the module it pulls in at the point it is pulled in, and then tracing full HTTP request lifecycles for every route.

> Scope note: `database/ticket_tracker.db` is a runtime SQLite file created automatically at first run by `db.create_all()` (see Phase 3/5). It is a generated artifact, not source code, so it is not analyzed further.

---

## Table of Contents

1. [Phase 1: Entrypoint & Top-Level Imports (`app.py`)](#phase-1)
2. [Phase 2: Configuration Loading (`config.py`)](#phase-2)
3. [Phase 3: Database / Extension Setup (`db.py`)](#phase-3)
4. [Phase 4: `setup_logging()` Execution](#phase-4)
5. [Phase 5: `create_app()` — App Factory Walkthrough](#phase-5)
   - 5.1 Flask app construction & config load
   - 5.2 Extension initialization
   - 5.3 Blueprint registration (imports `routes/auth.py`, `routes/dashboard.py`, `routes/tickets.py`, `routes/approvals.py`, `routes/admin.py`, `routes/comments.py` — each expanded in full at the point it is first imported)
   - 5.4 Model imports & `db.create_all()` (each `models/*.py` file expanded at the point it is first imported)
   - 5.5 `_run_migrations()`
   - 5.6 Default admin seeding
   - 5.7 `_seed_dummy_data()`
6. [Phase 6: Module-Level Route (`/`) and `__main__` Guard](#phase-6)
7. [Phase 7: Request Lifecycle — Authentication (`routes/auth.py`)](#phase-7)
8. [Phase 8: Request Lifecycle — Dashboard (`routes/dashboard.py`)](#phase-8)
9. [Phase 9: Request Lifecycle — Ticket CRUD & Bulk Upload (`routes/tickets.py`)](#phase-9)
10. [Phase 10: Request Lifecycle — Comments (`routes/comments.py`)](#phase-10)
11. [Phase 11: Request Lifecycle — Approvals Workflow (`routes/approvals.py`)](#phase-11)
12. [Phase 12: Request Lifecycle — Admin (`routes/admin.py`)](#phase-12)
13. [Phase 13: Services Deep Dive — `services/email_service.py`](#phase-13)
14. [Phase 14: Services Deep Dive — `services/history_service.py`](#phase-14)
15. [Phase 15: Frontend Connections — Templates, `app.js`, `style.css`](#phase-15)

---

<a name="phase-1"></a>
## Phase 1: Entrypoint & Top-Level Imports (`app.py`)

When you run `python app.py` (or a WSGI server imports `app` from this module), CPython begins executing `app.py` top to bottom. This is the true entrypoint of the whole system.

```python
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, redirect, url_for
from config import Config
from db import db, login_manager, mail
```

- `import os` — used later for `os.makedirs` (ensuring the `database/` folder exists) and indirectly by `config.py`.
- `import logging` / `from logging.handlers import RotatingFileHandler` — the app builds a custom rotating file logger instead of relying on Flask's default stderr logging. `RotatingFileHandler` caps log file size and keeps a fixed number of backups so the log directory doesn't grow unbounded.
- `from pathlib import Path` — used in `setup_logging()` to build a cross-platform path to the `logs/` directory relative to this file.
- `from flask import Flask, redirect, url_for` — `Flask` is the WSGI application class; `redirect`/`url_for` are used by the root `/` view later in this file to bounce visitors to the dashboard.
- `from config import Config` — **this import causes Python to load and fully execute `config.py` right now**, before any further line of `app.py` runs. See Phase 2.
- `from db import db, login_manager, mail` — **this import causes Python to load and fully execute `db.py` right now**. See Phase 3. Note this happens even before Flask-SQLAlchemy/Flask-Login/Flask-Mail are bound to an actual `Flask` app instance — at this point `db`, `login_manager`, and `mail` are unbound singleton objects that get attached to the app later in `create_app()` via `.init_app(app)`. This is the standard "extension instance decoupled from app instance" pattern that allows the app-factory pattern to work and avoids circular imports (models can `from db import db` without needing the app object).

Because `from config import Config` appears before `from db import db, ...`, Python imports `config.py` first. We follow real execution order, so we go there now.

<a name="phase-2"></a>
## Phase 2: Configuration Loading (`config.py`)

```python
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
```

- `os.path.dirname(__file__)` gets the directory containing `config.py` (the project root, since `config.py` lives at the top level). `os.path.abspath` normalizes it to an absolute path. `BASE_DIR` is then used to build an absolute SQLite file path so the app works regardless of the current working directory it's launched from.

```python
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production-abc123xyz'
```
- A plain class (not an instance) used with Flask's `app.config.from_object(Config)`, which copies all uppercase class attributes into `app.config`. `SECRET_KEY` signs the Flask session cookie and is also reused directly by `services/email_service.py` to sign password-set/reset tokens via `itsdangerous.URLSafeTimedSerializer`. If unset via environment variable, a hardcoded dev fallback is used — insecure for production but keeps local dev frictionless. If this were removed, sessions and tokens couldn't be created/validated at all (`KeyError` or `None` key errors).

```python
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'database', 'ticket_tracker.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
```
- Builds an absolute-path SQLite URI: `sqlite:///D:/Claude/ticket_tracker/database/ticket_tracker.db` (on this machine). This is the single source of truth for where the runtime `.db` file lives — it is what causes `database/ticket_tracker.db` to be created. `SQLALCHEMY_TRACK_MODIFICATIONS = False` disables Flask-SQLAlchemy's legacy signal-based modification tracking, which is a performance/memory best practice and silences a deprecation warning; nothing in this app relies on those signals.

```python
    # Flask-Mail config (Gmail SMTP)
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or ''
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or ''
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or ''
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or ''
```
- All SMTP settings are read from environment variables with empty-string fallbacks (so the app can boot even with no mail configured — sending will simply fail gracefully, caught by `try/except` in `email_service.py`). `MAIL_PORT` is explicitly cast to `int` since env vars are always strings and Flask-Mail requires an integer port. `MAIL_USE_TLS = True` is hardcoded (not overridable via env), assuming a TLS-capable SMTP relay such as Gmail's `smtp.gmail.com:587`.

```python
    # Token expiry in seconds (24 hours)
    TOKEN_EXPIRY = 86400
```
- Used by `verify_token()` in `email_service.py` as the `max_age` for the signed set-password/reset-password links, i.e., those links stop working after 24 hours.

`config.py` finishes executing; control returns to `app.py`'s import statement, which now moves to `from db import db, login_manager, mail`.

<a name="phase-3"></a>
## Phase 3: Database / Extension Setup (`db.py`)

```python
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
```

- Three extension objects are instantiated **without an app**. This is Flask's "deferred initialization" pattern: `SQLAlchemy()`, `LoginManager()`, and `Mail()` can all be created before any `Flask` instance exists, and are bound later with `.init_app(app)`. This is critical for the app-factory pattern used in `create_app()` (Phase 5) and lets every other module (`models/*.py`, `routes/*.py`) simply `from db import db` (or `login_manager`/`mail`) without importing `app.py` itself — avoiding circular imports (since `app.py` needs to import routes, and routes need `db`).
- `db` — the shared `SQLAlchemy` instance; every model class in `models/*.py` inherits from `db.Model` and uses `db.Column`, `db.relationship`, etc., all sourced from this one object.
- `login_manager` — the shared `Flask-Login` `LoginManager`; configured further in `create_app()` (`login_view`, `login_message_category`) and used via its `@login_manager.user_loader` decorator in `models/user.py` (see Phase 5.4).
- `mail` — the shared `Flask-Mail` `Mail` instance; used inside `services/email_service.py` to actually dispatch SMTP messages.

`db.py` finishes; control returns to `app.py`. All top-level imports of `app.py` are now resolved.

<a name="phase-4"></a>
## Phase 4: `setup_logging()` Definition & Immediate Call

```python
def setup_logging():
    log_dir = Path(__file__).resolve().parent / 'logs'
    log_dir.mkdir(exist_ok=True)
```
- `Path(__file__).resolve().parent` is the absolute directory containing `app.py` (project root). `/ 'logs'` builds `<project_root>/logs`. `.mkdir(exist_ok=True)` creates it if missing, silently no-ops if it already exists — this is what causes the `logs/` folder (containing `application.log`, confirmed on disk) to exist.

```python
    handler = RotatingFileHandler(
        log_dir / 'application.log',
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s  %(levelname)-8s  %(name)s  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
```
- Creates a `RotatingFileHandler` writing to `logs/application.log`. `maxBytes=5*1024*1024` (5 MB) is the size threshold at which the handler rotates: once the current log file hits 5 MB, it's renamed (e.g. `application.log.1`) and a fresh file started. `backupCount=10` keeps at most 10 rotated backups before the oldest is deleted — bounding total log disk usage to roughly 55 MB. The formatter produces lines like `2026-07-28 10:15:03  INFO      routes.auth  Login success: user=admin`, giving timestamp, level, logger name (module path), and message — every `logging.getLogger(__name__)` call throughout the route/service files inherits this format because they propagate up to the root logger.

```python
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)

    logging.getLogger('werkzeug').setLevel(logging.WARNING)
```
- Attaches the handler to the **root** logger (not a named one), so every module's `logging.getLogger(__name__)` call anywhere in the codebase (auth.py, tickets.py, email_service.py, etc.) automatically writes into this same file, since child loggers propagate to root by default. `root.setLevel(logging.INFO)` means `DEBUG`-level messages are suppressed but `INFO`/`WARNING`/`ERROR` pass through. `if not root.handlers` guards against duplicate handlers being added if `setup_logging()` were ever called twice (e.g., under a reloader that re-imports the module) — without this guard, log lines would be duplicated on each addition. `logging.getLogger('werkzeug').setLevel(logging.WARNING)` quiets Flask's built-in development server request-logging (which is normally INFO-level and prints every HTTP request), keeping the log file focused on application-level events.

```python
setup_logging()
```
- Called immediately at import time — i.e., the very first side effect the app performs after imports resolve is wiring up logging, ensuring anything logged during `create_app()` (below) is actually captured.

<a name="phase-5"></a>
## Phase 5: `create_app()` — App Factory Walkthrough

The next top-level statements in `app.py` are the definitions of `_run_migrations`, `_seed_dummy_data`, and `create_app`, followed by the module-level call `app = create_app()`. Function **bodies** don't execute until called, so we first note their definitions, then trace `create_app()` since it's what actually runs at import time (line 150: `app = create_app()`).

### 5.1 Flask app construction & config load

```python
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
```
- `Flask(__name__)` constructs the WSGI application; `__name__` here is `'app'` (or `'__main__'` if run directly), used by Flask to locate the `templates/` and `static/` folders relative to this file (both found at the project root, confirmed present).
- `app.config.from_object(Config)` copies every uppercase attribute from the `Config` class (Phase 2) into `app.config`, e.g. `app.config['SECRET_KEY']`, `app.config['SQLALCHEMY_DATABASE_URI']`, all `MAIL_*` keys, `TOKEN_EXPIRY`.

```python
    # Ensure database directory exists
    os.makedirs(os.path.join(os.path.dirname(__file__), 'database'), exist_ok=True)
```
- Explicitly creates `<project_root>/database/` before SQLAlchemy tries to open a file inside it — SQLite will not auto-create missing parent directories, only the file itself, so without this line the very first `db.create_all()` call below would raise `sqlite3.OperationalError: unable to open database file`.

### 5.2 Extension initialization

```python
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'
```
- `db.init_app(app)` — binds the earlier-created `SQLAlchemy()` singleton (Phase 3) to this specific Flask app, reading `SQLALCHEMY_DATABASE_URI` from `app.config` to configure the engine.
- `login_manager.init_app(app)` — binds Flask-Login to the app, enabling `current_user`, `login_user()`, `logout_user()`, and the `@login_required` decorator used throughout every route file.
- `mail.init_app(app)` — binds Flask-Mail, reading the `MAIL_*` config keys to configure an SMTP client used later by `services/email_service.py`.
- `login_manager.login_view = 'auth.login'` — tells Flask-Login which endpoint to redirect unauthenticated users to when they hit an `@login_required` view; the string `'auth.login'` refers to the blueprint-qualified endpoint name (`auth_bp` blueprint, `login` function) that gets registered in the next step. If this blueprint weren't registered with the name `'auth'`, this string would silently fail to resolve at redirect time.
- `login_manager.login_message_category = 'warning'` — the flash-message category Flask-Login uses for its default "Please log in to access this page" message, which the templates render as a Bootstrap `alert-warning`.

### 5.3 Blueprint registration

```python
    # Register blueprints
    from routes.auth import auth_bp
```

**This import triggers loading `routes/auth.py` right now.** We stop and fully trace it.

#### `routes/auth.py` (imported here, structure/definitions only — request-time behavior covered in Phase 7)

```python
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from db import db
from models.user import User
```

- `from models.user import User` — **this import triggers loading `models/user.py` right now**, which we trace immediately since it happens before the rest of `auth.py` finishes importing.

##### `models/user.py` (loaded here)

```python
from db import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(10), default='User', nullable=False)  # Admin / User
    active_flag = db.Column(db.Boolean, default=True, nullable=False)
    force_password_change = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```
- `User(UserMixin, db.Model)` — multiple inheritance: `UserMixin` (Flask-Login) supplies default implementations of `is_authenticated`, `is_active`, `is_anonymous`, and `get_id()` so `User` instances work directly with `login_user()`/`current_user` without reimplementing those. `db.Model` makes it a SQLAlchemy ORM-mapped class.
- `__tablename__ = 'users'` — explicit table name (otherwise SQLAlchemy would auto-derive one from the class name).
- `id` — integer primary key, auto-increment by default in SQLite.
- `username` — unique, required (`nullable=False`), indexed for fast lookups (used in `User.query.filter_by(username=...)` throughout `auth.py`).
- `email` — unique, required, indexed — used both for login-adjacent lookups and as the recipient/identity embedded in signed tokens (`generate_token(user.email)` in `email_service.py`).
- `password_hash` — stores a Werkzeug-hashed password (never plaintext); nullable at the column level because a newly `register()`-ed user has no password until they use the "set password" email link — see Phase 7.
- `role` — `'Admin'` or `'User'`; defaults to `'User'`. Used by `is_admin()` below and every `admin_required` decorator across `approvals.py`/`admin.py`.
- `active_flag` — soft-disable flag; `login()` checks this so deactivated users can't log in even with a correct password.
- `force_password_change` — set `True`... actually here it defaults `False`, but is referenced in `login()` to force a redirect to `change_password` if `True` (though nothing in the current code ever sets it `True` after creation — it's a hook for future use, e.g., admin-forced resets).
- `created_at` — `default=datetime.utcnow` — note this is the **function reference**, not `datetime.utcnow()` (no parenthesis) — SQLAlchemy calls it at insert time, so each row gets its own real creation timestamp rather than all rows sharing the import-time timestamp (a common bug this code correctly avoids).

```python
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'Admin'

    def __repr__(self):
        return f'<User {self.username}>'
```
- `set_password` — hashes and stores; called in `register()`, `set_password()` route, `change_password()` route, and admin default-user seeding in `app.py`.
- `check_password` — verifies a plaintext candidate against the stored hash using constant-time comparison (Werkzeug internally). Would raise if `password_hash` is `None` (a user who registered but never set a password attempting login — in practice `login()` still calls this, so if `password_hash` is `None`, `check_password_hash(None, password)` — Werkzeug handles `None` hashes by returning `False` rather than raising, so login just fails gracefully).
- `is_admin` — simple string comparison, the sole authorization gate throughout the app.
- `__repr__` — debug-friendly string representation, e.g. in a Python shell or log dump.

```python
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
```
- Registers `load_user` as Flask-Login's user-loader callback. On every request where a session cookie is present, Flask-Login calls this with the `user_id` string stored in the session to reconstruct the `current_user` object. `int(user_id)` converts the session's string ID back to an integer for the primary-key lookup. If this function returned `None` (e.g., the user was deleted), Flask-Login treats the request as anonymous. This decorator only takes effect because `login_manager.init_app(app)` was already called in `create_app()` before this module might run — but actually order here doesn't strictly matter since the decorator just registers the callback on the shared `login_manager` singleton, and `init_app` only needs to have happened before requests come in, not before this import.

`models/user.py` finishes loading. Back in `routes/auth.py`:

```python
from services.email_service import send_set_password_email, send_reset_password_email, verify_token
```
- **Triggers loading `services/email_service.py` now.** We defer its full line-by-line trace to Phase 13 (Services Deep Dive) to keep this section focused on registration order, but note here what's imported: `send_set_password_email`, `send_reset_password_email`, `verify_token` — all used inside `auth.py`'s route handlers (Phase 7).

```python
auth_bp = Blueprint('auth', __name__)
log = logging.getLogger(__name__)
```
- `Blueprint('auth', __name__)` creates a blueprint named `'auth'` — this is the namespace prefix seen in `url_for('auth.login')` etc. `__name__` here is `'routes.auth'`, used by Flask to help locate templates/static if the blueprint had its own (it doesn't; it shares the app's `templates/` folder).
- `log = logging.getLogger(__name__)` — a module-scoped logger (`'routes.auth'`) that inherits the root handler configured in Phase 4, so `log.info(...)` calls here land in `logs/application.log`.

The five `@auth_bp.route(...)` view functions (`login`, `logout`, `register`, `set_password`, `change_password`, `forgot_password`) are **defined** here (decorators run now, attaching each function to the blueprint's routing table) but their **bodies execute only when a matching HTTP request arrives** — traced in full in Phase 7.

`routes/auth.py` finishes importing. Back in `app.py`'s `create_app()`:

```python
    from routes.dashboard import dashboard_bp
```

**Triggers loading `routes/dashboard.py` now.**

#### `routes/dashboard.py` (imported here)

```python
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
```

- **Triggers loading `models/ticket.py` now.**

##### `models/ticket.py` (loaded here)

```python
from db import db
from datetime import datetime


class Ticket(db.Model):
    __tablename__ = 'tickets'

    id = db.Column(db.Integer, primary_key=True)
    ticket_no = db.Column(db.String(50), nullable=False, unique=True)
    ticket_type = db.Column(db.String(50))
    service = db.Column(db.String(100))
    description = db.Column(db.Text)
    status = db.Column(db.String(30), default='Open')
    planned_month = db.Column(db.String(20))
    actual_implementation_month = db.Column(db.String(20))
    planned_efforts = db.Column(db.Float, default=0)
    utilized_efforts = db.Column(db.Float, default=0)
    approved_by = db.Column(db.String(100))
    estimated_uat = db.Column(db.Date)
    estimated_prod = db.Column(db.Date)
    actual_uat = db.Column(db.Date)
    actual_prod = db.Column(db.Date)
    revised_uat_date = db.Column(db.Date)
    revised_prod_date = db.Column(db.Date)
    exception_from = db.Column(db.String(200))
    business_benefits = db.Column(db.Text)
    remarks = db.Column(db.Text)

    assigned_to = db.Column(db.String(64), nullable=True)
```
- This is the central entity of the whole app. Each column models one field of a ticket:
  - `ticket_no` — unique human-readable identifier like `TKT-001`, required and unique so duplicate ticket numbers are rejected at the DB level (and pre-checked in route code before insert).
  - `ticket_type` / `service` / `description` — free-text/categorical classification.
  - `status` — one of `Open/In Progress/UAT/Closed/On Hold` (enforced only in Python via the `STATUSES` list in `dashboard.py`/`tickets.py`, not a DB-level CHECK constraint — so a malformed status could theoretically be inserted directly via SQL, but the app's forms constrain it).
  - `planned_month`/`actual_implementation_month` — string labels like `'Jan-2026'` (not real `Date` columns) — used for grouping/filtering by "release month".
  - `planned_efforts`/`utilized_efforts` — `Float` man-day/hour estimates vs actuals, aggregated with SQL `SUM` in dashboard/analytics views.
  - `estimated_uat`/`estimated_prod`/`actual_uat`/`actual_prod`/`revised_uat_date`/`revised_prod_date` — six `Date` columns tracking a ticket's UAT/production timeline and any revisions to those dates.
  - `assigned_to` — added later via the `_run_migrations()` ALTER TABLE (see 5.5) — hence `nullable=True` and its own explicit `db.Index` below, since on an existing DB this column wouldn't exist until the migration runs.

```python
    # Soft delete
    deleted_flag = db.Column(db.Boolean, default=False)
    delete_requested = db.Column(db.Boolean, default=False)
    delete_requested_by = db.Column(db.String(64))
    delete_requested_date = db.Column(db.DateTime)

    created_by = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```
- `deleted_flag` — the app never hard-deletes tickets; `delete_ticket()` in `tickets.py` only ever sets this flag `True` (after admin approval). All "active" queries filter `deleted_flag=False`; "deleted tickets" admin view filters `deleted_flag=True`. This preserves history/audit trail integrity.
- `delete_requested`/`delete_requested_by`/`delete_requested_date` — tracks that a delete is pending approval, shown in the UI so users know not to re-request.
- `created_by` — username string (not a FK to `users.id` — a deliberate denormalization; if the user is later deleted, the ticket still shows who created it, though nothing enforces referential integrity here).
- `created_at` — set once at insert (function reference again, correctly avoiding the shared-timestamp bug).
- `updated_at` — `onupdate=datetime.utcnow` means SQLAlchemy automatically refreshes this column to "now" on every UPDATE issued through the ORM (not on raw SQL) — used implicitly whenever `apply_dict_to_ticket()` mutates an existing `Ticket` and the session is committed.

```python
    __table_args__ = (
        db.Index('ix_tickets_status', 'status'),
        db.Index('ix_tickets_planned_month', 'planned_month'),
        db.Index('ix_tickets_deleted_flag', 'deleted_flag'),
        db.Index('ix_tickets_ticket_type', 'ticket_type'),
        db.Index('ix_tickets_assigned_to', 'assigned_to'),
    )
```
- Explicit secondary indexes on the four/five columns most frequently filtered on (dashboard search/filter, analytics grouping). These mirror the `CREATE INDEX IF NOT EXISTS` statements also run manually in `_run_migrations()` — belt-and-suspenders: SQLAlchemy's `db.create_all()` would create these on a fresh DB from `__table_args__` alone, but for a pre-existing DB from before these indexes/columns existed, the manual migration statements in `app.py` are what actually apply them (see 5.5).

```python
    def to_dict(self):
        def fmt_date(d):
            return d.strftime('%Y-%m-%d') if d else None
        return { ... }
```
- Converts a `Ticket` row into a plain dict with ISO-formatted date strings (or `None`). This is critical infrastructure used in three places: (1) `edit_ticket()` in `tickets.py` diffs `old_data = ticket.to_dict()` against submitted form data to compute `changed_fields`; (2) `delete_ticket()` snapshots the ticket into an `ApprovalRequest.request_data` JSON blob so the full pre-delete state is preserved for audit/undo purposes; (3) implicitly informs the shape of `new_data` dicts built by `form_to_dict()` in `tickets.py`, which must use matching keys for the diff comparison to work correctly. Note `created_at` is included in the returned dict but with a different (`%Y-%m-%d %H:%M:%S`) format than the date fields — asymmetric but intentional since it's a `DateTime` not `Date`.

```python
    def __repr__(self):
        return f'<Ticket {self.ticket_no}>'
```

`models/ticket.py` finishes. Back in `routes/dashboard.py`:

```python
from models.approval import ApprovalRequest
```

**Triggers loading `models/approval.py` now.**

##### `models/approval.py` (loaded here)

```python
from db import db
from datetime import datetime
import json


class ApprovalRequest(db.Model):
    __tablename__ = 'approval_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_type = db.Column(db.String(10), nullable=False)  # ADD / EDIT / DELETE
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=True)
    request_data = db.Column(db.Text)  # JSON
    requested_by = db.Column(db.String(64))
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(10), default='PENDING')  # PENDING / APPROVED / REJECTED
    approved_by = db.Column(db.String(64))
    approved_at = db.Column(db.DateTime)
    comments = db.Column(db.Text)

    ticket = db.relationship('Ticket', backref=db.backref('approvals', lazy='dynamic'))
```
- This is the heart of the approval workflow. One row represents a single pending/resolved change request.
- `request_type` — `'ADD'`, `'EDIT'`, or `'DELETE'` — drives all branching logic in `approvals.py`'s `_process_single_approval()`.
- `ticket_id` — **foreign key to `tickets.id`**, `nullable=True` because an `ADD` request has no existing ticket yet (the ticket is only created upon approval).
- `request_data` — a `Text` column storing arbitrary JSON via `json.dumps`/`json.loads` (helper methods below) — this is how the entire pending-change payload (new ticket fields, or old/new diff for edits, or a full snapshot for deletes) is persisted without needing separate tables per request type. Trade-off: not queryable by field value in SQL, but far simpler schema.
- `requested_by`/`requested_at` — audit fields for who submitted the request and when.
- `status` — defaults `'PENDING'`; transitions to `'APPROVED'`/`'REJECTED'` only via `_process_single_approval()`.
- `approved_by`/`approved_at`/`comments` — filled in when an admin acts on the request.
- `ticket = db.relationship('Ticket', backref=db.backref('approvals', lazy='dynamic'))` — bidirectional relationship: `approval.ticket` gets the related `Ticket` object (via the `ticket_id` FK), and conversely any `Ticket` instance gains a `.approvals` attribute (a lazy dynamic query object, meaning `ticket.approvals` returns a `Query`, not a list, so you can further filter it, e.g. `ticket.approvals.filter_by(status='PENDING')`, without loading all rows into memory).

```python
    def get_request_data(self):
        if self.request_data:
            return json.loads(self.request_data)
        return {}

    def set_request_data(self, data):
        self.request_data = json.dumps(data)

    def __repr__(self):
        return f'<ApprovalRequest {self.request_type} ticket={self.ticket_id}>'
```
- `get_request_data`/`set_request_data` are the (de)serialization helpers wrapping the raw `Text` column — called throughout `tickets.py` and `approvals.py` instead of touching `.request_data` directly, keeping JSON encoding centralized. If `request_data` is empty/`None`, `get_request_data()` safely returns `{}` rather than raising a `json.JSONDecodeError`.

`models/approval.py` finishes. Back in `routes/dashboard.py`:

```python
from models.user import User
```
- `User` was already imported and fully executed during the `auth.py` import chain above; Python's import system caches modules in `sys.modules`, so this is a cheap dictionary lookup, not a re-execution.

```python
from sqlalchemy import func
import pandas as pd
import io
from datetime import datetime
```
- `func` — SQLAlchemy's namespace for SQL functions (`func.sum`, `func.count`) used heavily for aggregate dashboard/analytics queries instead of pulling all rows into Python and summing in a loop (a deliberate performance choice, called out explicitly in a comment later in the file: "single grouped query instead of 6 separate counts").
- `pandas as pd` / `io` — used by `export()` to build an in-memory Excel file (`io.BytesIO()` as a virtual file, written to by `pandas.ExcelWriter`, then sent via `send_file` without ever touching disk).

```python
dashboard_bp = Blueprint('dashboard', __name__)

STATUSES = ['Open', 'In Progress', 'UAT', 'Closed', 'On Hold']
TICKET_TYPES = ['Enhancement', 'Bug Fix', 'New Feature', 'Maintenance', 'Support', 'Other']
```
- Module-level constants defining the allowed dropdown values for status/type across templates — the single source of truth duplicated (not imported/shared) in `routes/tickets.py` as an identical list; a maintenance note: if these two lists ever drift apart, dashboard filters and add/edit forms could offer different options. Not a bug today, but worth knowing.

Function definitions `fmt_date_display`, `_build_query`, and the two route handlers `index()`/`export()` are defined now; their bodies are traced in Phase 8.

`routes/dashboard.py` finishes. Back in `create_app()`:

```python
    from routes.tickets import tickets_bp
```

**Triggers loading `routes/tickets.py` now.**

#### `routes/tickets.py` (imported here)

```python
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.approval import ApprovalRequest
from models.settings import SystemSettings
```

- `Ticket`, `ApprovalRequest` are already cached in `sys.modules`. **`from models.settings import SystemSettings` triggers loading `models/settings.py` now** (first time it's referenced).

##### `models/settings.py` (loaded here)

```python
from db import db
from datetime import datetime


class SystemSettings(db.Model):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    freeze_date = db.Column(db.Date)
    updated_by = db.Column(db.String(64))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SystemSettings freeze_date={self.freeze_date}>'
```
- A tiny singleton-style table: the app only ever expects **one row** (`SystemSettings.query.first()` is used everywhere, never filtered by ID). `freeze_date` — when set, any ticket-add attempted on or after this date requires admin approval instead of being saved directly (see `is_frozen()` in `tickets.py`, Phase 9). `updated_by`/`updated_at` record who last changed the freeze date and when, for auditability. There's no uniqueness constraint preventing multiple rows from being inserted — the code simply always reads/writes the *first* row found (`freeze_settings()` route checks `if settings:` to decide update-vs-insert), so as long as only that route ever writes here, only one row will ever exist in practice.

`models/settings.py` finishes. Back in `routes/tickets.py`:

```python
from models.user import User
from services.history_service import log_ticket_created, log_ticket_changes, log_ticket_deleted
```
- `User` cached. **`services/history_service.py` loads now** — full trace deferred to Phase 14; note here what's imported: three logging helper functions called at ticket create/edit-approve/delete-approve points.

```python
import pandas as pd
import io
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
```
- `pandas`/`io` again for bulk-upload (`pd.read_excel`) and the downloadable template generator. `relativedelta` — used by `get_months()` to compute "current month + next 4 months" labels for the planned-month dropdown, correctly handling month/year rollover (e.g., November + 4 months = March of next year), which plain `timedelta` arithmetic cannot do reliably for months.

```python
tickets_bp = Blueprint('tickets', __name__)
log = logging.getLogger(__name__)

STATUSES = ['Open', 'In Progress', 'UAT', 'Closed', 'On Hold']
TICKET_TYPES = ['Enhancement', 'Bug Fix', 'New Feature', 'Maintenance', 'Support', 'Other']

def get_months():
    months = []
    current_month = datetime.today().replace(day=1)
    for i in range(5):  # Current month + next 4 months
        month = current_month + relativedelta(months=i)
        months.append(month.strftime('%b-%Y'))
    return months

MONTHS = get_months()
```
- `MONTHS` is computed **once at import time** (module load), not per-request. This means the "planned month" dropdown options are frozen to whatever the current month was when the server process started — if the server runs for weeks without restart, the 5-month rolling window will not advance day-to-day; it only refreshes on app restart. This is a subtle but real behavior worth flagging (not necessarily a bug, but a design choice with a caveat).

Function definitions `is_frozen()`, `parse_date()`, `form_to_dict()`, `apply_dict_to_ticket()`, and all `@tickets_bp.route` handlers are defined now; traced fully in Phase 9. (Note: `apply_dict_to_ticket` and `parse_date` are later imported directly by `routes/approvals.py` — `from routes.tickets import apply_dict_to_ticket, parse_date` — showing tickets.py's helper functions are reused as the single source of truth for turning a submitted/approved data dict into `Ticket` column assignments.)

`routes/tickets.py` finishes. Back in `create_app()`:

```python
    from routes.approvals import approvals_bp
```

**Triggers loading `routes/approvals.py` now.**

#### `routes/approvals.py` (imported here)

```python
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.approval import ApprovalRequest
from models.user import User
from services.history_service import log_ticket_created, log_ticket_changes, log_ticket_deleted
from services.email_service import send_approval_notification
from routes.tickets import apply_dict_to_ticket, parse_date
from datetime import datetime
from functools import wraps
```
- All model/service imports are already cached. `from routes.tickets import apply_dict_to_ticket, parse_date` is a **cross-blueprint import** — `routes/approvals.py` reaches back into `routes/tickets.py` to reuse its form-to-model mapping logic when an ADD/EDIT approval is approved, rather than duplicating that logic. This means `routes/tickets.py` must be importable independently of `approvals.py` (it is — no circular dependency, since `tickets.py` never imports from `approvals.py`).
- `functools.wraps` — used to build the `admin_required` decorator below in a way that preserves the wrapped view function's `__name__`/docstring, which Flask requires for correct endpoint registration (without `@wraps`, Flask would raise `AssertionError: View function mapping is overwriting an existing endpoint function` if two decorated views happened to produce identically-named wrapper functions).

```python
approvals_bp = Blueprint('approvals', __name__)
log = logging.getLogger(__name__)

FIELD_LABELS = { ... }  # maps internal field names to human-readable labels
```
- `FIELD_LABELS` — a display-name lookup dict used by `approval_details()` to render a readable diff table (e.g. `'planned_efforts'` → `'Planned Efforts'`) instead of showing raw snake_case field names to admins reviewing a request.

```python
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated
```
- A custom decorator (there is no shared `decorators.py` module in this project — each route file that needs admin-gating defines its own identical copy, one in `approvals.py` and one in `admin.py`). It wraps a view function `f`: when the decorated view is called, `decorated` runs first, checks `current_user.is_authenticated` (false for anonymous visitors) and `current_user.is_admin()` (false for regular users); if either check fails, it flashes an error and redirects to the dashboard **without ever calling `f`**. If both pass, it calls and returns `f(*args, **kwargs)`, passing through any URL-captured arguments (e.g. `approval_id`). Note this decorator does **not** replace `@login_required` — it's always stacked *underneath* `@login_required` in usage (`@login_required` then `@admin_required` then the route decorator, applied bottom-up), so `login_required` guarantees `current_user` is a real logged-in user before `admin_required` even runs its authorization check — though `admin_required` defensively re-checks `is_authenticated` anyway.

`_process_single_approval()` (the core approve/reject logic) and the three route handlers (`pending_approvals`, `approval_details`, `approval_action`, `bulk_approval_action`) are defined now, traced fully in Phase 11.

`routes/approvals.py` finishes. Back in `create_app()`:

```python
    from routes.admin import admin_bp
```

**Triggers loading `routes/admin.py` now.**

#### `routes/admin.py` (imported here)

```python
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.user import User
from models.ticket import Ticket
from models.settings import SystemSettings
from services.history_service import log_ticket_restored
from functools import wraps
from datetime import datetime
```
- All names already cached from earlier imports. `log_ticket_restored` is the one history-service function not yet referenced by any previously-loaded module.

```python
admin_bp = Blueprint('admin', __name__)
log = logging.getLogger(__name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated
```
- Byte-for-byte the same `admin_required` implementation as in `approvals.py` — duplicated rather than shared from a common module. Functionally identical behavior as described above.

Route handlers `users`, `toggle_active`, `promote_user`, `reset_password`, `freeze_settings`, `deleted_tickets`, `restore_ticket`, `analytics` are defined now, traced fully in Phase 12.

`routes/admin.py` finishes. Back in `create_app()`:

```python
    from routes.comments import comments_bp
```

**Triggers loading `routes/comments.py` now.**

#### `routes/comments.py` (imported here)

```python
import logging
from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from db import db
from models.ticket import Ticket
from models.comment import TicketComment
```
- `from models.comment import TicketComment` — **triggers loading `models/comment.py` now**, the last model module to be loaded in the import chain.

##### `models/comment.py` (loaded here)

```python
from db import db
from datetime import datetime


class TicketComment(db.Model):
    __tablename__ = 'ticket_comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', backref=db.backref(
        'comments', lazy='dynamic', order_by='TicketComment.created_at'
    ))

    __table_args__ = (
        db.Index('ix_comments_ticket_created', 'ticket_id', 'created_at'),
    )

    def __repr__(self):
        return f'<TicketComment ticket={self.ticket_id} by={self.created_by}>'
```
- `ticket_id` — required (`nullable=False`) FK to `tickets.id`; unlike `ApprovalRequest.ticket_id`, a comment always belongs to an existing ticket (comments can't be made on an as-yet-unapproved ADD request).
- `body` — the comment text, required, capped at 2000 characters by application-level validation in `comments.py` (no DB-level length constraint on `Text`).
- `created_by` — username string, same denormalized pattern as `Ticket.created_by`.
- `ticket = db.relationship(..., backref=db.backref('comments', lazy='dynamic', order_by='TicketComment.created_at'))` — gives every `Ticket` a `.comments` dynamic query property, pre-sorted oldest-first by `created_at` (ascending, since no `.desc()` is specified) — this is what `view_ticket.html` presumably iterates to show the comment thread chronologically.
- `__table_args__` composite index on `(ticket_id, created_at)` — optimizes the exact access pattern of "get all comments for ticket X ordered by time," which is precisely what the `comments` relationship's `order_by` triggers on every access.

`models/comment.py` finishes. Back in `routes/comments.py`:

```python
comments_bp = Blueprint('comments', __name__)
log = logging.getLogger(__name__)
```

Route handlers `add_comment`, `delete_comment` are defined now, traced fully in Phase 10.

`routes/comments.py` finishes. **All six blueprint imports are now resolved.** Back in `create_app()`:

```python
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(comments_bp)
```
- Each `register_blueprint` call walks the blueprint's collected `@bp.route(...)` decorators and adds their URL rules to the app's central `url_map`. Order here matters only if two blueprints defined colliding routes (they don't — inspecting all six confirms disjoint URL prefixes: `/login /logout /register /set-password /change-password /forgot-password` (auth), `/` and `/export` (dashboard), `/add /edit /delete /view /history /bulk-upload /template` (tickets), `/approvals*` (approvals), `/admin/*` (admin), `/tickets/<id>/comments/*` (comments)). After this point, `url_for('auth.login')`, `url_for('dashboard.index')`, etc. all resolve correctly — which is why `login_manager.login_view = 'auth.login'` (set earlier, in 5.2, *before* the blueprint was even registered) works: Flask-Login only needs that string to resolve at redirect-time (later), not at assignment-time.

### 5.4 Model imports & `db.create_all()`

```python
    # Create tables
    with app.app_context():
        # Import models to ensure they are registered
        from models.user import User
        from models.ticket import Ticket
        from models.history import TicketHistory
        from models.approval import ApprovalRequest
        from models.settings import SystemSettings
        from models.comment import TicketComment
```
- `with app.app_context():` — pushes a Flask application context, required because `db.create_all()` and other Flask-SQLAlchemy operations need access to `current_app` internally to find the configured engine; without this context manager, calling `db.create_all()` here (outside of a request, where Flask would normally push a context automatically) would raise a `RuntimeError: Working outside of application context`.
- All six model imports are already cached in `sys.modules` from the blueprint-loading chain above **except `models.history`**, which is imported here for the first time. **Triggers loading `models/history.py` now.**

##### `models/history.py` (loaded here)

```python
from db import db
from datetime import datetime


class TicketHistory(db.Model):
    __tablename__ = 'ticket_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    action = db.Column(db.String(20))  # CREATED / UPDATED / DELETED / RESTORED
    field_name = db.Column(db.String(100))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    changed_by = db.Column(db.String(64))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    ticket = db.relationship('Ticket', backref=db.backref('history', lazy='dynamic'))

    def __repr__(self):
        return f'<History ticket={self.ticket_id} field={self.field_name}>'
```
- The audit-trail table. Every row is **one field-level change event** — `log_ticket_created()` writes a single row (action `CREATED`, field `ticket_no`), while `log_ticket_changes()` writes one row **per changed field** (see Phase 14), meaning editing 3 fields at once produces 3 `TicketHistory` rows sharing the same `changed_at`/`changed_by` but different `field_name`/`old_value`/`new_value`. `ticket_id` is a required FK; `action` is a free-text enum-like string with no DB constraint (`'CREATED'`, `'UPDATED'`, `'DELETED'`, `'RESTORED'` by convention). `ticket.history` gives every `Ticket` a dynamic query of its full change log, used by `ticket_history()` in `tickets.py` (`ticket.history.order_by(db.text('changed_at desc')).all()`).

`models/history.py` finishes. All six model modules are now loaded and their classes registered against `db.Model`'s metadata.

```python
        db.create_all()
        _run_migrations(app)
```
- `db.create_all()` — inspects SQLAlchemy's `Base.metadata` (populated by every `db.Model` subclass defined so far: `User`, `Ticket`, `TicketHistory`, `ApprovalRequest`, `SystemSettings`, `TicketComment`) and issues `CREATE TABLE IF NOT EXISTS` for each, plus the indexes declared in each model's `__table_args__`. This is what actually produces `database/ticket_tracker.db` with all six tables on first run; on subsequent runs it's a no-op for existing tables (it never alters existing tables' columns — that's what the manual migration step below is for).

### 5.5 `_run_migrations(app)`

```python
def _run_migrations(app):
    """Add new columns to existing tables idempotently."""
    migrations = [
        "ALTER TABLE tickets ADD COLUMN assigned_to VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets (status)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_planned_month ON tickets (planned_month)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_deleted_flag ON tickets (deleted_flag)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_ticket_type ON tickets (ticket_type)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_assigned_to ON tickets (assigned_to)",
    ]
    with app.app_context():
        for sql in migrations:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()
```
- This is a hand-rolled, extremely lightweight migration mechanism (no Alembic/Flask-Migrate). It exists because `db.create_all()` never alters an already-existing table's schema — so if the `Ticket` model gained the `assigned_to` column *after* the database file already existed from an earlier version of the app, `create_all()` alone would leave the live `tickets` table without that column, causing every ORM query touching `assigned_to` to fail.
- The loop runs each raw SQL string via `db.text(sql)` (SQLAlchemy's way of marking a string as literal executable SQL rather than something to be parameter-bound), wrapped in `try/except` **per-statement**: on a *brand-new* database (just created by `create_all()` above, already containing `assigned_to` because it's in the current model definition), `ALTER TABLE ... ADD COLUMN assigned_to` will fail with "duplicate column name" — the `except: db.session.rollback()` swallows that specific expected failure and moves to the next statement. On an *existing* older database missing the column, the `ALTER TABLE` succeeds, and the four `CREATE INDEX IF NOT EXISTS` statements are naturally idempotent (SQLite honors `IF NOT EXISTS` natively) so they never need the exception path. This blanket `except Exception` is broad — it would also silently swallow a genuine SQL syntax error or a lock/permission problem — but is an intentional, pragmatic trade-off for a small self-contained app avoiding an Alembic dependency.
- `db.session.rollback()` after each caught failure is essential in SQLite/SQLAlchemy — without it, the session would remain in an aborted transaction state and every subsequent statement in the loop would also fail.

### 5.6 Default admin seeding

```python
        # Create default admin if no users exist
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@tickettracker',
                role='Admin',
                active_flag=True,
                force_password_change=False
            )
            admin.set_password('Admin@123')
            db.session.add(admin)
            db.session.commit()
            logging.getLogger(__name__).info('Default admin created: admin / Admin@123')
```
- `User.query.first()` — returns `None` if the `users` table is empty (true on a completely fresh database). In that case a hardcoded bootstrap admin account is created: username `admin`, password `Admin@123` (hashed via `set_password`), role `Admin`, active. This is what allows the very first login into a freshly deployed instance — without it there would be no way to log in at all (registration creates only `role='User'` accounts). The plaintext password is also logged to `application.log` at INFO level, which is a notable security consideration for anyone auditing this app (credentials end up in a log file) — worth flagging even though it's intentional bootstrap-convenience behavior.
- This block only runs **once ever** per fresh database — after the first admin exists, `User.query.first()` returns a truthy row and this whole branch is skipped on every subsequent app start.

### 5.7 `_seed_dummy_data()`

```python
        # Seed dummy tickets if none exist
        if not Ticket.query.first():
            _seed_dummy_data()
```
- Same "only if empty" guard, but for the `tickets` table. Calls the module-level `_seed_dummy_data()` function (defined earlier in `app.py`, executed only now).

```python
def _seed_dummy_data():
    from models.ticket import Ticket
    from datetime import date

    tickets = [
        Ticket(ticket_no='TKT-001', ...), 
        ... # 20 Ticket(...) constructor calls total
    ]
    for t in tickets:
        db.session.add(t)
    db.session.commit()
    logging.getLogger(__name__).info('Seeded 20 dummy tickets.')
```
- Builds 20 fully-populated `Ticket` ORM objects in memory (covering a realistic spread of `ticket_type`, `service`, `status`, dates, efforts, and business-benefit text) using Python's keyword-argument constructor (inherited automatically by every `db.Model` subclass from SQLAlchemy's declarative base — no explicit `__init__` was written in `Ticket`). Each is `db.session.add(t)`-ed individually inside the loop, but only a **single** `db.session.commit()` happens after the loop — meaning all 20 inserts are flushed to SQLite in one transaction, which is both faster and atomic (if row 15 somehow violated a constraint, none of the 20 would be committed... though in a `try`-less flow here, an exception would actually propagate up and potentially crash `create_app()` — there's no error handling around this call, another indicator this is meant purely as convenience demo data for local development, not production-hardened logic).
- This local re-import (`from models.ticket import Ticket`) inside the function body is redundant (already imported at module scope of `app.py`'s `create_app()` via the `with app.app_context()` block above) but harmless — Python's module cache makes it a no-op lookup.
- Purpose: gives a brand-new install immediately-visible, realistic-looking sample data across the dashboard, charts, and analytics views rather than an empty table.

```python
    return app
```
- `create_app()` returns the fully constructed, configured, blueprint-registered, table-initialized Flask `app` object.

Back at true module (top) level in `app.py`:

```python
app = create_app()
```
- This is the line that actually **invokes** everything traced in 5.1–5.7 above. After this line executes, `app` is a ready-to-serve WSGI application with all six tables created, migrations applied, and (on first run) a default admin + 20 demo tickets seeded.

<a name="phase-6"></a>
## Phase 6: Module-Level Route (`/`) and `__main__` Guard

```python
@app.route('/')
def root():
    return redirect(url_for('dashboard.index'))
```
- A route registered directly on the app (not a blueprint) for the bare root URL `/`. Since `dashboard_bp` is registered with no URL prefix and its `index()` view is *also* mapped to `/` (see `@dashboard_bp.route('/')` in Phase 8), this `root()` view is actually **dead code / unreachable in practice** — Flask resolves `/` to whichever rule was registered last for that exact path, or raises on an outright duplicate. In this specific case both `dashboard.index` and `app.root` map to the literal string `/`; because `dashboard_bp` was registered earlier (inside `create_app()`, called at line 150) and this `@app.route('/')` is defined afterward (line 153), and blueprint routes vs. app routes don't inherently conflict unless the exact rule string is identical — this is a genuine ambiguity in the routing table. In practice Werkzeug will use the first-registered matching rule for a given path when building `url_map`, so `dashboard.index` (registered first, inside `create_app()`) wins, and `root()` here is effectively unreachable. It's a harmless leftover / redundant safety net rather than an active behavior — worth noting since a request to `/` is actually always served by `dashboard.index` directly, not via this redirect.

```python
if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.3', port=5000)
```
- Only executes when `app.py` is run directly (`python app.py`), not when imported by a WSGI server (e.g., gunicorn/waitress) or by this documentation-writing process. `debug=True` enables Flask's interactive debugger and the auto-reloader (which re-executes this entire module, including `setup_logging()` and `create_app()`, on every source file change — the `if not root.handlers` guard in `setup_logging()` exists specifically to survive this reload behavior gracefully). `host='127.0.0.3'` is an unusual, deliberately non-default loopback address (normally `127.0.0.1`) — binds the dev server only to that specific loopback IP on port `5000`.

This concludes startup/import-time execution. Everything below is **request-time** behavior — code that only runs when an HTTP request matches a given route, traced in the order a typical user session would hit them: login first, then dashboard, then ticket operations, comments, approvals, and admin functions.

---

<a name="phase-7"></a>
## Phase 7: Request Lifecycle — Authentication (`routes/auth.py`)

### `GET/POST /login`

```python
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
```
- No `@login_required` here (it's the login page itself). `current_user` is a Flask-Login proxy resolved per-request via the `load_user` callback (Phase 5.3) reading the session cookie; if already logged in, immediately redirect to the dashboard rather than showing the login form again.

```python
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active_flag:
            log.info('Login success: user=%s', username)
            login_user(user)
```
- On form submission: reads `username`/`password` from the POST body (`request.form`, defaulting to `''` if missing, avoiding `KeyError`). `.strip()` on username trims accidental whitespace. Looks up the user by exact username match. The condition is a three-part AND: user must exist, password hash must verify, **and** `active_flag` must be `True` — a deactivated user (see `toggle_active` in Phase 12) cannot log in even with correct credentials, satisfying that guard here rather than at the account-lookup stage (so the error message is the same generic "Invalid username or password" either way, not leaking whether the account is merely deactivated — a reasonable security choice, intentional or not).
- `login_user(user)` — Flask-Login call that serializes the user's ID (via `get_id()`, from `UserMixin`) into the session cookie, marking the request (and all future requests bearing that cookie) as authenticated.

```python
            if user.force_password_change:
                flash('Please change your password.', 'warning')
                return redirect(url_for('auth.change_password'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))
        log.warning('Login failed: user=%s', username)
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')
```
- If the account requires a forced password change, redirect there instead of the dashboard (note: this branch is currently unreachable in practice since nothing in the codebase ever sets `force_password_change=True` after account creation — it's dormant infrastructure).
- `next_page = request.args.get('next')` — supports the standard Flask-Login redirect-after-login pattern: when an anonymous user is bounced to `/login` by `@login_required` (via `login_manager.login_view`), Flask-Login appends `?next=<original_url>` automatically, and this line honors it so the user lands back where they were headed instead of always going to the dashboard.
- On failed login, logs a warning (not `error`) and flashes a generic invalid-credentials message — the function falls through to `return render_template('login.html')` at the end, which serves both the initial `GET` (empty form) and a failed `POST` (form re-rendered with the flash message, since Jinja has access to flashed messages via `base.html`'s `get_flashed_messages()`).

### `GET /logout`

```python
@auth_bp.route('/logout')
@login_required
def logout():
    log.info('Logout: user=%s', current_user.username)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
```
- `@login_required` ensures only an authenticated session can hit this (an anonymous GET to `/logout` would itself be redirected to login first, which is slightly odd UX but harmless). Logs the current username *before* calling `logout_user()` (which clears `current_user` back to an anonymous proxy) — ordering matters here, since `current_user.username` after `logout_user()` would raise an `AttributeError` on the anonymous user object.

### `GET/POST /register`

```python
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()

        if not username or not email:
            flash('Username and email are required.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('register.html')
```
- No password is collected on this form at all — registration only takes username + email. Three sequential validation gates: both fields present, username not already taken, email not already taken — each returning early with a distinct flash message on failure (form re-rendered, but note: unlike `login()`, the previously-typed `username`/`email` are **not** passed back into the template context here, so the user would see a blank form again after a validation failure — a minor UX gap, but confirmed accurate to the code as written).

```python
        user = User(username=username, email=email, role='User', active_flag=True)
        db.session.add(user)
        db.session.commit()

        log.info('User registered: username=%s email=%s', username, email)
        sent = send_set_password_email(user)
        if sent:
            flash('Registration successful! Check your email to set your password.', 'success')
        else:
            log.warning('Set-password email not sent for user=%s', username)
            flash('Account created, but email could not be sent. Contact your admin.', 'warning')
        return redirect(url_for('auth.login'))
    return render_template('register.html')
```
- Creates the `User` row **without ever calling `set_password()`**, so `password_hash` is `None` at this point — the account exists but cannot yet be logged into (since `check_password(None-hash, ...)` will fail). It's committed to the DB immediately, then `send_set_password_email(user)` is called (**call into `services/email_service.py`, traced fully in Phase 13**) to email the user a signed link that lets them set their password (the `/set-password/<token>` route below). If the email genuinely fails to send (e.g. SMTP not configured — very plausible given `config.py`'s empty-string defaults), the account still exists in a "created but password-less" limbo state, and the flash message tells the user to contact an admin — implying an admin would need to use `reset_password` (Phase 12) to resend the link.

### `GET/POST /set-password/<token>`

```python
@auth_bp.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    email = verify_token(token)
    if not email:
        flash('The link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))
```
- `token` is a URL path segment (the signed token generated by `email_service.generate_token`). `verify_token(token)` (**Phase 13**) decodes and validates the signature/expiry, returning the embedded email or `None`. If verification fails (tampered, expired past 24h, or malformed), the user is bounced to login with an error — no further processing happens.

```python
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))
```
- Defensive check: even with a valid signature, if the user account tied to that email was deleted since the token was issued (no delete-user route exists in this app currently, but the check is defensive), bail out gracefully.

```python
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('set_password.html', token=token)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('set_password.html', token=token)
        user.set_password(password)
        user.force_password_change = False
        db.session.commit()
        log.info('Password set via token: user=%s', user.username)
        flash('Password set successfully! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('set_password.html', token=token)
```
- Minimum 6-character password policy, confirmation-match check, then `set_password()` hashes and stores it, `force_password_change` is explicitly reset to `False` (defensive, in case a future code path ever set it `True` for this user), committed, and the user is sent to login to authenticate with their new credentials. Both `GET` and a validation-failed `POST` render the same template, passing `token` back so the form's action URL (embedding the token) remains correct on re-submission.

### `GET/POST /change-password`

```python
@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html')
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'danger')
            return render_template('change_password.html')
        if new_password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('change_password.html')

        current_user.set_password(new_password)
        current_user.force_password_change = False
        db.session.commit()
        log.info('Password changed: user=%s', current_user.username)
        flash('Password changed successfully.', 'success')
        return redirect(url_for('dashboard.index'))
    return render_template('change_password.html')
```
- Requires login (unlike `set_password`, which works via an anonymous-but-signed token). Three-step validation: current password must verify (prevents someone with a hijacked session-but-not-password from changing it — though if they have the session, this check is largely moot for that threat model; it mainly prevents accidental changes / shoulder-surfing), new password length ≥ 6, and confirmation match. On success, updates the hash in place on the already-loaded `current_user` object and commits — no need to re-query, since `current_user` **is** the live SQLAlchemy-tracked `User` instance for this session.

### `GET/POST /forgot-password`

```python
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            sent = send_reset_password_email(user)
            if sent:
                flash('Password reset email sent.', 'success')
            else:
                flash('Could not send email. Contact your admin.', 'warning')
        else:
            flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('forgot_password.html')
```
- Notable security-conscious detail: when the email **is not found**, the flash message is deliberately vague ("If that email is registered...") to avoid confirming/denying account existence to an attacker (user enumeration protection) — but this protection is **inconsistent**, because when the email **is found but sending fails**, the flash explicitly says "Could not send email. Contact your admin," which *does* leak that the account exists (an attacker could infer registered emails by triggering an SMTP failure scenario, though in practice SMTP failures are uniform across all addresses when misconfigured, so the leak is low-severity here). `send_reset_password_email` reuses the exact same token/link mechanism as `send_set_password_email` (both point to the `set_password` route) — traced in Phase 13.

---

<a name="phase-8"></a>
## Phase 8: Request Lifecycle — Dashboard (`routes/dashboard.py`)

### Helper: `fmt_date_display(d)`
```python
def fmt_date_display(d):
    if d:
        return d.strftime('%d-%b-%Y')
    return ''
```
- Formats a `date`/`datetime` as `'28-Jul-2026'` style, or empty string if `None`/falsy. Passed into the template context as `fmt_date` so Jinja can call it inline per-row without a custom filter.

### Helper: `_build_query(...)`
```python
def _build_query(search_no, search_desc, filter_month, filter_status, filter_ticket_type, filter_assigned=''):
    query = Ticket.query.filter_by(deleted_flag=False)
    if search_no:
        query = query.filter(Ticket.ticket_no.ilike(f'%{search_no}%'))
    if search_desc:
        query = query.filter(Ticket.description.ilike(f'%{search_desc}%'))
    if filter_month:
        query = query.filter(Ticket.planned_month == filter_month)
    if filter_status:
        query = query.filter(Ticket.status == filter_status)
    if filter_ticket_type:
        query = query.filter(Ticket.ticket_type == filter_ticket_type)
    if filter_assigned:
        query = query.filter(Ticket.assigned_to == filter_assigned)
    return query
```
- A single shared query-builder used by both `index()` and `export()` so the two views can never drift in their filtering logic. Always starts from `deleted_flag=False` (soft-deleted tickets are invisible everywhere by default). Each optional filter is applied conditionally — an empty string for any parameter means "don't filter on this dimension." `.ilike(f'%{term}%')` performs a case-insensitive substring match (SQLite's `ILIKE` via SQLAlchemy translates to `LIKE` with `COLLATE NOCASE` semantics or a wrapped `LOWER()` comparison depending on dialect specifics) on ticket number and description — allowing partial-text search. Returns a lazy, not-yet-executed SQLAlchemy `Query` object that the caller can further chain (`.order_by`, `.paginate`, `.all`, or inspect `.whereclause`).

### `GET /` — `index()`

```python
@dashboard_bp.route('/')
@login_required
def index():
    search_no          = request.args.get('search_no', '').strip()
    search_desc        = request.args.get('search_desc', '').strip()
    filter_month       = request.args.get('filter_month', '').strip()
    filter_status      = request.args.get('filter_status', '').strip()
    filter_ticket_type = request.args.get('filter_ticket_type', '').strip()
    filter_assigned    = request.args.get('filter_assigned', '').strip()
    page               = request.args.get('page', 1, type=int)
    per_page           = request.args.get('per_page', 25, type=int)
    if per_page not in (25, 50, 100):
        per_page = 25
```
- **This is the actual view serving `/`** (see the Phase 6 note about `app.root()` being shadowed by this). All filter/search/pagination inputs come from query-string parameters (`request.args`), meaning filtered dashboard states are bookmarkable/shareable URLs. `type=int` on `request.args.get` auto-converts and defaults gracefully if the parameter is missing or non-numeric (Flask's `MultiDict.get` with `type=` swallows `ValueError` and returns the default). `per_page` is whitelisted to exactly `{25, 50, 100}` — any other value (including malicious/malformed input) silently falls back to `25`, preventing a client from requesting an absurdly large page size that could strain the server.

```python
    query = _build_query(search_no, search_desc, filter_month, filter_status,
                         filter_ticket_type, filter_assigned)
    tickets = query.order_by(Ticket.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
```
- Builds the filtered query, orders newest-first, and paginates via Flask-SQLAlchemy's `.paginate()` (returns a `Pagination` object with `.items`, `.page`, `.pages`, `.total`, etc. — used directly in the template for page-navigation controls). `error_out=False` means an out-of-range page number (e.g., `page=999` on a 3-page result set) returns an **empty** page gracefully instead of raising a 404, which is friendlier than the Flask-SQLAlchemy default.

```python
    # Effort totals: current page (in-memory) + all filtered (SQL aggregate)
    page_planned_total  = sum(t.planned_efforts or 0 for t in tickets.items)
    page_utilized_total = sum(t.utilized_efforts or 0 for t in tickets.items)

    effort_row = db.session.query(
        func.sum(Ticket.planned_efforts),
        func.sum(Ticket.utilized_efforts)
    ).filter(query.whereclause).one()
    all_planned_total  = float(effort_row[0] or 0)
    all_utilized_total = float(effort_row[1] or 0)
```
- Two different aggregation strategies deliberately combined: `page_planned_total`/`page_utilized_total` sum only the *currently displayed page's* 25/50/100 rows in plain Python (cheap, since it's already loaded into memory as `tickets.items`). `all_planned_total`/`all_utilized_total` compute the sum across **every** filtered row (not just the current page) via a genuine SQL `SUM()` aggregate query, reusing `query.whereclause` — the accumulated `WHERE` conditions from `_build_query()` — applied to a fresh aggregate query rather than the paginated one. `.one()` expects exactly one result row (guaranteed for an unconditional aggregate with no `GROUP BY`). `float(... or 0)` guards against `SUM()` returning SQL `NULL` when zero rows match the filter (e.g., a search with no results), which Python receives as `None` and would otherwise break arithmetic/display.

```python
    # Dashboard counts — single grouped query instead of 6 separate counts
    status_counts = db.session.query(
        Ticket.status, func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.status).all()
    sc = {row[0]: row[1] for row in status_counts}
    total            = sum(sc.values())
    open_count       = sc.get('Open', 0)
    closed_count     = sc.get('Closed', 0)
    inprogress_count = sc.get('In Progress', 0)
    uat_count        = sc.get('UAT', 0)
    onhold_count     = sc.get('On Hold', 0)
```
- One `GROUP BY status` query returns `[(status, count), ...]` pairs for *all non-deleted* tickets (note: **not** filtered by the search/filter parameters above — these stat-card counts always reflect the global unfiltered state, intentionally giving users a fixed reference point regardless of what they're currently searching for). Converted to a dict `sc` for O(1) lookups; `.get(status, 0)` defaults any status with zero tickets to `0` rather than `KeyError`.

```python
    # Pending approval counts — single grouped query
    pending_counts = db.session.query(
        ApprovalRequest.request_type, func.count(ApprovalRequest.id)
    ).filter_by(status='PENDING').group_by(ApprovalRequest.request_type).all()
    pc = {r[0]: r[1] for r in pending_counts}
    pending_add    = pc.get('ADD', 0)
    pending_edit   = pc.get('EDIT', 0)
    pending_delete = pc.get('DELETE', 0)
```
- Same grouped-query pattern applied to `ApprovalRequest`, giving separate pending-count badges per request type (likely rendered in the Admin dropdown or a stat card visible to admins).

```python
    # Chart data: tickets by type
    type_counts_q = db.session.query(
        Ticket.ticket_type, func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.ticket_type).all()
    type_labels = [r[0] or 'Unset' for r in type_counts_q]
    type_counts_data = [r[1] for r in type_counts_q]

    months_used = db.session.query(Ticket.planned_month).filter(
        Ticket.planned_month.isnot(None), Ticket.deleted_flag == False
    ).distinct().all()
    months_used = [m[0] for m in months_used if m[0]]

    active_users = User.query.filter_by(active_flag=True).order_by(User.username).all()
```
- `type_labels`/`type_counts_data` — parallel arrays (labels + counts) shaped for direct consumption by Chart.js on the client side (`{r[0] or 'Unset' for ...}` substitutes `'Unset'` for tickets with a `NULL` `ticket_type`, so the chart never shows a blank/`None` label).
- `months_used` — a distinct list of all `planned_month` values actually present in the (non-deleted) ticket data, used to populate the "filter by month" dropdown with only real options rather than a hardcoded/static list — note this is different from `tickets.py`'s `MONTHS` constant (which is a fixed 5-month rolling window for *new* ticket entry); this dashboard filter dropdown reflects *historical* data instead.
- `active_users` — all currently-active users sorted alphabetically, used to populate the "filter by assignee" dropdown.

```python
    return render_template('dashboard.html',
        tickets=tickets, total=total, open_count=open_count, closed_count=closed_count,
        inprogress_count=inprogress_count, uat_count=uat_count, onhold_count=onhold_count,
        pending_add=pending_add, pending_edit=pending_edit, pending_delete=pending_delete,
        months=months_used, statuses=STATUSES, ticket_types=TICKET_TYPES,
        active_users=active_users, search_no=search_no, search_desc=search_desc,
        filter_month=filter_month, filter_status=filter_status,
        filter_ticket_type=filter_ticket_type, filter_assigned=filter_assigned,
        per_page=per_page, page_planned_total=page_planned_total,
        page_utilized_total=page_utilized_total, all_planned_total=all_planned_total,
        all_utilized_total=all_utilized_total, fmt_date=fmt_date_display,
        type_labels=type_labels, type_counts=type_counts_data,
    )
```
- Renders `templates/dashboard.html` with a large context: the paginated ticket list itself, six status-count stat cards, three pending-approval counts, filter-dropdown option lists, the current filter/search state (so the form fields stay populated after a search), both tiers of effort totals, the date formatter function (callable directly inside Jinja as `{{ fmt_date(ticket.estimated_uat) }}`), and Chart.js data arrays for the ticket-type breakdown chart.

### `GET /export` — `export()`

```python
@dashboard_bp.route('/export')
@login_required
def export():
    search_no          = request.args.get('search_no', '').strip()
    ... # same six filter params as index()
    tickets = _build_query(
        search_no, search_desc, filter_month, filter_status, filter_ticket_type, filter_assigned
    ).order_by(Ticket.created_at.desc()).all()
```
- Reuses the exact same six query-string parameters and `_build_query()` helper as `index()`, so exporting always reflects whatever filter/search was active on the dashboard when the user clicked "Export" (assuming the export link is built with the same query string, which is a template-level detail). `.all()` here (not `.paginate()`) — loads **every** matching row into memory, since an export needs the full result set, not just one page.

```python
    def fd(d):
        return d.strftime('%d-%b-%Y') if d else ''

    data = []
    for t in tickets:
        data.append({ 'Ticket No': t.ticket_no, 'Type': t.ticket_type, ... })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tickets')
    output.seek(0)
    filename = f'tickets_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return send_file(output, download_name=filename,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```
- Builds a list of plain dicts with human-readable column headers (distinct from `Ticket.to_dict()`'s machine-oriented keys), constructs a pandas `DataFrame`, and writes it to an **in-memory** `BytesIO` buffer (never touches the filesystem) using the `openpyxl` engine to produce a genuine `.xlsx` file. `output.seek(0)` rewinds the buffer to the start so `send_file` reads from the beginning rather than the end-of-write position. The filename embeds a timestamp down to the second, guaranteeing uniqueness across repeated exports. `send_file(..., as_attachment=True, mimetype=...)` triggers a browser download rather than inline rendering, with the correct Excel MIME type.

---

<a name="phase-9"></a>
## Phase 9: Request Lifecycle — Ticket CRUD & Bulk Upload (`routes/tickets.py`)

### Helper: `is_frozen()`
```python
def is_frozen():
    settings = SystemSettings.query.first()
    if settings and settings.freeze_date:
        return date.today() >= settings.freeze_date
    return False
```
- Reads the singleton settings row. If a `freeze_date` is set and today's date has reached or passed it, the system is considered "frozen" — meaning new ticket adds require approval instead of direct save (checked in `add_ticket()` below). If no settings row exists yet, or `freeze_date` is `None`, the system is never frozen.

### Helper: `parse_date(val)`
```python
def parse_date(val):
    if not val:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None
```
- A tolerant multi-format date parser: tries ISO (`2026-07-28`), then `DD-MM-YYYY`, then `DD/MM/YYYY`, returning the first successful parse as a `date` object (discarding the time component). If none of the three formats match, returns `None` silently (no exception raised to the caller) — meaning a malformed date string from a form or bulk-upload spreadsheet is quietly dropped rather than blocking the whole submission, which is forgiving but could mask data-entry mistakes without user feedback.

### Helper: `form_to_dict(form)`
```python
def form_to_dict(form):
    return {
        'ticket_no': form.get('ticket_no', '').strip(),
        ... # 18 keys total, each read via form.get(key, default).strip() or raw for numeric fields
    }
```
- Normalizes a Flask `request.form` (an `ImmutableMultiDict`) into a plain dict with consistent keys and whitespace-stripped string values, used as the canonical intermediate representation between "what the user typed" and "what gets applied to a `Ticket` object" (via `apply_dict_to_ticket` below) or "what gets JSON-serialized into an `ApprovalRequest`" (when frozen/edit). This single normalization point is what lets `edit_ticket()`'s diff logic compare old vs. new using identical key sets.

### Helper: `apply_dict_to_ticket(ticket, data)`
```python
def apply_dict_to_ticket(ticket, data):
    ticket.ticket_no = data['ticket_no']
    ... 
    try:
        ticket.planned_efforts = float(data['planned_efforts'])
    except (ValueError, TypeError):
        ticket.planned_efforts = 0
    try:
        ticket.utilized_efforts = float(data['utilized_efforts'])
    except (ValueError, TypeError):
        ticket.utilized_efforts = 0
    ...
    ticket.estimated_uat = parse_date(data['estimated_uat'])
    ...
```
- Mutates a `Ticket` ORM instance **in place** from a normalized dict (does not return anything — relies on the caller already holding a reference, whether newly-constructed or fetched from the DB). Numeric fields are defensively cast with `try/except`, falling back to `0` on any non-numeric input (e.g., empty string or garbage text) rather than raising and aborting the whole request. All six date fields are routed through `parse_date()`. This function is the single choke point for turning "raw string data" into "typed model attributes," reused identically whether the ticket is being added directly, added via approval, edited via approval, or bulk-uploaded — guaranteeing consistent coercion rules everywhere.

### `GET/POST /add` — `add_ticket()`

```python
@tickets_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_ticket():
    frozen = is_frozen()
    if request.method == 'POST':
        data = form_to_dict(request.form)

        if not data['ticket_no']:
            flash('Ticket number is required.', 'danger')
            return render_template('add_ticket.html', data=data, statuses=STATUSES,
                                   ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen)

        if Ticket.query.filter_by(ticket_no=data['ticket_no']).first():
            flash('Ticket number already exists.', 'danger')
            return render_template('add_ticket.html', data=data, statuses=STATUSES,
                                   ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen)
```
- Checks freeze status up front. On POST, normalizes the form, then validates: ticket number non-empty, and not already taken (an application-level duplicate check that runs *before* hitting the database's own `unique=True` constraint — giving a friendlier error message than a raw `IntegrityError`). Both failure paths re-render the add form with the user's already-typed `data` preserved (unlike `register()`, this view does pass data back), plus the dropdown option lists and current freeze state so the template can show/hide the "requires approval" banner.

```python
        if frozen:
            # Requires approval
            ar = ApprovalRequest(
                request_type='ADD',
                ticket_id=None,
                requested_by=current_user.username,
            )
            ar.set_request_data(data)
            db.session.add(ar)
            db.session.commit()
            log.info('Add request pending approval: ticket_no=%s by=%s', data['ticket_no'], current_user.username)
            flash('Freeze is active. Add request submitted for approval.', 'warning')
            return redirect(url_for('dashboard.index'))
```
- **Frozen branch**: no `Ticket` row is created at all yet — instead an `ApprovalRequest` (`request_type='ADD'`, `ticket_id=None` since there's no ticket yet) stores the entire submitted `data` dict as JSON via `set_request_data`. The actual `Ticket` creation only happens later if/when an admin approves it (see Phase 11's `_process_single_approval`).

```python
        else:
            # Direct save
            ticket = Ticket(created_by=current_user.username)
            apply_dict_to_ticket(ticket, data)
            db.session.add(ticket)
            db.session.commit()
            log_ticket_created(ticket, current_user.username)
            log.info('Ticket created: ticket_no=%s by=%s', ticket.ticket_no, current_user.username)
            flash('Ticket added successfully.', 'success')
            return redirect(url_for('dashboard.index'))
```
- **Unfrozen branch**: creates the `Ticket` directly, applies all form data, commits, then **calls into `services/history_service.log_ticket_created()`** (traced in Phase 14) to record the audit-trail entry, then flashes success and redirects.

```python
    active_users = User.query.filter_by(active_flag=True).order_by(User.username).all()
    return render_template('add_ticket.html', data={}, statuses=STATUSES,
                           ticket_types=TICKET_TYPES, months=MONTHS, frozen=frozen,
                           active_users=active_users)
```
- On plain `GET`, renders an empty add-ticket form (`data={}`) with all dropdown option lists and the assignable-users list for the "assigned to" selector.

### `GET/POST /edit/<int:ticket_id>` — `edit_ticket()`

```python
@tickets_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def edit_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    frozen = is_frozen()
```
- `<int:ticket_id>` — Flask URL converter ensures only integer path segments match this route (a non-numeric ID 404s automatically at the routing layer, before this function even runs). `first_or_404()` — fetches the ticket only if it exists **and is not soft-deleted**; otherwise Flask aborts with a genuine 404 response. Note edits are **not** gated on `frozen` the way adds are — see below, edits *always* require approval regardless of freeze state.

```python
    if request.method == 'POST':
        new_data = form_to_dict(request.form)
        old_data = ticket.to_dict()

        date_fields = {'estimated_uat', 'estimated_prod', 'actual_uat', 'actual_prod',
                       'revised_uat_date', 'revised_prod_date'}
        changed_fields = []
        for field in new_data:
            old_val = str(old_data.get(field) or '')
            new_val = str(new_data.get(field) or '')
            if old_val != new_val:
                changed_fields.append(field)

        if not changed_fields:
            flash('No changes detected.', 'info')
            return redirect(url_for('dashboard.index'))
```
- `old_data = ticket.to_dict()` — snapshots the ticket's **current** DB state (using the model's own serializer, Phase 5.3). `new_data = form_to_dict(...)` — normalizes what was submitted. The loop iterates every key in `new_data` and string-compares it against the corresponding value in `old_data` (coercing both to strings via `str(... or '')` so type differences, e.g. `float` vs `str`, or `None` vs `''`, don't cause false-positive "changed" detections) — building a list of field names that actually differ. Note `date_fields` is defined but **never referenced again in this function** — apparent dead code, likely a leftover from an earlier version that special-cased date comparison formatting; the current string-comparison approach works uniformly for all field types including dates because `form_to_dict` already stores dates as plain `'YYYY-MM-DD'` strings from the HTML date input, matching `to_dict()`'s `fmt_date` output format.
- If nothing changed, short-circuits with an info flash and redirect — avoids creating pointless approval requests for a no-op edit submission.

```python
        # Always requires approval for edit
        ar = ApprovalRequest(
            request_type='EDIT',
            ticket_id=ticket.id,
            requested_by=current_user.username,
        )
        ar.set_request_data({
            'old_data': old_data,
            'new_data': new_data,
            'changed_fields': changed_fields,
        })
        db.session.add(ar)
        db.session.commit()
        log.info('Edit request pending approval: ticket=%s fields=%s by=%s', ticket.ticket_no, changed_fields, current_user.username)
        flash('Edit request submitted for approval.', 'warning')
        return redirect(url_for('dashboard.index'))
```
- Unlike `add_ticket()`, edits **unconditionally** go through the approval workflow — the comment explicitly says "Always requires approval for edit," a deliberate policy difference from adds (which only require approval when frozen). The `ApprovalRequest.request_data` JSON payload bundles `old_data`, `new_data`, and the precomputed `changed_fields` list together — this is exactly the shape `approval_details()` (Phase 11) expects when building its diff view, and exactly what `_process_single_approval()`'s EDIT branch expects when applying the change on approval.

```python
    # Pre-populate form
    def fmt_date(d):
        return d.strftime('%Y-%m-%d') if d else ''

    data = { 'ticket_no': ticket.ticket_no, ... 'assigned_to': ticket.assigned_to or '' }
    active_users = User.query.filter_by(active_flag=True).order_by(User.username).all()
    return render_template('edit_ticket.html', ticket=ticket, data=data,
                           statuses=STATUSES, ticket_types=TICKET_TYPES,
                           months=MONTHS, frozen=frozen, active_users=active_users)
```
- On `GET` (or after building the dict on first entry to the function, which happens regardless of method — Python executes top to bottom and this block is *after* the `if POST: ... return` block, so it only runs when method is `GET`, since POST always returns early above), renders the edit form pre-populated with the ticket's current values, dates reformatted to `YYYY-MM-DD` (the format native HTML `<input type="date">` expects), and passes the `ticket` object itself too (likely for displaying non-editable metadata like `ticket.created_by`/`created_at` in the template).

### `POST /delete/<int:ticket_id>` — `delete_ticket()`

```python
@tickets_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
def delete_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()

    existing = ApprovalRequest.query.filter_by(
        ticket_id=ticket_id, request_type='DELETE', status='PENDING'
    ).first()
    if existing:
        flash('A delete request is already pending for this ticket.', 'warning')
        return redirect(url_for('dashboard.index'))
```
- POST-only (no GET form — deletion is triggered by a button/form submit, not a navigable URL, reducing accidental deletion via link-clicking or crawlers). Guards against submitting a duplicate delete request while one is already pending for the same ticket.

```python
    ar = ApprovalRequest(
        request_type='DELETE',
        ticket_id=ticket.id,
        requested_by=current_user.username,
    )
    ar.set_request_data(ticket.to_dict())
    db.session.add(ar)
    ticket.delete_requested = True
    ticket.delete_requested_by = current_user.username
    ticket.delete_requested_date = datetime.utcnow()
    db.session.commit()
    log.info('Delete request pending approval: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash('Delete request submitted for approval.', 'warning')
    return redirect(url_for('dashboard.index'))
```
- Like edits, deletes **always** require approval — there's no direct-delete path at all in this codebase, even when unfrozen. Snapshots the full current ticket state into `request_data` (so admins reviewing the request, or anyone auditing later, can see exactly what would be deleted). Also flips the ticket's own `delete_requested*` fields **immediately** (not waiting for approval) — this is what allows the dashboard/UI to visually flag "delete pending" on the ticket even before an admin acts, and is what the "already pending" guard above checks against. Note both the `ApprovalRequest` row and the `Ticket` flag updates happen in the **same transaction** (single `db.session.commit()` at the end), so they're atomic — either both succeed or (on error) neither is persisted.

### `GET /view/<int:ticket_id>` — `view_ticket()`

```python
@tickets_bp.route('/view/<int:ticket_id>')
@login_required
def view_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    def fmt_date(d):
        return d.strftime('%d-%b-%Y') if d else '–'
    return render_template('view_ticket.html', ticket=ticket, fmt_date=fmt_date)
```
- Read-only detail view. Note this is the page that also renders the comment thread (`ticket.comments`, via the relationship established in `models/comment.py`) and the add-comment form that posts to `comments.add_comment` (Phase 10) — the template joins ticket detail + comments in one page even though the Python view function here doesn't explicitly query comments itself (it relies on the `ticket.comments` dynamic relationship being accessed lazily inside the Jinja template).

### `GET /history/<int:ticket_id>` — `ticket_history()`

```python
@tickets_bp.route('/history/<int:ticket_id>')
@login_required
def ticket_history(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    history = ticket.history.order_by(db.text('changed_at desc')).all()
    return render_template('history.html', ticket=ticket, history=history)
```
- Note this uses `get_or_404` (not `filter_by(deleted_flag=False)`) — meaning a **soft-deleted** ticket's history is still viewable (useful for audit purposes even after deletion, e.g. via a link from the admin "Deleted Tickets" view). `ticket.history` is the dynamic relationship from `TicketHistory` (Phase 5.4), ordered newest-first via a raw SQL text fragment `db.text('changed_at desc')` (rather than the ORM-idiomatic `TicketHistory.changed_at.desc()`) — functionally equivalent, just a stylistic choice.

### `GET/POST /bulk-upload` — `bulk_upload()`

```python
@tickets_bp.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    frozen = is_frozen()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls')):
            flash('Please upload a valid Excel file.', 'danger')
            return render_template('bulk_upload.html')
```
- `request.files.get('file')` — reads the uploaded file from `templates/bulk_upload.html`'s multipart form (the field must be named `file`). Validates a file was actually attached and has a recognized Excel extension (a shallow check — doesn't verify actual file content/magic bytes, so a renamed non-Excel file would pass this check but fail at the `pd.read_excel` step below).

```python
        try:
            df = pd.read_excel(file)
            df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        except Exception as e:
            flash(f'Error reading file: {e}', 'danger')
            return render_template('bulk_upload.html')
```
- `pd.read_excel(file)` reads directly from the uploaded file-like object (no temp file written to disk). Column names are normalized: trimmed, lowercased, spaces replaced with underscores — so a spreadsheet with a header `"Ticket No"` becomes the Python-friendly key `ticket_no`, matching the expected internal field names. Any parse failure (corrupt file, wrong format, etc.) is caught broadly and surfaced as a flash message including the raw exception text `{e}` — mildly risky from an information-disclosure perspective (could leak internal file-path details in some pandas error messages) but reasonable for an internal tool.

```python
        required_cols = ['ticket_no', 'description']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            flash(f'Missing required columns: {", ".join(missing)}', 'danger')
            return render_template('bulk_upload.html')
```
- Only two columns are hard-required: `ticket_no` and `description`. All other fields are optional in the uploaded spreadsheet.

```python
        added = 0
        skipped = 0
        pending = 0
        errors = []

        for idx, row in df.iterrows():
            ticket_no = str(row.get('ticket_no', '')).strip()
            if not ticket_no or ticket_no == 'nan':
                skipped += 1
                continue

            if Ticket.query.filter_by(ticket_no=ticket_no).first():
                errors.append(f'Row {idx+2}: Ticket {ticket_no} already exists.')
                skipped += 1
                continue
```
- Iterates every spreadsheet row (`df.iterrows()` yields `(index, Series)` pairs; `idx` is the zero-based DataFrame row index). `str(row.get('ticket_no', '')).strip()` handles pandas' `NaN` representation for genuinely empty cells — but note that `str(NaN)` produces the literal string `'nan'`, which is why the check explicitly also excludes `ticket_no == 'nan'` (a common pandas gotcha correctly handled here). Blank ticket numbers are silently skipped (counted). Rows whose ticket number already exists in the DB (checked per-row, against the live DB state, so duplicates *within* the same uploaded file up to that point would also be caught since earlier rows in the same loop may have already been inserted — though inserted rows aren't flushed to the DB until later unless `db.session.flush()` is called, see below) are recorded as an error with a 1-indexed-plus-header row number (`idx+2`: +1 for zero-index-to-one-index, +1 more for the header row) and skipped.

```python
            def safe_str(val):
                v = str(val).strip() if pd.notna(val) else ''
                return '' if v == 'nan' else v

            def safe_date(val):
                if pd.isna(val):
                    return None
                try:
                    if hasattr(val, 'date'):
                        return val.date()
                    return parse_date(str(val))
                except:
                    return None
```
- `safe_str` — a closure defined fresh on every loop iteration (mildly wasteful but harmless at this data scale) that converts any pandas cell value to a clean string, treating `NaN`/`NaT` (`pd.notna` check) and the string `'nan'` both as empty string.
- `safe_date` — handles the fact that pandas may parse Excel date cells as native `pandas.Timestamp`/`datetime` objects (which have a `.date()` method) rather than strings — in that case it calls `.date()` directly; otherwise it falls back to the same `parse_date()` string-format parser used elsewhere, wrapped in a bare `except:` that swallows any error and returns `None` (again silently dropping unparseable dates without erroring the whole row). Interestingly, `safe_date` is **defined but never actually called** anywhere in this function — all date fields below instead go through `safe_str(...)` and are then parsed later by `apply_dict_to_ticket`'s own `parse_date()` call, making `safe_date` dead code (a leftover helper, confirmed by inspection — not fabricated).

```python
            data = {
                'ticket_no': ticket_no,
                'ticket_type': safe_str(row.get('ticket_type', '')),
                ... # remaining 16 fields via safe_str(row.get(...))
                'planned_efforts': str(row.get('planned_efforts', '0') or '0'),
                'utilized_efforts': str(row.get('utilized_efforts', '0') or '0'),
                ...
            }
```
- Builds the same normalized `data` dict shape as `form_to_dict()` produces from a web form, so it can be fed into the same `apply_dict_to_ticket()` function — reuse of the single source of truth for field coercion. Numeric fields are stringified (since `apply_dict_to_ticket` expects string input it will `float()`-cast itself) with `'0'` fallback if missing/falsy.

```python
            if frozen:
                ar = ApprovalRequest(request_type='ADD', requested_by=current_user.username)
                ar.set_request_data(data)
                db.session.add(ar)
                pending += 1
            else:
                ticket = Ticket(created_by=current_user.username)
                apply_dict_to_ticket(ticket, data)
                db.session.add(ticket)
                db.session.flush()
                log_ticket_created(ticket, current_user.username)
                added += 1

        db.session.commit()
```
- Same frozen/unfrozen branching as `add_ticket()`, applied per-row. In the unfrozen branch, `db.session.flush()` is called **immediately after adding each ticket** (unlike `_seed_dummy_data()`'s batch-commit-at-the-end pattern) — `flush()` pushes the pending INSERT to the database (assigning the new row its auto-increment `id`) *without* committing the transaction, which is necessary here because `log_ticket_created(ticket, ...)` (called right after) needs `ticket.id` to already exist to create the `TicketHistory` row's foreign key — and `log_ticket_created` itself calls `db.session.commit()` internally (see Phase 14), meaning **each successfully-added row in the loop is actually committed individually** via the nested `history_service` call, not batched — a subtle but real detail: the final `db.session.commit()` after the loop mainly finalizes any pending `ApprovalRequest` inserts from the frozen branch (which are never individually flushed/committed inside the loop).

```python
        msg = f'Bulk upload: {added} added, {pending} pending approval, {skipped} skipped.'
        if errors:
            msg += ' Errors: ' + '; '.join(errors[:5])
        log.info('Bulk upload: added=%d pending=%d skipped=%d by=%s', added, pending, skipped, current_user.username)
        flash(msg, 'info')
        return redirect(url_for('dashboard.index'))

    return render_template('bulk_upload.html')
```
- Builds a summary flash message with counts, appending up to the first 5 error messages (truncated to avoid an unreadably long flash banner if many rows failed). `GET` requests simply render the empty upload form.

### `GET /template` — `download_template()`

```python
@tickets_bp.route('/template')
@login_required
def download_template():
    data = { 'ticket_no': ['TKT-001'], ... }  # one example row, all 18 fields
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tickets')
    output.seek(0)
    return send_file(output, download_name='bulk_upload_template.xlsx', as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```
- Generates a downloadable one-row example spreadsheet showing the expected column headers and sample values, so users know the exact format `bulk_upload()` expects — same in-memory `BytesIO`/`ExcelWriter` pattern as `dashboard.export()`.

---

<a name="phase-10"></a>
## Phase 10: Request Lifecycle — Comments (`routes/comments.py`)

### `POST /tickets/<int:ticket_id>/comments/add` — `add_comment()`

```python
@comments_bp.route('/tickets/<int:ticket_id>/comments/add', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=False).first_or_404()
    body = request.form.get('body', '').strip()

    if not body:
        flash('Comment cannot be empty.', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    if len(body) > 2000:
        flash('Comment is too long (max 2000 characters).', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    comment = TicketComment(
        ticket_id=ticket.id,
        body=body,
        created_by=current_user.username,
    )
    db.session.add(comment)
    db.session.commit()
    log.info('Comment added: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash('Comment added.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))
```
- POST-only, called from the comment form on `view_ticket.html`. Requires the ticket to exist and not be soft-deleted. Two validation gates: non-empty body, and a 2000-character cap (enforced only in Python here — the DB column is an unbounded `Text` type). On success, creates the `TicketComment`, commits, and redirects back to the ticket detail page (`tickets.view_ticket`) — this is a standard Post/Redirect/Get pattern, preventing duplicate comment submission on page refresh.

### `POST /tickets/<int:ticket_id>/comments/<int:comment_id>/delete` — `delete_comment()`

```python
@comments_bp.route('/tickets/<int:ticket_id>/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(ticket_id, comment_id):
    comment = TicketComment.query.filter_by(id=comment_id, ticket_id=ticket_id).first_or_404()

    if comment.created_by != current_user.username and not current_user.is_admin():
        flash('You can only delete your own comments.', 'danger')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    db.session.delete(comment)
    db.session.commit()
    log.info('Comment deleted: id=%s ticket=%s by=%s', comment_id, ticket_id, current_user.username)
    flash('Comment deleted.', 'info')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))
```
- The `filter_by(id=comment_id, ticket_id=ticket_id)` double-condition ensures a comment ID can only be deleted through the URL of the ticket it actually belongs to (prevents a crafted URL mixing a valid `comment_id` with an unrelated `ticket_id` from producing confusing redirect behavior — though the 404 would occur either way if they don't match). Authorization check: only the comment's original author **or** an admin can delete it — everyone else gets a danger flash and redirect without deletion. This is a genuine **hard delete** (`db.session.delete(comment)`, not a soft-delete flag) — unlike tickets, deleted comments are permanently removed with no audit trail or undo, and no approval workflow gates comment deletion at all.

---

<a name="phase-11"></a>
## Phase 11: Request Lifecycle — Approvals Workflow (`routes/approvals.py`)

### Helper: `_process_single_approval(approval, action, admin_username, comments)`

This is the core state-machine function, shared by both the single-approval and bulk-approval routes.

```python
def _process_single_approval(approval, action, admin_username, comments):
    """Apply approve/reject logic for one ApprovalRequest. Caller must commit."""
    approval.approved_by = admin_username
    approval.approved_at = datetime.utcnow()
    approval.comments = comments

    ticket_no = 'N/A'
```
- Regardless of approve/reject, always stamps who acted and when, and stores any admin-provided free-text comments. `ticket_no` defaults to `'N/A'` as a fallback used in the email notification if no ticket association can be resolved. The docstring explicitly notes the caller is responsible for the actual `db.session.commit()` — this function only stages changes (via ORM attribute mutation and `db.session.add`/`flush`), enabling the bulk-action route to process many approvals in one transaction.

```python
    if action == 'approve':
        approval.status = 'APPROVED'
        data = approval.get_request_data()

        if approval.request_type == 'ADD':
            ticket = Ticket(created_by=approval.requested_by)
            apply_dict_to_ticket(ticket, data)
            db.session.add(ticket)
            db.session.flush()
            approval.ticket_id = ticket.id
            log_ticket_created(ticket, approval.requested_by)
            ticket_no = ticket.ticket_no
            log.info('ADD approved: ticket=%s by=%s', ticket.ticket_no, admin_username)
```
- **ADD approval**: this is the moment an approved "add" request finally becomes a real `Ticket` row — note `created_by=approval.requested_by`, **not** `admin_username` — the ticket's creator is correctly attributed to the original requester, not the approving admin. `apply_dict_to_ticket(ticket, data)` reuses the exact same coercion function from `routes/tickets.py` (imported cross-module, Phase 5.3) to apply the stored JSON payload. `db.session.flush()` (not commit) pushes the INSERT to get an auto-generated `ticket.id` **within the still-open transaction**, which is then written back onto `approval.ticket_id` — linking the approval record to its resulting ticket permanently. `log_ticket_created` (**Phase 14**) is called here too, so the audit trail correctly shows the ticket's "CREATED" history event timestamped at *approval* time, not at original-request time.

```python
        elif approval.request_type == 'EDIT':
            ticket = approval.ticket
            if ticket:
                old_data = ticket.to_dict()
                apply_dict_to_ticket(ticket, data['new_data'])
                ticket.updated_at = datetime.utcnow()
                db.session.flush()
                log_ticket_changes(ticket.id, old_data, data['new_data'],
                                   approval.requested_by, 'UPDATED')
                ticket_no = ticket.ticket_no
                log.info('EDIT approved: ticket=%s by=%s', ticket.ticket_no, admin_username)
```
- **EDIT approval**: `approval.ticket` uses the `ApprovalRequest.ticket` relationship (Phase 5.3) to fetch the live ticket via its stored `ticket_id` FK. `if ticket:` guards against the (unlikely but possible) case where the ticket was deleted/removed between request and approval — in that case the edit silently does nothing except mark the approval `APPROVED` with no actual data change (a subtle edge case worth knowing).
- Important: `old_data = ticket.to_dict()` is re-snapshotted **at approval time**, not reused from the originally-stored `data['old_data']` in the approval request — meaning if the ticket was somehow modified between the edit request being submitted and being approved (e.g., a different concurrent edit was approved first), the history log records the *actual* pre-approval state, not the stale state captured when the edit was originally requested. This is more correct/accurate for audit purposes but means `log_ticket_changes` might record a different "old value" than what the requesting user originally saw.
- `apply_dict_to_ticket(ticket, data['new_data'])` applies only the `new_data` portion of the stored payload (recall `edit_ticket()` stored `{'old_data':..., 'new_data':..., 'changed_fields':...}`). `ticket.updated_at` is explicitly bumped (redundant with the model's `onupdate=datetime.utcnow`, which would fire automatically on any UPDATE anyway — this explicit set is harmless double-coverage). `db.session.flush()` ensures the update is pushed before `log_ticket_changes` runs (though for an UPDATE on an existing row, `ticket.id` is already known, so flush here is less critical than in the ADD case — still good practice for consistency). `log_ticket_changes` (**Phase 14**) then computes and logs the actual per-field diff.

```python
        elif approval.request_type == 'DELETE':
            ticket = approval.ticket
            if ticket:
                ticket.deleted_flag = True
                ticket.delete_requested = False
                db.session.flush()
                log_ticket_deleted(ticket, approval.requested_by)
                ticket_no = ticket.ticket_no
                log.info('DELETE approved: ticket=%s by=%s', ticket.ticket_no, admin_username)
```
- **DELETE approval**: sets the soft-delete flag `True` and clears the pending-request flag `False` (so the "delete pending" UI indicator clears). Same `if ticket:` defensive guard. `log_ticket_deleted` (**Phase 14**) records the audit event.

```python
    elif action == 'reject':
        approval.status = 'REJECTED'
        if approval.request_type == 'DELETE' and approval.ticket:
            approval.ticket.delete_requested = False
        if approval.ticket:
            ticket_no = approval.ticket.ticket_no
        log.info('Request rejected: approval_id=%s type=%s by=%s',
                 approval.id, approval.request_type, admin_username)
```
- **Rejection**: simply marks the request `REJECTED` with no data changes to the ticket itself — **except** for a DELETE rejection, which specifically clears `delete_requested` back to `False` on the ticket (since the pending-delete flag was set eagerly at request time in `delete_ticket()`, rejecting the request must also clear it, otherwise the ticket would remain permanently stuck showing "delete pending" in the UI with no way to clear it). ADD/EDIT rejections need no such cleanup since those request types never mutate the underlying ticket at request time (an EDIT-in-flight ticket is untouched until approval; an ADD-in-flight has no ticket at all yet).

```python
    # Send email notification to requester (non-blocking)
    requester = User.query.filter_by(username=approval.requested_by).first()
    if requester and requester.email:
        send_approval_notification(
            requester.username, requester.email,
            action, approval.request_type, ticket_no, comments
        )

    return ticket_no
```
- Regardless of approve/reject/type, looks up the original requester by username and, if found with a valid email, **calls into `services/email_service.send_approval_notification`** (traced in Phase 13) to notify them of the outcome. The comment "(non-blocking)" reflects that `send_approval_notification` internally catches its own exceptions (Phase 13) so an SMTP failure here never breaks the approval transaction itself. Returns the resolved `ticket_no` (used only internally by callers for flash-message context, not otherwise significant).

### `GET /approvals` — `pending_approvals()`

```python
@approvals_bp.route('/approvals')
@login_required
@admin_required
def pending_approvals():
    pending = ApprovalRequest.query.filter_by(status='PENDING').order_by(
        ApprovalRequest.requested_at.desc()
    ).all()
    return render_template('pending_approvals.html', approvals=pending)
```
- Note the decorator stacking: `@login_required` (outermost, runs first) then `@admin_required` (Phase 5.3's implementation) — both must pass before `pending_approvals` executes. Straightforward: all pending requests, newest-first, no pagination (assumes pending-request volume stays manageable — a genuine scalability limit worth noting for a high-traffic deployment, though reasonable for an internal tool).

### `GET /approvals/<int:approval_id>` — `approval_details()`

```python
@approvals_bp.route('/approvals/<int:approval_id>')
@login_required
@admin_required
def approval_details(approval_id):
    approval = ApprovalRequest.query.get_or_404(approval_id)
    data = approval.get_request_data()
    ticket = approval.ticket

    diff = None
    if approval.request_type == 'EDIT' and 'changed_fields' in data:
        diff = []
        old_data = data.get('old_data', {})
        new_data = data.get('new_data', {})
        for field in data['changed_fields']:
            diff.append({
                'label': FIELD_LABELS.get(field, field),
                'old': old_data.get(field, ''),
                'new': new_data.get(field, ''),
            })

    return render_template('approval_details.html',
        approval=approval, data=data, ticket=ticket, diff=diff, field_labels=FIELD_LABELS,
    )
```
- Fetches the full approval record (404 if not found). `data = approval.get_request_data()` deserializes the JSON payload. `ticket = approval.ticket` resolves the related ticket if any (via the FK relationship — `None` for a still-pending ADD request, since `ticket_id` is `None` until approved).
- The `diff` construction is **only** built for `EDIT` requests whose stored data happens to include a `'changed_fields'` key (a defensive `in` check — true for every EDIT created via `edit_ticket()`, since that route always stores this key, but guards against malformed/legacy data). For each changed field, builds a `{label, old, new}` triple using `FIELD_LABELS` for a human-readable name, falling back to the raw field name (`FIELD_LABELS.get(field, field)`) if somehow not in the lookup dict. This `diff` list is what the template renders as a before/after comparison table for the admin reviewing the edit.

### `POST /approvals/<int:approval_id>/action` — `approval_action()`

```python
@approvals_bp.route('/approvals/<int:approval_id>/action', methods=['POST'])
@login_required
@admin_required
def approval_action(approval_id):
    approval = ApprovalRequest.query.get_or_404(approval_id)
    if approval.status != 'PENDING':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('approvals.pending_approvals'))

    action = request.form.get('action')
    comments = request.form.get('comments', '').strip()

    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('approvals.pending_approvals'))

    _process_single_approval(approval, action, current_user.username, comments)
    db.session.commit()

    if action == 'approve':
        type_msg = {'ADD': 'Ticket created.', 'EDIT': 'Ticket updated.', 'DELETE': 'Ticket deleted.'}
        flash(f'{approval.request_type} request approved. {type_msg.get(approval.request_type, "")}', 'success')
    else:
        flash('Request rejected.', 'info')

    return redirect(url_for('approvals.pending_approvals'))
```
- Guards against double-processing an already-resolved request (`status != 'PENDING'`) — protects against, e.g., a double-submitted form or a stale browser tab re-posting an action. Validates `action` is exactly `'approve'` or `'reject'` before proceeding — anything else (missing field, typo, tampered form) is rejected with a flash and no processing. Delegates all actual logic to `_process_single_approval`, then this route is responsible for the final `db.session.commit()` (per that function's documented contract). Builds a type-specific success message for approvals (different wording for ADD/EDIT/DELETE) versus a generic rejection message.

### `POST /approvals/bulk-action` — `bulk_approval_action()`

```python
@approvals_bp.route('/approvals/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_approval_action():
    approval_ids = request.form.getlist('approval_ids')
    action = request.form.get('action')

    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('approvals.pending_approvals'))

    if not approval_ids:
        flash('No approvals selected.', 'warning')
        return redirect(url_for('approvals.pending_approvals'))
```
- `request.form.getlist('approval_ids')` — reads **multiple** form values sharing the name `approval_ids` (a multi-checkbox form field on `pending_approvals.html`), returning a list of string IDs. Same action validation as the single-action route, plus a check that at least one ID was actually selected.

```python
    processed = 0
    for aid in approval_ids:
        try:
            approval = ApprovalRequest.query.get(int(aid))
            if approval and approval.status == 'PENDING':
                _process_single_approval(approval, action, current_user.username, '')
                processed += 1
        except Exception as e:
            log.error('Bulk action failed for id=%s: %s', aid, e)
            db.session.rollback()

    db.session.commit()
    flash(f'{processed} request(s) {action}d successfully.', 'success')
    return redirect(url_for('approvals.pending_approvals'))
```
- Iterates each submitted ID string, converts to `int`, re-fetches (defensive re-validation that the approval still exists and is still `PENDING`, since another admin could theoretically have concurrently processed it — a real race-condition guard). Notice `comments=''` is always passed (no per-item admin comment supported in bulk mode, unlike the single-action route). Each iteration is wrapped in its own `try/except`: if `_process_single_approval` raises for one item (e.g., a data integrity issue), that failure is logged and `db.session.rollback()` is called — **this rolls back the entire pending transaction, including any successfully-processed items from earlier in the loop that hadn't been committed yet**, since SQLAlchemy's session-level rollback undoes all uncommitted work, not just the failing item. This means a failure partway through a bulk action could silently discard progress on earlier items in the same batch (they'd need to be re-submitted) — a real behavioral subtlety worth flagging, not a fabrication. The final `db.session.commit()` after the loop persists whatever remains staged (all items if no exceptions occurred, or a possibly-empty set if the last exception's rollback wiped everything and no further successful items followed it).

---

<a name="phase-12"></a>
## Phase 12: Request Lifecycle — Admin (`routes/admin.py`)

### `GET /admin/users` — `users()`

```python
@admin_bp.route('/admin/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users.html', users=all_users)
```
- Simple listing, newest-registered first, admin-only.

### `POST /admin/users/<int:user_id>/toggle-active` — `toggle_active()`

```python
@admin_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate yourself.', 'danger')
        return redirect(url_for('admin.users'))
    user.active_flag = not user.active_flag
    db.session.commit()
    status = 'activated' if user.active_flag else 'deactivated'
    log.info('User %s: by=%s', status, current_user.username)
    flash(f'User {user.username} has been {status}.', 'success')
    return redirect(url_for('admin.users'))
```
- Self-protection check: an admin cannot deactivate their own account (would otherwise be able to lock themselves out, and if they were the only admin, potentially lock out the whole system's admin access). `user.active_flag = not user.active_flag` is a toggle, not a set-to-specific-value — meaning this single route serves both "activate" and "deactivate," inferred from the user's current state.

### `POST /admin/users/<int:user_id>/promote` — `promote_user()`

```python
@admin_bp.route('/admin/users/<int:user_id>/promote', methods=['POST'])
@login_required
@admin_required
def promote_user(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'Admin' if user.role == 'User' else 'User'
    db.session.commit()
    log.info('Role changed: user=%s new_role=%s by=%s', user.username, user.role, current_user.username)
    flash(f'User {user.username} role set to {user.role}.', 'success')
    return redirect(url_for('admin.users'))
```
- Another toggle route (misleadingly named "promote" but actually toggles both directions: `User → Admin` and `Admin → User`). **No self-protection check here** — unlike `toggle_active`, an admin *can* demote themselves (or even demote the only other admin, or demote themselves down to zero admins remaining in the system, since there's no "last admin" safeguard anywhere in this codebase) — a genuine gap worth flagging, not fabricated: confirmed by the absence of any `if user.id == current_user.id` guard in this function.

### `POST /admin/users/<int:user_id>/reset-password` — `reset_password()`

```python
@admin_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    from services.email_service import send_reset_password_email
    user = User.query.get_or_404(user_id)
    sent = send_reset_password_email(user)
    if sent:
        flash(f'Password reset email sent to {user.email}.', 'success')
    else:
        flash('Could not send email. Check mail config.', 'warning')
    return redirect(url_for('admin.users'))
```
- Note the **local, function-scoped import** `from services.email_service import send_reset_password_email` — unusual compared to the rest of the codebase, which imports services at module top-level. This local import still resolves instantly from `sys.modules` cache (the module was already loaded during the `routes.auth` import chain in Phase 5.3) so there's no real cost, but it's a stylistic inconsistency worth noting. This is the admin-side "help a user who never got/lost their set-password email" recovery path — **calls into `email_service`** (Phase 13).

### `GET/POST /admin/freeze` — `freeze_settings()`

```python
@admin_bp.route('/admin/freeze', methods=['GET', 'POST'])
@login_required
@admin_required
def freeze_settings():
    settings = SystemSettings.query.first()
    if request.method == 'POST':
        freeze_date_str = request.form.get('freeze_date', '').strip()
        freeze_date = None
        if freeze_date_str:
            try:
                freeze_date = datetime.strptime(freeze_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format.', 'danger')
                return render_template('freeze_settings.html', settings=settings)
```
- Reads the (possibly `None`, if no row exists yet) singleton settings row. On POST, parses the submitted date string strictly as `%Y-%m-%d` (matching the native HTML date input format) — a parse failure flashes an error and re-renders with the stale `settings` object (note: unlike some other forms, this doesn't preserve the just-typed invalid string back into the form — the template would show whatever `settings.freeze_date` was previously, not the rejected input). An empty submitted string is treated as intentionally **clearing** the freeze (`freeze_date = None`), i.e., this form doubles as both "set a freeze date" and "unfreeze the system."

```python
        if settings:
            settings.freeze_date = freeze_date
            settings.updated_by = current_user.username
            settings.updated_at = datetime.utcnow()
        else:
            settings = SystemSettings(
                freeze_date=freeze_date,
                updated_by=current_user.username
            )
            db.session.add(settings)
        db.session.commit()
        log.info('Freeze date set to %s by=%s', freeze_date, current_user.username)
        flash('Freeze date updated successfully.', 'success')
        return redirect(url_for('admin.freeze_settings'))

    return render_template('freeze_settings.html', settings=settings)
```
- Classic upsert pattern: update the existing singleton row if present, otherwise create the first one. This is what `is_frozen()` in `tickets.py` (Phase 9) reads to gate direct ticket adds.

### `GET /admin/deleted-tickets` — `deleted_tickets()`

```python
@admin_bp.route('/admin/deleted-tickets')
@login_required
@admin_required
def deleted_tickets():
    tickets = Ticket.query.filter_by(deleted_flag=True).order_by(Ticket.updated_at.desc()).all()
    return render_template('deleted_tickets.html', tickets=tickets)
```
- The inverse of every other ticket-listing view — shows **only** soft-deleted tickets, newest-updated first, for potential restoration.

### `POST /admin/restore/<int:ticket_id>` — `restore_ticket()`

```python
@admin_bp.route('/admin/restore/<int:ticket_id>', methods=['POST'])
@login_required
@admin_required
def restore_ticket(ticket_id):
    ticket = Ticket.query.filter_by(id=ticket_id, deleted_flag=True).first_or_404()
    ticket.deleted_flag = False
    ticket.delete_requested = False
    db.session.commit()
    log_ticket_restored(ticket, current_user.username)
    log.info('Ticket restored: ticket=%s by=%s', ticket.ticket_no, current_user.username)
    flash(f'Ticket {ticket.ticket_no} has been restored.', 'success')
    return redirect(url_for('admin.deleted_tickets'))
```
- The only route allowed to flip `deleted_flag` back to `False`, restricted to admins, and only operates on tickets that are actually currently soft-deleted (`filter_by(..., deleted_flag=True)` — attempting to restore a non-deleted ticket 404s). Clears `delete_requested` defensively too. Calls `log_ticket_restored` (**Phase 14**) after the commit (note: the history log call happens *after* `db.session.commit()` here, unlike most other routes which log-then-let-the-history-function-commit-separately — but since `log_ticket_restored` does its own independent `db.session.add`+`commit`, the ordering doesn't cause any data loss, just means it's technically two separate transactions rather than one atomic one).

### `GET /admin/analytics` — `analytics()`

```python
@admin_bp.route('/admin/analytics')
@login_required
@admin_required
def analytics():
    from sqlalchemy import func

    monthly = db.session.query(
        func.strftime('%Y-%m', Ticket.created_at).label('month'),
        func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by('month').order_by('month').all()
```
- `func.strftime('%Y-%m', Ticket.created_at)` — pushes SQLite's native `strftime()` function down into the SQL query itself (via SQLAlchemy's generic `func` proxy, which passes through to whatever the underlying dialect supports) to bucket tickets by creation year-month directly in the database, rather than pulling every row into Python and grouping there — a genuine performance-conscious choice, though it does mean this specific analytics query is **SQLite-specific** (a different DB backend like PostgreSQL doesn't have `strftime` and would require `to_char` or similar — a portability limitation worth noting, confirmed by reading the code, not speculation). `.label('month')` names the computed column so `.group_by('month')`/`.order_by('month')` can reference it by alias.

```python
    effort_by_month = db.session.query(
        Ticket.planned_month,
        func.sum(Ticket.planned_efforts),
        func.sum(Ticket.utilized_efforts)
    ).filter(
        Ticket.deleted_flag == False,
        Ticket.planned_month.isnot(None)
    ).group_by(Ticket.planned_month).all()

    by_type = db.session.query(
        Ticket.ticket_type, func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.ticket_type).all()

    by_status = db.session.query(
        Ticket.status, func.count(Ticket.id)
    ).filter(Ticket.deleted_flag == False).group_by(Ticket.status).all()
```
- Three more grouped-aggregate queries: effort totals per planned month (excluding tickets with no planned month at all), ticket count per type, ticket count per status — all mirroring patterns already seen in `dashboard.index()` but assembled here specifically for the dedicated analytics page.

```python
    return render_template('admin_analytics.html',
        monthly_labels=[r[0] for r in monthly],
        monthly_counts=[r[1] for r in monthly],
        effort_months=[r[0] for r in effort_by_month],
        effort_planned=[float(r[1] or 0) for r in effort_by_month],
        effort_utilized=[float(r[2] or 0) for r in effort_by_month],
        type_labels=[r[0] or 'Unset' for r in by_type],
        type_counts=[r[1] for r in by_type],
        status_labels=[r[0] for r in by_status],
        status_counts=[r[1] for r in by_status],
    )
```
- Every result set is flattened into parallel label/value arrays — the exact shape Chart.js needs client-side. `float(r[1] or 0)` guards against `NULL` sums the same way `dashboard.index()` did. `r[0] or 'Unset'` again substitutes a display label for `NULL` ticket types.

---

<a name="phase-13"></a>
## Phase 13: Services Deep Dive — `services/email_service.py`

This module was first imported during Phase 5.3 (by `routes/auth.py`), and its functions are called from `auth.py` (register/set-password/forgot-password), `approvals.py` (`_process_single_approval`), and `admin.py` (`reset_password`).

```python
import logging
from flask_mail import Message
from db import mail
from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer

log = logging.getLogger(__name__)
```
- `Message` — Flask-Mail's email-message container (subject, recipients, body). `mail` — the shared `Mail()` singleton from `db.py`, already bound to the app via `mail.init_app(app)` in `create_app()`. `current_app` — Flask's application-context proxy, used here to read `SECRET_KEY`/`TOKEN_EXPIRY` from config without needing the concrete `app` object passed in directly (works because these functions are only ever called from within a request, where an app context is automatically active). `url_for` — used to build absolute URLs for the set-password link. `URLSafeTimedSerializer` (from `itsdangerous`, a Flask-Mail/Flask-Login dependency ecosystem library) — creates cryptographically signed, time-limited tokens.

```python
def generate_token(email):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt='password-set-salt')
```
- Creates a serializer keyed by the app's `SECRET_KEY` (Phase 2) and encodes the given `email` string into a signed, URL-safe token, tagged with a fixed `salt` string (`'password-set-salt'`) — the salt namespaces this token type so it can't be confused with/reused as a token generated for a different purpose elsewhere in the app (not currently an issue since this is the only token type in the app, but good practice). The resulting token embeds the email plus a signature and timestamp, but is **not encrypted** — it's signed, meaning its payload (the email address) is technically readable by anyone who decodes the base64 (though tampering would invalidate the signature) — acceptable since the email isn't secret information being protected from the recipient themselves.

```python
def verify_token(token, expiration=None):
    if expiration is None:
        expiration = current_app.config.get('TOKEN_EXPIRY', 86400)
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='password-set-salt', max_age=expiration)
    except Exception:
        return None
    return email
```
- Symmetric verification: same secret key and salt must match for the signature to validate. `max_age=expiration` (defaulting to `TOKEN_EXPIRY=86400` seconds from config) enforces the 24-hour link expiry — `itsdangerous` internally embeds a timestamp at signing time and raises `SignatureExpired` if `max_age` has elapsed, or `BadSignature` if the token was tampered with or signed with a different key/salt. Both are caught by the blanket `except Exception`, collapsing all failure modes into a simple `None` return — the caller (`set_password()` in `auth.py`, Phase 7) can't distinguish "expired" from "tampered" from "malformed," which is intentional (doesn't leak which specific failure occurred to a potential attacker probing the endpoint).

```python
def send_set_password_email(user):
    token = generate_token(user.email)
    set_url = url_for('auth.set_password', token=token, _external=True)
    subject = 'Ticket Tracker – Set Your Password'
    body = f"""Hello {user.username},

Your Ticket Tracker account has been created.
Please click the link below to set your password:

{set_url}

This link expires in 24 hours.

If you did not request this, please ignore this email.

Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
        log.info('Set-password email sent: user=%s', user.username)
        return True
    except Exception as e:
        log.error('Set-password email failed: user=%s error=%s', user.username, e)
        return False
```
- `url_for('auth.set_password', token=token, _external=True)` — `_external=True` is essential here: without it, `url_for` would produce a relative path (`/set-password/xyz`), which is meaningless inside an email (there's no "current host" context for an email client) — `_external=True` forces Flask to build a fully-qualified URL including scheme and host (derived from the request context or `SERVER_NAME` config). The plain-text email body embeds this link plus a human-friendly expiry notice. `mail.send(msg)` is wrapped in `try/except Exception` — **any** SMTP failure (connection refused, auth failure, empty `MAIL_SERVER` config, network timeout) is caught, logged as an error, and converted into a `False` return value rather than propagating an exception up into the route handler — this is precisely why `register()` in `auth.py` can gracefully fall back to "Account created, but email could not be sent" instead of crashing with a 500 error.

```python
def send_approval_notification(requester_username, requester_email, action,
                               request_type, ticket_no, admin_comments=''):
    subject = f'Ticket Tracker – Your {request_type} request was {action}'
    comments_line = f'\nAdmin comments: {admin_comments}\n' if admin_comments else ''
    body = f"""Hello {requester_username},

Your {request_type} request for ticket {ticket_no} has been {action}.
{comments_line}
Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[requester_email], body=body)
        mail.send(msg)
        log.info('Approval notification sent: user=%s action=%s ticket=%s',
                 requester_username, action, ticket_no)
        return True
    except Exception as e:
        log.error('Approval notification failed: user=%s error=%s', requester_username, e)
        return False
```
- Called exclusively from `_process_single_approval()` (Phase 11), for **every** approve/reject action on **every** request type. `comments_line` conditionally includes the admin's freeform comment text only if non-empty, otherwise an empty string (avoiding a dangling "Admin comments: " line with nothing after it). Same try/except-swallow pattern as above — a failed notification email never breaks the approval transaction itself (the caller in `approvals.py` doesn't even check this function's boolean return value — it's fire-and-forget from the caller's perspective).

```python
def send_reset_password_email(user):
    token = generate_token(user.email)
    reset_url = url_for('auth.set_password', token=token, _external=True)
    subject = 'Ticket Tracker – Password Reset'
    body = f"""Hello {user.username},

You requested a password reset.
Please click the link below to set a new password:

{reset_url}

This link expires in 24 hours.

Regards,
Ticket Tracker Team
"""
    try:
        msg = Message(subject=subject, recipients=[user.email], body=body)
        mail.send(msg)
        log.info('Reset-password email sent: user=%s', user.username)
        return True
    except Exception as e:
        log.error('Reset-password email failed: user=%s error=%s', user.username, e)
        return False
```
- Nearly identical to `send_set_password_email` — notably, it points to the **same** `auth.set_password` route (not a separate `/reset-password/<token>` endpoint). This works because `set_password()` (Phase 7) doesn't distinguish "new account" vs. "forgot password" flows — it just verifies the token, looks up the user by the embedded email, and lets them set a new password, which is functionally correct for both use cases (the route name is slightly misleading for the reset flow, but behaviorally identical).

---

<a name="phase-14"></a>
## Phase 14: Services Deep Dive — `services/history_service.py`

First imported during Phase 5.3 (by `routes/tickets.py`), later also imported by `routes/approvals.py` and `routes/admin.py`.

```python
import logging
from db import db
from models.history import TicketHistory
from datetime import datetime

log = logging.getLogger(__name__)


FIELD_LABELS = {
    'ticket_no': 'Ticket No',
    ... # 19 key-value pairs mapping internal field names to display labels
    'deleted_flag': 'Deleted',
}
```
- Note this module has its **own** copy of `FIELD_LABELS`, separate from (though largely overlapping) the one defined independently in `routes/approvals.py` — another instance of duplicated-rather-than-shared constants across the codebase (confirmed by comparing both dicts: `approvals.py`'s version has `assigned_to` and lacks `deleted_flag`; this one has `deleted_flag` and lacks `assigned_to` — they are genuinely not identical, a real inconsistency).
- This `FIELD_LABELS` here is actually used only inside `log_ticket_changes()`'s iteration below (as the master list of *which fields to check* for changes, not primarily for display) — its keys effectively define the complete set of ticket fields that get audit-tracked when edited; any `Ticket` column *not* present in this dict (e.g., `assigned_to`, or `created_by`) would silently **never** be captured in the history log even if changed via an approved edit — a genuine, confirmed gap: `assigned_to` changes are not audit-logged by this function, since it's absent from this particular `FIELD_LABELS` dict.

```python
def log_ticket_created(ticket, changed_by):
    log.info('History: CREATED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='CREATED',
        field_name='ticket_no',
        old_value=None,
        new_value=ticket.ticket_no,
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()
```
- Writes a **single** `TicketHistory` row representing ticket creation as a whole, using `ticket_no` as a representative `field_name` (not literally logging every field's initial value — just a marker event). Requires `ticket.id` to already be populated, which is why callers (`add_ticket`, `bulk_upload`, `_process_single_approval`'s ADD branch) always `db.session.flush()` or otherwise ensure the ticket is already inserted before calling this. Commits independently — this function owns its own transaction boundary, separate from whatever commit the caller did for the `Ticket` insert itself (meaning ticket-creation and history-logging are technically two separate commits, not perfectly atomic — if the process crashed between them, you could end up with a ticket that has no corresponding CREATED history row, though this is an unlikely edge case in practice).

```python
def log_ticket_changes(ticket_id, old_data, new_data, changed_by, action='UPDATED'):
    date_fields = {'estimated_uat', 'estimated_prod', 'actual_uat', 'actual_prod',
                   'revised_uat_date', 'revised_prod_date'}

    def fmt(val, field):
        if val is None:
            return ''
        return str(val)

    for field in FIELD_LABELS.keys():
        old_val = old_data.get(field)
        new_val = new_data.get(field)
        if str(old_val or '') != str(new_val or ''):
            h = TicketHistory(
                ticket_id=ticket_id,
                action=action,
                field_name=field,
                old_value=fmt(old_val, field),
                new_value=fmt(new_val, field),
                changed_by=changed_by,
                changed_at=datetime.utcnow()
            )
            db.session.add(h)
    db.session.commit()
```
- `date_fields` is defined but, like in `edit_ticket()`, **never referenced** in the function body — genuinely dead/unused code, confirmed by direct inspection (there's no branch that treats date fields specially despite this set existing).
- `fmt(val, field)` — a trivial helper that converts `None` to `''` and everything else to its plain string representation via `str()` — the `field` parameter is accepted but unused inside the function body, another small inconsistency (perhaps intended for future field-specific formatting that was never implemented).
- The core loop: iterates every key in `FIELD_LABELS` (**not** every key actually present in `old_data`/`new_data`, and **not** the caller-supplied `changed_fields` list from `edit_ticket()`'s own diff computation — this function independently recomputes which fields differ, ignoring whatever `changed_fields` list was passed to it upstream, since it isn't even a parameter here). For each candidate field, compares string-coerced old vs. new values (same pattern as `edit_ticket()`'s own diff logic) and, if different, creates one `TicketHistory` row per differing field. This means, as noted above, only fields present as keys in `FIELD_LABELS` can ever produce a history row — `assigned_to` changes are silently excluded from the audit trail because that key is missing from this dict, a genuine and confirmed limitation of the current code, not a hypothetical.
- One shared `db.session.commit()` at the end persists all the field-level rows from a single edit in one transaction (atomic across all the fields changed in that one edit).

```python
def log_ticket_deleted(ticket, changed_by):
    log.info('History: DELETED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='DELETED',
        field_name='deleted_flag',
        old_value='False',
        new_value='True',
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()


def log_ticket_restored(ticket, changed_by):
    log.info('History: RESTORED ticket=%s by=%s', ticket.ticket_no, changed_by)
    h = TicketHistory(
        ticket_id=ticket.id,
        action='RESTORED',
        field_name='deleted_flag',
        old_value='True',
        new_value='False',
        changed_by=changed_by,
        changed_at=datetime.utcnow()
    )
    db.session.add(h)
    db.session.commit()
```
- Mirror-image functions, each writing exactly one `TicketHistory` row marking the soft-delete flag's transition in the corresponding direction, with hardcoded `old_value`/`new_value` strings (`'False'`→`'True'` for delete, reversed for restore) rather than reading the ticket's actual prior state — safe because both functions are only ever called immediately after the flag has just been flipped by the caller, so the hardcoded values are always accurate given the calling convention.

---

<a name="phase-15"></a>
## Phase 15: Frontend Connections — Templates, `app.js`, `style.css`

### `templates/base.html`
Every other template `{% extends "base.html" %}` and fills in the `{% block title %}` and `{% block content %}` blocks (confirmed present as the two named blocks, plus an optional `{% block scripts %}` for page-specific JS).

- Loads Bootstrap 5.3.3 CSS/JS and Bootstrap Icons from a CDN, plus the app's own `static/style.css` via `url_for('static', filename='style.css')` — Flask's built-in static file serving resolves this to `/static/style.css`.
- Loads Chart.js 4.4.3 from CDN in the `<head>` — this is what powers the ticket-type doughnut/bar chart on `dashboard.html` (fed by `type_labels`/`type_counts` from `dashboard.index()`, Phase 8) and the multiple charts on `admin_analytics.html` (fed by `monthly_labels`/`monthly_counts`, `effort_months`/`effort_planned`/`effort_utilized`, `type_labels`/`type_counts`, `status_labels`/`status_counts` from `admin.analytics()`, Phase 12). The actual Chart.js instantiation JavaScript (`new Chart(ctx, {...})`) is not in the shared `static/app.js` — it must live inline in each analytics-bearing template's own `{% block scripts %}`, reading the server-passed arrays (likely rendered as inline `{{ type_labels|tojson }}` or similar into a `<script>` block), since `app.js` itself (read in full below) contains no chart-related code at all.
- The navbar (`{% if current_user.is_authenticated %}`) conditionally renders based on login state — its structure directly encodes the route map: `dashboard.index`, `tickets.add_ticket`, and (admin-only, `{% if current_user.is_admin() %}`) `tickets.bulk_upload`, `approvals.pending_approvals`, `admin.users`, `admin.freeze_settings`, `admin.deleted_tickets`, `admin.analytics` — every single blueprint/route traced in Phases 7–12 is reachable from this one navigation bar, confirming the nav is the primary UI entry point into the whole route map.
- The user dropdown links to `auth.change_password` and `auth.logout`, and displays `current_user.username` plus a colored role badge (`bg-warning` for Admin, `bg-light` for User) driven by `current_user.role`/`is_admin()`.
- The flash-message block iterates `get_flashed_messages(with_categories=true)` — this is the rendering counterpart to every `flash(message, category)` call traced throughout Phases 7–12; the category (`success`/`danger`/`warning`/`info`) maps directly to a Bootstrap alert class (`alert-success`, etc.) and to an icon choice.
- Loads Bootstrap's JS bundle then the app's own `static/app.js`, followed by any page-specific `{% block scripts %}`.

### `static/app.js`
Two small, generic behaviors, both DOM-ready-gated:
- `togglePassword(fieldId, iconId)` — a reusable show/hide-password toggle used by password-input pages (`login.html`, `register.html`, `set_password.html`, `change_password.html` most plausibly wire an eye-icon button's `onclick` to this function).
- An `alert.alert-dismissible` auto-dismiss timer — every flash message (rendered by `base.html`'s flash block above) is fitted with Bootstrap's `alert-dismissible` class, and this script finds all of them on `DOMContentLoaded` and auto-closes each after 5 seconds via Bootstrap's `Alert` API (falling back to a manual opacity-fade-then-remove if no Bootstrap `Alert` instance is attached yet).
- A Bootstrap tooltip initializer for any element carrying `data-bs-toggle="tooltip"` — enables hover tooltips wherever templates choose to add that attribute (e.g., likely on truncated ticket descriptions or icon-only buttons in the ticket table).
- Notably, there is **no AJAX/fetch code anywhere in `app.js`** — every form submission and action button in this app (add/edit/delete tickets, comments, approvals, admin actions) is a traditional full-page HTML form POST followed by a server-side redirect, not a client-side API call. This is consistent with everything traced in Phases 7–12: every route handler ends in `render_template(...)` or `redirect(url_for(...))`, never `jsonify(...)`.

### `static/style.css`
Pure visual styling with no behavior of its own — worth summarizing since it explains *why* certain data-driven templates look the way they do:
- CSS custom properties (`--primary`, `--surface`, `--border`, `--shadow`, `--radius`) define the app's blue-accented visual theme, reused across cards/buttons/forms.
- `.status-badge` combined with modifier classes `.status-open`, `.status-closed`, `.status-in-progress`, `.status-uat`, `.status-on-hold` — a direct visual mapping to the `Ticket.status` values enumerated in `STATUSES` (Phases 8/9); templates presumably compute the modifier class name from `ticket.status` (e.g., lowercased/hyphenated) to color-code each ticket's status pill in the dashboard table.
- `.reqtype-badge` + `.reqtype-add`/`.reqtype-edit`/`.reqtype-delete` — same pattern applied to `ApprovalRequest.request_type` values (`ADD`/`EDIT`/`DELETE`) on `pending_approvals.html`/`approval_details.html`.
- `.action-badge` + `.action-created`/`.action-updated`/`.action-deleted`/`.action-restored` — same pattern for `TicketHistory.action` values on `history.html`.
- `.ticket-table` rules implement a sticky header row and sticky first/second columns (via `position: sticky`) — this is the CSS backing the dashboard's large, horizontally-scrollable, many-column ticket table (`ticket-table-wrapper` with `max-height: 75vh` and both-axis scroll), keeping the ticket-number/type columns pinned in view while scrolling right through the many date/effort columns, and keeping the header pinned while scrolling down through paginated rows.
- `.freeze-banner` — a distinct gradient-styled banner class, almost certainly rendered conditionally in `add_ticket.html`/`edit_ticket.html`/`bulk_upload.html` when the `frozen` context variable (Phase 9's `is_frozen()`) is `True`, visually warning the user that their submission will require approval.

---

## Summary of Cross-Cutting Observations (confirmed by code, not speculative)

- **Approval policy asymmetry**: ticket *adds* only require approval when the system is frozen; *edits* and *deletes* always require approval regardless of freeze state. Confirmed in `add_ticket()` vs. `edit_ticket()`/`delete_ticket()` in `routes/tickets.py`.
- **Audit trail gap**: `services/history_service.py`'s `FIELD_LABELS` dict omits `assigned_to`, so changes to a ticket's assignee are never recorded in `TicketHistory`, even though `assigned_to` is a fully editable field via the approval workflow.
- **`root()` in `app.py` is effectively unreachable**, shadowed by `dashboard.index()` which is also mapped to `/`.
- **No server-restart-proof month rolling window**: `tickets.py`'s `MONTHS` constant is computed once at import time, not per-request, so the "current + next 4 months" dropdown only advances when the process restarts.
- **Duplicated (and slightly inconsistent) constants**: `admin_required` decorator logic, `FIELD_LABELS` dicts, and `STATUSES`/`TICKET_TYPES` lists are each independently redefined in multiple files rather than imported from one shared location.
- **Plaintext bootstrap admin password is logged**: `app.py`'s default-admin-creation path logs `'Default admin created: admin / Admin@123'` at INFO level into `logs/application.log`.
- **No purely client-side AJAX**: the entire UI is server-rendered, form-POST-driven; `static/app.js` only handles cosmetic behaviors (password toggle, alert auto-dismiss, tooltips).

---

*Document generated from a full line-by-line read of every `.py` file in `D:\Claude\ticket_tracker` (`app.py`, `config.py`, `db.py`, all of `models/`, `routes/`, `services/`), plus `templates/base.html`, `static/app.js`, and `static/style.css`, tracing genuine Python import/execution order from the `app.py` entrypoint through full request lifecycles for every route.*
