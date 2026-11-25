import os, sqlite3, secrets, json, zipfile, io
from datetime import datetime
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_from_directory, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "instance"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", ROOT / "uploads"))
VIDEO_DIR = UPLOAD_DIR / "videos"
UPDATE_DIR = UPLOAD_DIR / "updates"
for folder in (DATA_DIR, VIDEO_DIR, UPDATE_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.jinja_env.globals["str"] = str
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=1024 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
)
DB_PATH = DATA_DIR / "electromecanica.db"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}
UPDATE_EXTENSIONS = {".zip", ".txt", ".md", ".json", ".pdf"}
WHATSAPP_NUMBER = "5493875077769"
WHATSAPP_MESSAGE = "¡Hola! Estuve visitando la plataforma Electromecánica Mauro y me gustaría obtener más información sobre los cursos y las clases disponibles."

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','admin','student'))
        );
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, level TEXT NOT NULL,
            description TEXT DEFAULT '', position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            title TEXT NOT NULL, description TEXT DEFAULT '', video_filename TEXT DEFAULT '',
            video_url TEXT DEFAULT '', position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            prompt TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, c TEXT NOT NULL, d TEXT NOT NULL,
            correct TEXT NOT NULL, explanation TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            score INTEGER NOT NULL, total INTEGER NOT NULL, percentage REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
            completed_at TEXT NOT NULL, PRIMARY KEY(user_id, lesson_id)
        );
        CREATE TABLE IF NOT EXISTS updates_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, uploaded_by TEXT NOT NULL,
            created_at TEXT NOT NULL, note TEXT DEFAULT ''
        );
        """)
        count = con.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
        if count == 0:
            starter = [
                ("Capítulo 1: Inicial", "Inicial", "Fundamentos, herramientas, seguridad y conceptos básicos.", 1),
                ("Capítulo 2: Primario", "Primario", "Conocimientos intermedios y circuitos eléctricos.", 2),
                ("Capítulo 3: Secundario", "Secundario", "Contenidos avanzados de electromecánica y diagnóstico.", 3),
            ]
            con.executemany("INSERT INTO chapters(title,level,description,position) VALUES(?,?,?,?)", starter)
        # Create accounts only when credentials are explicitly configured in Render environment.
        for prefix, role in (("OWNER", "owner"), ("ADMIN2", "admin")):
            username, password = os.environ.get(prefix + "_USERNAME"), os.environ.get(prefix + "_PASSWORD")
            if username and password:
                con.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)",
                            (username.strip(), generate_password_hash(password), role))

init_db()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("role") not in ("owner", "admin"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def owner_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("role") != "owner":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

@app.context_processor
def common():
    return {"current_user": session.get("username"), "current_role": session.get("role"),
            "wa_url": "https://wa.me/" + WHATSAPP_NUMBER + "?text=" + quote(WHATSAPP_MESSAGE)}

@app.route("/")
def index():
    with db() as con:
        chapters = con.execute("SELECT c.*, COUNT(l.id) lesson_count FROM chapters c LEFT JOIN lessons l ON l.chapter_id=c.id GROUP BY c.id ORDER BY c.position").fetchall()
        latest = con.execute("SELECT title,description,created_at FROM lessons ORDER BY id DESC LIMIT 3").fetchall()
    return render_template("index.html", chapters=chapters, latest=latest)

@app.route("/capitulo/<int:chapter_id>")
def chapter(chapter_id):
    with db() as con:
        ch = con.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        if not ch: abort(404)
        lessons = con.execute("SELECT * FROM lessons WHERE chapter_id=? ORDER BY position,id", (chapter_id,)).fetchall()
        questions_count = con.execute("SELECT COUNT(*) FROM questions WHERE chapter_id=?", (chapter_id,)).fetchone()[0]
    completed = set()
    if session.get("user_id"):
        with db() as con:
            completed = {r["lesson_id"] for r in con.execute("SELECT lesson_id FROM progress WHERE user_id=?", (session["user_id"],))}
    return render_template("chapter.html", chapter=ch, lessons=lessons, completed=completed, questions_count=questions_count)

@app.route("/video/<path:filename>")
@login_required
def video(filename):
    return send_from_directory(VIDEO_DIR, filename)

@app.post("/leccion/<int:lesson_id>/completar")
@login_required
def complete_lesson(lesson_id):
    with db() as con:
        exists = con.execute("SELECT id FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if not exists: abort(404)
        con.execute("INSERT OR IGNORE INTO progress(user_id,lesson_id,completed_at) VALUES(?,?,?)",
                    (session["user_id"], lesson_id, datetime.utcnow().isoformat()))
    flash("¡Progreso guardado!", "success")
    return redirect(request.referrer or url_for("index"))

@app.route("/evaluacion/<int:chapter_id>", methods=["GET", "POST"])
@login_required
def quiz(chapter_id):
    with db() as con:
        ch = con.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        if not ch: abort(404)
        questions = con.execute("SELECT * FROM questions WHERE chapter_id=? ORDER BY id", (chapter_id,)).fetchall()
        previous = con.execute("SELECT * FROM results WHERE user_id=? AND chapter_id=? ORDER BY id DESC LIMIT 1",
                               (session["user_id"], chapter_id)).fetchone()
        if request.method == "POST":
            if not questions:
                flash("Este capítulo todavía no tiene preguntas.", "warning")
                return redirect(url_for("chapter", chapter_id=chapter_id))
            score = sum(1 for q in questions if request.form.get(str(q["id"])) == q["correct"])
            total = len(questions)
            pct = round(score / total * 100, 1)
            con.execute("INSERT INTO results(user_id,chapter_id,score,total,percentage,created_at) VALUES(?,?,?,?,?,?)",
                        (session["user_id"], chapter_id, score, total, pct, datetime.utcnow().isoformat()))
            return render_template("quiz_result.html", chapter=ch, questions=questions, score=score, total=total, percentage=pct, answers=request.form)
    return render_template("quiz.html", chapter=ch, questions=questions, previous=previous)

@app.route("/mis-resultados")
@login_required
def my_results():
    with db() as con:
        results = con.execute("""SELECT r.*,c.title FROM results r JOIN chapters c ON c.id=r.chapter_id
                               WHERE r.user_id=? ORDER BY r.id DESC""", (session["user_id"],)).fetchall()
        total_lessons = con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM progress WHERE user_id=?", (session["user_id"],)).fetchone()[0]
    return render_template("results.html", results=results, total_lessons=total_lessons, done=done)

@app.route("/registro", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username, password = request.form.get("username","").strip(), request.form.get("password","")
        if len(username) < 3 or len(password) < 8:
            flash("El usuario debe tener al menos 3 caracteres y la contraseña 8.", "error")
        else:
            try:
                with db() as con:
                    con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                                (username, generate_password_hash(password), "student"))
                flash("Cuenta creada. Ya podés iniciar sesión.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Ese nombre de usuario ya existe.", "error")
    return render_template("register.html")

@app.route("/ingresar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username, password = request.form.get("username","").strip(), request.form.get("password","")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            return redirect(request.args.get("next") or url_for("index"))
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")

@app.route("/salir")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@login_required
@admin_required
def admin():
    with db() as con:
        chapters = con.execute("SELECT * FROM chapters ORDER BY position").fetchall()
        lessons = con.execute("SELECT l.*,c.title chapter_title FROM lessons l JOIN chapters c ON c.id=l.chapter_id ORDER BY c.position,l.position").fetchall()
        users = con.execute("SELECT id,username,role FROM users ORDER BY role,username").fetchall()
    return render_template("admin.html", chapters=chapters, lessons=lessons, users=users)

@app.post("/admin/capitulo")
@login_required
@admin_required
def add_chapter():
    title, level, description = (request.form.get(x,"").strip() for x in ("title","level","description"))
    if title and level:
        with db() as con:
            con.execute("INSERT INTO chapters(title,level,description,position) VALUES(?,?,?,?)",
                        (title, level, description, con.execute("SELECT COALESCE(MAX(position),0)+1 FROM chapters").fetchone()[0]))
        flash("Capítulo creado.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/capitulo/<int:cid>/editar")
@login_required
@admin_required
def edit_chapter(cid):
    with db() as con:
        con.execute("UPDATE chapters SET title=?,level=?,description=? WHERE id=?",
                    (request.form.get("title","").strip(), request.form.get("level","").strip(),
                     request.form.get("description","").strip(), cid))
    flash("Capítulo actualizado.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/capitulo/<int:cid>/eliminar")
@login_required
@owner_required
def delete_chapter(cid):
    with db() as con:
        con.execute("DELETE FROM chapters WHERE id=?", (cid,))
    flash("Capítulo eliminado.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/leccion")
@login_required
@admin_required
def add_lesson():
    title = request.form.get("title","").strip()
    chapter_id = request.form.get("chapter_id")
    description = request.form.get("description","").strip()
    video_url = request.form.get("video_url","").strip()
    file = request.files.get("video")
    filename = ""
    if file and file.filename:
        safe = secure_filename(file.filename)
        if Path(safe).suffix.lower() not in VIDEO_EXTENSIONS:
            flash("Formato de video no permitido. Usá MP4, WEBM, OGG o MOV.", "error")
            return redirect(url_for("admin"))
        filename = secrets.token_hex(8) + "_" + safe
        file.save(VIDEO_DIR / filename)
    if title and chapter_id:
        with db() as con:
            con.execute("INSERT INTO lessons(chapter_id,title,description,video_filename,video_url,position,created_at) VALUES(?,?,?,?,?,?,?)",
                        (chapter_id,title,description,filename,video_url,
                         con.execute("SELECT COALESCE(MAX(position),0)+1 FROM lessons WHERE chapter_id=?",(chapter_id,)).fetchone()[0],
                         datetime.utcnow().isoformat()))
        flash("Clase creada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/leccion/<int:lid>/eliminar")
@login_required
@admin_required
def delete_lesson(lid):
    with db() as con:
        row = con.execute("SELECT video_filename FROM lessons WHERE id=?", (lid,)).fetchone()
        if row and row["video_filename"]:
            (VIDEO_DIR / row["video_filename"]).unlink(missing_ok=True)
        con.execute("DELETE FROM lessons WHERE id=?", (lid,))
    flash("Clase eliminada.", "success")
    return redirect(url_for("admin"))

@app.post("/admin/pregunta")
@login_required
@admin_required
def add_question():
    fields = [request.form.get(k,"").strip() for k in ("chapter_id","prompt","a","b","c","d","correct","explanation")]
    if all(fields[:7]) and fields[6] in ("a","b","c","d"):
        with db() as con:
            con.execute("INSERT INTO questions(chapter_id,prompt,a,b,c,d,correct,explanation) VALUES(?,?,?,?,?,?,?,?)", fields)
        flash("Pregunta agregada.", "success")
    else:
        flash("Completá la pregunta y sus cuatro opciones.", "error")
    return redirect(url_for("admin"))

@app.post("/admin/pregunta/<int:qid>/eliminar")
@login_required
@admin_required
def delete_question(qid):
    with db() as con:
        con.execute("DELETE FROM questions WHERE id=?", (qid,))
    flash("Pregunta eliminada.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/actualizar", methods=["GET","POST"])
@login_required
@owner_required
def platform_update():
    if request.method == "POST":
        f = request.files.get("update_file")
        if not f or not f.filename:
            flash("Elegí un archivo primero.", "error")
        else:
            name = secure_filename(f.filename)
            ext = Path(name).suffix.lower()
            if ext not in UPDATE_EXTENSIONS:
                flash("Tipo no permitido. Se aceptan ZIP, TXT, MD, JSON y PDF. No se ejecutan archivos.", "error")
            else:
                stored = secrets.token_hex(6) + "_" + name
                f.save(UPDATE_DIR / stored)
                with db() as con:
                    con.execute("INSERT INTO updates_log(filename,uploaded_by,created_at,note) VALUES(?,?,?,?)",
                                (name, session["username"], datetime.utcnow().isoformat(), "Archivo recibido para revisión; no aplicado automáticamente."))
                flash("Archivo recibido y guardado para revisión. No se ejecutó ni modificó el sitio automáticamente.", "success")
        return redirect(url_for("platform_update"))
    with db() as con:
        logs = con.execute("SELECT * FROM updates_log ORDER BY id DESC").fetchall()
    return render_template("updates.html", logs=logs)

@app.route("/admin/backup")
@login_required
@owner_required
def backup():
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
        if DB_PATH.exists(): z.write(DB_PATH, "electromecanica.db")
        for f in VIDEO_DIR.iterdir():
            if f.is_file(): z.write(f, "videos/" + f.name)
    memory.seek(0)
    return send_file(memory, as_attachment=True, download_name="respaldo_electromecanica.zip", mimetype="application/zip")

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="No tenés permisos para acceder a esta sección."), 403

@app.errorhandler(404)
def missing(_):
    return render_template("error.html", code=404, message="No encontramos esa página."), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
