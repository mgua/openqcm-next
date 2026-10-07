import csv
import io
import os
import secrets
import sqlite3
from ipaddress import ip_address
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "app.db")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_COLUMNS = ["Date", "Time", "Relative_time", "Temperature", "Resonance_Frequency", "Dissipation"]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret-key-in-production"),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            rows_count INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            date TEXT,
            time TEXT,
            relative_time REAL,
            temperature REAL,
            resonance_frequency REAL,
            dissipation REAL,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        );
        """
    )
    admin = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if admin is None:
        db.execute(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,?,?)",
            ("admin", generate_password_hash("admin123!"), "admin", datetime.utcnow().isoformat()),
        )
    db.commit()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token()}


def require_csrf():
    if request.form.get("csrf_token") != session.get("csrf_token"):
        abort(400, description="Token CSRF non valido.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def load_user():
    g.user = None
    if session.get("user_id"):
        g.user = get_db().execute(
            "SELECT id, username, role FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Credenziali non valide.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    datasets = get_db().execute(
        "SELECT * FROM datasets ORDER BY imported_at DESC, id DESC"
    ).fetchall()
    return render_template("dashboard.html", datasets=datasets)


@app.route("/compare")
@login_required
def compare_datasets():
    raw_ids = request.args.getlist("id")
    if len(raw_ids) == 1 and "," in raw_ids[0]:
        raw_ids = [x.strip() for x in raw_ids[0].split(",") if x.strip()]
    try:
        ids = list(dict.fromkeys(int(x) for x in raw_ids))
    except ValueError:
        abort(400, description="Identificativo dataset non valido.")
    if not ids or len(ids) > 3:
        abort(400, description="Seleziona da 1 a 3 dataset.")
    placeholders = ",".join("?" for _ in ids)
    db = get_db()
    datasets = db.execute(
        f"SELECT * FROM datasets WHERE id IN ({placeholders})", ids
    ).fetchall()
    by_id = {row["id"]: row for row in datasets}
    if len(by_id) != len(ids):
        abort(404)
    datasets = [dict(by_id[i]) for i in ids]
    data = {}
    for dataset in datasets:
        rows = db.execute(
            "SELECT relative_time,temperature,resonance_frequency,dissipation "
            "FROM measurements WHERE dataset_id = ? ORDER BY id",
            (dataset["id"],),
        ).fetchall()
        data[str(dataset["id"])] = [dict(row) for row in rows]
    return render_template("compare.html", datasets=datasets, data=data)


@app.route("/dataset/<int:dataset_id>")
@login_required
def dataset_detail(dataset_id):
    db = get_db()
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if dataset is None:
        abort(404)
    rows = db.execute(
        "SELECT date,time,relative_time,temperature,resonance_frequency,dissipation "
        "FROM measurements WHERE dataset_id = ? ORDER BY id",
        (dataset_id,),
    ).fetchall()
    data = [dict(row) for row in rows]
    return render_template("dataset.html", dataset=dataset, data=data)


def parse_float(value, column, line_no):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Valore non numerico nella colonna {column}, riga {line_no}.") from exc


def parse_csv(file_storage):
    raw = file_storage.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Il file supera il limite di 10 MB.")
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Encoding CSV non supportato. Usa UTF-8, UTF-8 BOM o CP1252.")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("Il CSV non contiene un'intestazione.")
    reader.fieldnames = [h.strip() if h else h for h in reader.fieldnames]
    missing = [c for c in ALLOWED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise ValueError("Colonne mancanti: " + ", ".join(missing))

    rows = []
    for line_no, row in enumerate(reader, start=2):
        if not any((str(v).strip() if v is not None else "") for v in row.values()):
            continue
        rows.append(
            {
                "date": (row.get("Date") or "").strip(),
                "time": (row.get("Time") or "").strip(),
                "relative_time": parse_float(row.get("Relative_time"), "Relative_time", line_no),
                "temperature": parse_float(row.get("Temperature"), "Temperature", line_no),
                "resonance_frequency": parse_float(row.get("Resonance_Frequency"), "Resonance_Frequency", line_no),
                "dissipation": parse_float(row.get("Dissipation"), "Dissipation", line_no),
            }
        )
    if not rows:
        raise ValueError("Il CSV non contiene righe di dati.")
    return rows


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        require_csrf()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not user or not check_password_hash(user["password_hash"], current_password):
            flash("La password attuale non è corretta.", "error")
        elif len(new_password) < 8:
            flash("La nuova password deve contenere almeno 8 caratteri.", "error")
        elif new_password != confirm_password:
            flash("Le nuove password non coincidono.", "error")
        elif check_password_hash(user["password_hash"], new_password):
            flash("La nuova password deve essere diversa da quella attuale.", "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new_password), session["user_id"]))
            db.commit()
            flash("Password modificata con successo.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")


@app.route("/admin/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_dataset():
    if request.method == "POST":
        require_csrf()
        uploaded = request.files.get("csv_file")
        name = request.form.get("name", "").strip()
        if not uploaded or not uploaded.filename:
            flash("Seleziona un file CSV.", "error")
            return redirect(url_for("import_dataset"))
        if not uploaded.filename.lower().endswith(".csv"):
            flash("Sono ammessi solo file CSV.", "error")
            return redirect(url_for("import_dataset"))
        if not name:
            name = os.path.splitext(os.path.basename(uploaded.filename))[0]
        try:
            rows = parse_csv(uploaded)
            db = get_db()
            cur = db.execute(
                "INSERT INTO datasets(name,original_filename,imported_at,rows_count) VALUES (?,?,?,?)",
                (name, os.path.basename(uploaded.filename), datetime.utcnow().isoformat(), len(rows)),
            )
            dataset_id = cur.lastrowid
            db.executemany(
                "INSERT INTO measurements(dataset_id,date,time,relative_time,temperature,resonance_frequency,dissipation) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        dataset_id,
                        r["date"], r["time"], r["relative_time"], r["temperature"],
                        r["resonance_frequency"], r["dissipation"],
                    )
                    for r in rows
                ],
            )
            db.commit()
            flash(f"Importazione completata: {len(rows)} misure.", "success")
            return redirect(url_for("dataset_detail", dataset_id=dataset_id))
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception:
            get_db().rollback()
            flash("Errore durante l'importazione del CSV.", "error")
    return render_template("import.html")


@app.post("/admin/dataset/<int:dataset_id>/delete")
@login_required
@admin_required
def delete_dataset(dataset_id):
    require_csrf()
    db = get_db()
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if dataset is None:
        abort(404)
    db.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    db.commit()
    flash(f"Dataset '{dataset['name']}' eliminato.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def users():
    db = get_db()
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        if not username or len(password) < 8 or role not in ("admin", "user"):
            flash("Username obbligatorio, password di almeno 8 caratteri e ruolo valido.", "error")
        else:
            try:
                db.execute(
                    "INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,?,?)",
                    (username, generate_password_hash(password), role, datetime.utcnow().isoformat()),
                )
                db.commit()
                flash(f"Utente '{username}' creato.", "success")
            except sqlite3.IntegrityError:
                flash("Username già esistente.", "error")
        return redirect(url_for("users"))
    user_rows = db.execute("SELECT id,username,role,created_at FROM users ORDER BY username").fetchall()
    return render_template("users.html", users=user_rows)


@app.post("/admin/users/<int:user_id>/delete")
@login_required
@admin_required
def delete_user(user_id):
    require_csrf()
    if user_id == session.get("user_id"):
        flash("Non puoi eliminare l'utente con cui sei autenticato.", "error")
        return redirect(url_for("users"))
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash("Utente eliminato.", "success")
    return redirect(url_for("users"))


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="Non hai i permessi necessari."), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="Risorsa non trovata."), 404


@app.errorhandler(413)
def too_large(error):
    return render_template("error.html", code=413, message="Il file è troppo grande (massimo 10 MB)."), 413


def ensure_self_signed_certificate():
    cert_dir = os.path.join(BASE_DIR, "certs")
    cert_path = os.environ.get("SSL_CERT_FILE", os.path.join(cert_dir, "localhost.crt"))
    key_path = os.environ.get("SSL_KEY_FILE", os.path.join(cert_dir, "localhost.key"))

    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    if os.environ.get("HTTPS_GENERATE_CERT", "1") != "1":
        raise RuntimeError(
            "Certificato HTTPS non trovato. Imposta SSL_CERT_FILE e SSL_KEY_FILE "
            "oppure abilita HTTPS_GENERATE_CERT=1."
        )

    os.makedirs(os.path.dirname(cert_path), exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "openQCM Next Viewer"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(ip_address("127.0.0.1")),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow() - timedelta(minutes=1))
        .not_valid_after(datetime.utcnow() + timedelta(days=825))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


with app.app_context():
    init_db()

if __name__ == "__main__":
    https_enabled = os.environ.get("HTTPS_ENABLED", "1") == "1"
    if https_enabled:
        cert_file, key_file = ensure_self_signed_certificate()
        print("openQCM Next Viewer: https://127.0.0.1:5443")
        print("Certificato autofirmato:", cert_file)
        app.run(host="127.0.0.1", port=5443, ssl_context=(cert_file, key_file), debug=False)
    else:
        print("openQCM Next Viewer: http://127.0.0.1:5000")
        app.run(host="127.0.0.1", port=5000, debug=False)
