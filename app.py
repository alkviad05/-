"""
Portfolio Flask App — сайт-визитка с SQLite, авторизацией, портфолио и формой обратной связи.
ORM-слой реализован через собственный легковесный класс поверх sqlite3 (SQLAlchemy недоступен в окружении).
"""

import sqlite3
import os
import re
from functools import wraps
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, g, abort)

# ──────────────────────────────────────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-prod")

DATABASE = os.path.join(app.instance_path, "portfolio.db")
os.makedirs(app.instance_path, exist_ok=True)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = generate_password_hash(
    os.environ.get("ADMIN_PASSWORD", "admin123")
)

# ──────────────────────────────────────────────────────────────────────────────
# Database helpers (lightweight ORM-style layer over sqlite3)
# ──────────────────────────────────────────────────────────────────────────────

def get_db():
    """Return a per-request DB connection (stored on Flask's g object)."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables and seed initial data if the DB is fresh."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL,
            tech        TEXT,
            url         TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            email      TEXT    NOT NULL,
            body       TEXT    NOT NULL,
            is_read    INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.commit()

    # Seed sample projects if table is empty
    count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if count == 0:
        sample_projects = [
            ("E-Commerce Platform",
             "Полнофункциональный интернет-магазин с корзиной, оплатой Stripe "
             "и панелью администратора. REST API на FastAPI, фронтенд на React.",
             "Python · FastAPI · React · PostgreSQL · Stripe",
             "https://github.com"),
            ("Real-Time Chat App",
             "Мессенджер с комнатами, WebSocket-уведомлениями и историей сообщений. "
             "Поддерживает markdown-форматирование и вложения.",
             "Node.js · Socket.IO · MongoDB · Vue.js",
             "https://github.com"),
            ("ML Image Classifier",
             "Веб-сервис для классификации изображений на основе EfficientNet. "
             "Точность 94% на ImageNet. Docker-контейнер, Kubernetes-деплой.",
             "Python · PyTorch · FastAPI · Docker",
             "https://github.com"),
            ("DevOps Dashboard",
             "Дашборд мониторинга CI/CD-пайплайнов с алертами в Telegram, "
             "Grafana-метриками и логами из Loki.",
             "Go · Prometheus · Grafana · Loki",
             "https://github.com"),
            ("Portfolio CMS",
             "Headless CMS для управления контентом сайта-визитки. "
             "GraphQL API, авторизация через JWT, публикация в один клик.",
             "Python · Flask · GraphQL · SQLite",
             "https://github.com"),
        ]
        db.executemany(
            "INSERT INTO projects (title, description, tech, url) VALUES (?,?,?,?)",
            sample_projects,
        )
        db.commit()


# Initialise DB on first request
with app.app_context():
    init_db()

# ──────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Необходимо войти в систему.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_contact(name, email, body):
    errors = []
    if not name or len(name.strip()) < 2:
        errors.append("Имя должно содержать не менее 2 символов.")
    if not email or not EMAIL_RE.match(email.strip()):
        errors.append("Введите корректный e-mail.")
    if not body or len(body.strip()) < 10:
        errors.append("Сообщение должно содержать не менее 10 символов.")
    return errors


def validate_project(title, description):
    errors = []
    if not title or len(title.strip()) < 2:
        errors.append("Название должно содержать не менее 2 символов.")
    if not description or len(description.strip()) < 10:
        errors.append("Описание должно содержать не менее 10 символов.")
    return errors

# ──────────────────────────────────────────────────────────────────────────────
# Context processors
# ──────────────────────────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    unread = 0
    if session.get("logged_in"):
        try:
            unread = get_db().execute(
                "SELECT COUNT(*) FROM messages WHERE is_read=0"
            ).fetchone()[0]
        except Exception:
            pass
    return dict(current_year=datetime.now().year, unread_count=unread)

# ──────────────────────────────────────────────────────────────────────────────
# Public routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/portfolio")
def portfolio():
    projects = get_db().execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return render_template("portfolio.html", projects=projects)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        body  = request.form.get("message", "").strip()

        errors = validate_contact(name, email, body)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("contact.html",
                                   form={"name": name, "email": email, "message": body})

        get_db().execute(
            "INSERT INTO messages (name, email, body) VALUES (?,?,?)",
            (name, email, body),
        )
        get_db().commit()
        flash("Спасибо! Ваше сообщение отправлено.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", form={})

# ──────────────────────────────────────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            session["username"] = username
            flash("Добро пожаловать!", "success")
            next_url = request.args.get("next") or url_for("admin_dashboard")
            return redirect(next_url)
        else:
            flash("Неверный логин или пароль.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────────────────────
# Admin routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    projects_count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    messages_count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    unread_count   = db.execute("SELECT COUNT(*) FROM messages WHERE is_read=0").fetchone()[0]
    recent_msgs    = db.execute(
        "SELECT * FROM messages ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    return render_template("admin/dashboard.html",
                           projects_count=projects_count,
                           messages_count=messages_count,
                           unread_count=unread_count,
                           recent_msgs=recent_msgs)


@app.route("/admin/projects")
@login_required
def admin_projects():
    projects = get_db().execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return render_template("admin/projects.html", projects=projects)


@app.route("/admin/projects/new", methods=["GET", "POST"])
@login_required
def admin_project_new():
    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        tech        = request.form.get("tech", "").strip()
        url         = request.form.get("url", "").strip()

        errors = validate_project(title, description)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/project_form.html",
                                   project=request.form, action="new")

        get_db().execute(
            "INSERT INTO projects (title, description, tech, url) VALUES (?,?,?,?)",
            (title, description, tech, url),
        )
        get_db().commit()
        flash("Проект добавлен.", "success")
        return redirect(url_for("admin_projects"))

    return render_template("admin/project_form.html", project={}, action="new")


@app.route("/admin/projects/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def admin_project_edit(pid):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if project is None:
        abort(404)

    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        tech        = request.form.get("tech", "").strip()
        url         = request.form.get("url", "").strip()

        errors = validate_project(title, description)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/project_form.html",
                                   project=request.form, action="edit", pid=pid)

        db.execute(
            "UPDATE projects SET title=?, description=?, tech=?, url=? WHERE id=?",
            (title, description, tech, url, pid),
        )
        db.commit()
        flash("Проект обновлён.", "success")
        return redirect(url_for("admin_projects"))

    return render_template("admin/project_form.html",
                           project=project, action="edit", pid=pid)


@app.route("/admin/projects/<int:pid>/delete", methods=["POST"])
@login_required
def admin_project_delete(pid):
    get_db().execute("DELETE FROM projects WHERE id=?", (pid,))
    get_db().commit()
    flash("Проект удалён.", "info")
    return redirect(url_for("admin_projects"))


@app.route("/admin/messages")
@login_required
def admin_messages():
    messages = get_db().execute(
        "SELECT * FROM messages ORDER BY created_at DESC"
    ).fetchall()
    # Mark all as read
    get_db().execute("UPDATE messages SET is_read=1")
    get_db().commit()
    return render_template("admin/messages.html", messages=messages)


@app.route("/admin/messages/<int:mid>/delete", methods=["POST"])
@login_required
def admin_message_delete(mid):
    get_db().execute("DELETE FROM messages WHERE id=?", (mid,))
    get_db().commit()
    flash("Сообщение удалено.", "info")
    return redirect(url_for("admin_messages"))

# ──────────────────────────────────────────────────────────────────────────────
# Error handlers
# ──────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403


if __name__ == "__main__":
    app.run(debug=True, port=5000)
