"""Four-party renovation collaboration, with transactional shared state."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

from flask import Flask, g, jsonify, redirect, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

import domain as rules
from analysis_service import analyze, review_evidence, analyze_site_note, translate_project_text
from demo_case import PEOPLE, TITLE, populate, prepare_refund
import schedule
from photo_review import TASK_STANDARDS, ANGLES, CONTENT, inspect_photo

ROOT = Path(__file__).resolve().parent


def create_app(data_dir=None, demo_access=False):
    app = Flask(__name__, static_folder='static')
    public_demo_host = os.getenv('TASKFLOW_PUBLIC_DEMO_HOST', '')
    if public_demo_host:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    elif os.getenv('TASKFLOW_TRUST_PROXY') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.json.ensure_ascii = False
    app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024, MAX_FORM_PARTS=12)
    folder = Path(data_dir or os.getenv('TASKFLOW_DATA_DIR', str(ROOT / 'instance')))
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / 'taskflow.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            role TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS members (
            project_id TEXT NOT NULL REFERENCES projects(id), user_id TEXT NOT NULL REFERENCES users(id),
            role TEXT NOT NULL, PRIMARY KEY(project_id, user_id));
        CREATE TABLE IF NOT EXISTS invitations (
            token_hash TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            role TEXT NOT NULL, expires REAL NOT NULL, used_by TEXT);
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), change_id TEXT NOT NULL,
            version INTEGER NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL,
            name TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL,
            uploaded_by TEXT NOT NULL REFERENCES users(id), at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_limits (ip TEXT PRIMARY KEY, since REAL NOT NULL, attempts INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS demo_profiles (
            browser_hash TEXT NOT NULL, role TEXT NOT NULL,
            user_id TEXT UNIQUE NOT NULL REFERENCES users(id),
            PRIMARY KEY (browser_hash, role));
        CREATE TABLE IF NOT EXISTS photo_reviews (
            file_id TEXT PRIMARY KEY REFERENCES files(id), task_id TEXT NOT NULL, report TEXT NOT NULL);
        ''')
    connection.close()

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(database, timeout=10, isolation_level=None)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @contextmanager
    def transaction():
        connection = db()
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @app.teardown_appcontext
    def close_db(_error):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def payload():
        data = request.get_json(silent=True)
        rules.check(isinstance(data, dict), '请提交 JSON 对象。')
        return data

    @app.before_request
    def authenticate():
        if public_demo_host:
            rules.check(request.host == public_demo_host and request.is_secure,
                        '请使用展台的 HTTPS 链接。',403)
            rules.check(request.path not in ('/api/register','/api/login','/api/join')
                        and not request.path.endswith('/invitations'), '展台使用独立演示账号。',403)
        if not request.path.startswith('/api/'):
            return
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            rules.check(not origin or origin == request.host_url.rstrip('/'), '请求来源不匹配。', 403)
        if request.path in ('/api/register', '/api/login', '/api/health', '/api/demo-access', '/api/demo-login'):
            return
        token = request.cookies.get('taskflow_session', '')
        row = db().execute('SELECT u.id,u.name,u.username,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                           (token_hash(token), time.time())).fetchone()
        rules.check(row is not None, '请先登录。', 401)
        g.user = dict(row)
        g.csrf = g.user.pop('csrf')
        if request.method not in ('GET', 'HEAD'):
            rules.check(secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), g.csrf), '登录状态已变化，请刷新页面。', 403)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        # Only the local, standalone collaboration illustration may be framed.
        # Swarm creates a shadow-root stylesheet; allow its inline styles here only.
        if request.path == '/static/collaboration-scene.html':
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "connect-src 'none'; img-src 'self' data:; object-src 'none'; "
                "frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(rules.Problem)
    def domain_error(error):
        return jsonify(error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error='文件或请求过大。' if error.code == 413 else error.description), error.code

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        if app.config['TESTING']:
            raise error
        app.logger.error('Database operation failed: %s', type(error).__name__)
        return jsonify(error='数据暂时繁忙，请重试。'), 503

    @app.get('/')
    def index():
        if public_demo_host and request.args.get('show') == '1':
            return redirect('/')
        return app.send_static_file('index.html')

    @app.get('/api/health')
    def health():
        return jsonify(ok=True)

    def auth_rate_limit():
        ip = request.remote_addr or 'unknown'
        with transaction() as connection:
            row = connection.execute('SELECT * FROM auth_limits WHERE ip=?', (ip,)).fetchone()
            if row and row['since'] > time.time() - 900:
                rules.check(row['attempts'] < 60, '尝试次数较多，请稍后再试。', 429)
                connection.execute('UPDATE auth_limits SET attempts=attempts+1 WHERE ip=?', (ip,))
            else:
                connection.execute('INSERT OR REPLACE INTO auth_limits VALUES(?,?,?)', (ip, time.time(), 1))

    def login_response(user, **extra):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with transaction() as connection:
            connection.execute('DELETE FROM sessions WHERE expires<? OR token_hash=?', (time.time(), token_hash(request.cookies.get('taskflow_session', ''))))
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash(token), user['id'], csrf, time.time() + 86400 * 7))
        response = jsonify(user={k: user[k] for k in ('id', 'username', 'name', 'role')}, csrf=csrf, **extra)
        response.set_cookie('taskflow_session', token, max_age=86400 * 7, httponly=True, samesite='Lax',
                            secure=os.getenv('TASKFLOW_SECURE_COOKIE') == '1' or request.is_secure)
        return response

    def demo_available():
        if public_demo_host:
            return demo_access and request.host == public_demo_host and request.is_secure
        return (demo_access and request.remote_addr in ('127.0.0.1', '::1')
                and request.host.partition(':')[0] in ('127.0.0.1', 'localhost'))

    def demo_project_id(actor_id):
        row = db().execute(
            """SELECT p.id FROM projects p JOIN members m ON m.project_id=p.id
               WHERE m.user_id=? AND json_extract(p.data, '$.demo_creator_id')=?""",
            (actor_id, actor_id)).fetchone()
        return row['id'] if row else None

    def demo_profiles(browser_token):
        if not browser_token:
            return {}
        return {row['role']: dict(row) for row in db().execute(
            """SELECT u.id,u.name,u.username,u.role FROM demo_profiles d
               JOIN users u ON u.id=d.user_id WHERE d.browser_hash=?""", (token_hash(browser_token),))}

    def is_demo_profile():
        return db().execute('SELECT 1 FROM demo_profiles WHERE user_id=?', (g.user['id'],)).fetchone() is not None

    @app.get('/api/demo-access')
    def demo_status():
        available = demo_available()
        profiles = demo_profiles(request.cookies.get('taskflow_demo', '')) if available else {}
        coordinator = profiles.get('coordinator')
        return jsonify(available=available, ready=bool(coordinator and demo_project_id(coordinator['id'])))

    @app.post('/api/demo-login')
    def demo_login():
        rules.check(demo_available(), '此服务未开启本机演示登录。', 404)
        role = payload().get('role')
        rules.check(isinstance(role, str) and role in ('coordinator', *PEOPLE), '请选择演示身份。')
        auth_rate_limit()
        browser_token = request.cookies.get('taskflow_demo', '')
        with transaction() as connection:
            profiles = demo_profiles(browser_token)
            if not profiles:
                rules.check(role == 'coordinator', '请先选择中介方并创建演示案例。', 409)
                browser_token = secrets.token_urlsafe(32)
                for key, name in {'coordinator': '中介方（演示）', **PEOPLE}.items():
                    uid = rules.ident()
                    person = {'id': uid, 'username': 'demo_' + uid, 'name': name, 'role': key}
                    connection.execute('INSERT INTO users VALUES(?,?,?,?,?)', (*person.values(), '!'))
                    connection.execute('INSERT INTO demo_profiles VALUES(?,?,?)',
                                       (token_hash(browser_token), key, uid))
                    profiles[key] = person
            project_id = demo_project_id(profiles['coordinator']['id'])
            if role != 'coordinator':
                rules.check(project_id, '请先选择中介方并创建演示案例。', 409)
        response = login_response(profiles[role], demo_project_id=project_id)
        response.set_cookie('taskflow_demo', browser_token, max_age=86400 * 7, httponly=True,
                            samesite='Strict', secure=request.is_secure)
        return response

    @app.post('/api/register')
    def register():
        data = payload()
        auth_rate_limit()
        username = rules.required(data.get('username'), '用户名', 40).lower()
        rules.check(re.fullmatch(r'[a-z0-9_@.\-]{3,40}', username), '用户名使用 3–40 位字母、数字、下划线或邮箱字符。')
        name = rules.required(data.get('name'), '姓名', 40)
        role = data.get('role')
        rules.check(role in rules.ROLES, '请选择四方身份之一。')
        password = data.get('password')
        rules.check(isinstance(password, str) and 8 <= len(password) <= 128, '密码需要 8–128 个字符。')
        user = {'id': rules.ident(), 'username': username, 'name': name, 'role': role}
        hashed = generate_password_hash(password)
        try:
            with transaction() as connection:
                connection.execute('INSERT INTO users VALUES(?,?,?,?,?)', (*user.values(), hashed))
        except sqlite3.IntegrityError:
            raise rules.Problem('用户名已注册，请登录或换一个用户名。', 409)
        return login_response(user)

    @app.post('/api/login')
    def login():
        data = payload()
        auth_rate_limit()
        username = rules.required(data.get('username'), '用户名', 40).lower()
        password = data.get('password')
        rules.check(isinstance(password, str) and 0 < len(password) <= 128, '请输入密码。')
        user = db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        rules.check(user is not None and check_password_hash(user['password_hash'], password), '用户名或密码错误。', 401)
        return login_response(dict(user))

    @app.get('/api/me')
    def me():
        return jsonify(user=g.user, csrf=g.csrf, demo_profile=is_demo_profile())

    @app.post('/api/logout')
    def logout():
        db().execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get('taskflow_session', '')),))
        response = jsonify(ok=True)
        response.delete_cookie('taskflow_session')
        return response

    def members(project_id):
        return [dict(row) for row in db().execute('SELECT u.id,u.name,u.username,m.role FROM members m JOIN users u ON m.user_id=u.id WHERE m.project_id=? ORDER BY u.name', (project_id,))]

    def project_row(project_id):
        row = db().execute('SELECT p.* FROM projects p JOIN members m ON m.project_id=p.id WHERE p.id=? AND m.user_id=?', (project_id, g.user['id'],)).fetchone()
        rules.check(row is not None, '项目不存在或你尚未加入。', 404)
        return row

    def files(project_id):
        rows = db().execute('''SELECT f.id,f.project_id,f.change_id,f.version,f.kind,f.reference,f.name,f.size,f.at,
                               u.name AS uploaded_by,r.task_id,r.report
                               FROM files f JOIN users u ON u.id=f.uploaded_by
                               LEFT JOIN photo_reviews r ON r.file_id=f.id
                               WHERE f.project_id=? ORDER BY f.at,f.id''', (project_id,))
        attachments = []
        for row in rows:
            file = dict(row)
            report = file.pop('report')
            if report:
                file['photo_review'] = json.loads(report)
            attachments.append(file)
        return attachments

    def project_view(project_id):
        row = project_row(project_id)
        project = json.loads(row['data'])
        attachments = files(project_id)
        for change in project['changes']:
            change['blockers'] = {kind: rules.blockers(change, attachments, kind) for kind in ('design', 'construction', 'owner', 'publish')}
            change['plans'] = rules.plans(change)
            change['recommendation'] = rules.recommend_plan(change)
            change['pending_confirmation'] = rules.pending_confirmation(change, attachments)
            if change['tasks'] and change.get('published_plan'):
                schedule_plan = schedule.baseline(change)
                change['schedule_view'] = schedule.preview(change, schedule_plan['nodes'], {})
                change['schedule_task_locks'] = [t['id'] for t in change['tasks']
                                                 if schedule.locked_for_change(change, t['id'])]
        return {'id': project_id, 'revision': row['revision'], 'title': row['title'], 'data': project,
                'members': members(project_id), 'files': attachments,
                'templates': {key: {**{k: template[k] for k in ('name', 'sample', 'design', 'evidence')},
                                    'task_standards': TASK_STANDARDS[key],
                                    'photo_criteria': {s['key']: {'angle': ANGLES[s['key']], 'content': CONTENT[s['key']]}
                                                       for s in template['evidence']}}
                              for key, template in rules.TEMPLATES.items()}}

    @contextmanager
    def edit_project(project_id, expected):
        with transaction() as connection:
            row = project_row(project_id)
            rules.check(type(expected) is int and expected == row['revision'], '项目已由其他成员更新，请刷新后重试。', 409)
            project = json.loads(row['data'])
            yield project
            connection.execute('UPDATE projects SET data=?,revision=revision+1 WHERE id=?', (json.dumps(project, ensure_ascii=False), project_id))

    @app.get('/api/projects')
    def list_projects():
        return jsonify(projects=[dict(row) for row in db().execute('SELECT p.id,p.title,p.revision,m.role FROM projects p JOIN members m ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.rowid DESC', (g.user['id'],))])

    @app.post('/api/projects')
    def create_project():
        rules.check(g.user['role'] == 'coordinator', '请由中介方创建项目并邀请其他参与方。', 403)
        rules.check(not is_demo_profile(), '演示身份请使用「直接体验示例」。', 403)
        data = payload()
        title = rules.required(data.get('title'), '项目名称', 100)
        baseline = {'version': 1, 'text': rules.required(data.get('baseline'), '原方案说明'),
                    'reference': rules.required(data.get('reference'), '原图纸或方案版本', 100), 'finish_date': data.get('finish_date') or None}
        if baseline['finish_date']:
            try:
                rules.date.fromisoformat(baseline['finish_date'])
            except (ValueError, TypeError):
                raise rules.Problem('原交付日期格式错误。')
        project = {'original_plan': baseline.copy(), 'plan': baseline.copy(), 'changes': [], 'events': [],
                   'synthetic': bool(data.get('synthetic'))}
        rules.event(project, g.user, '创建项目', title)
        project_id = rules.ident()
        with transaction() as connection:
            connection.execute('INSERT INTO projects VALUES(?,?,?,?)', (project_id, title, 1, json.dumps(project, ensure_ascii=False)))
            connection.execute('INSERT INTO members VALUES(?,?,?)', (project_id, g.user['id'], g.user['role']))
        return jsonify(project_view(project_id)), 201

    @app.get('/api/projects/<project_id>')
    def get_project(project_id):
        return jsonify(project_view(project_id))

    @app.post('/api/projects/demo')
    def create_demo():
        actor = g.user
        rules.check(actor['role'] == 'coordinator', '请使用中介方账号体验此案例。', 403)
        with transaction() as connection:
            project_id = demo_project_id(actor['id'])
            existing = bool(project_id)
            if not existing:
                project_id = rules.ident()
                connection.execute('INSERT INTO projects VALUES(?,?,?,?)', (project_id, TITLE, 1, '{}'))
                profiles = demo_profiles(request.cookies.get('taskflow_demo', '')) if demo_available() else {}
                if profiles.get('coordinator', {}).get('id') == actor['id']:
                    participants = [profiles[role] for role in PEOPLE]
                else:
                    participants = [{'id': rules.ident(), 'name': name, 'role': role} for role, name in PEOPLE.items()]
                    for person in participants:
                        connection.execute('INSERT INTO users VALUES(?,?,?,?,?)',
                                           (person['id'], 'demo_' + person['id'], person['name'], person['role'], '!'))
                for person in [actor, *participants]:
                    connection.execute('INSERT INTO members VALUES(?,?,?)',
                                       (project_id, person['id'], person['role']))

                def add_file(change_id, version, uploader, kind, reference, name, content):
                    file_id, stamp = rules.ident(), rules.now()
                    connection.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                       (file_id, project_id, change_id, version, kind, reference, name,
                                        len(content), content, uploader['id'], stamp))
                    return {'id': file_id, 'change_id': change_id, 'version': version,
                            'kind': kind, 'reference': reference, 'name': name, 'at': stamp}

                project = populate(actor, participants, add_file, kitchen=os.getenv('TASKFLOW_KITCHEN_DEMO')=='1')
                project['demo_creator_id'] = actor['id']
                connection.execute('UPDATE projects SET data=? WHERE id=?',
                                   (json.dumps(project, ensure_ascii=False), project_id))
        return jsonify(project_view(project_id)), 200 if existing else 201

    @app.post('/api/projects/<project_id>/invitations')
    def invite(project_id):
        rules.check(g.user['role'] == 'coordinator', '仅中介方可邀请项目成员。', 403)
        data = payload()
        role = data.get('role')
        rules.check(role in rules.ROLES, '邀请角色无效。')
        token = secrets.token_urlsafe(24)
        with edit_project(project_id, data.get('revision')) as project:
            db().execute('INSERT INTO invitations VALUES(?,?,?,?,NULL)', (token_hash(token), project_id, role, time.time() + 86400 * 3))
            rules.event(project, g.user, '创建项目邀请', rules.ROLES[role])
        return jsonify(token=token, role=role, project=project_view(project_id))

    @app.post('/api/join')
    def join():
        rules.check(not is_demo_profile(), '演示身份已分配到自己的案例。', 403)
        data = payload()
        token = rules.required(data.get('token'), '邀请码', 100)
        with transaction() as connection:
            invite = connection.execute('SELECT * FROM invitations WHERE token_hash=?', (token_hash(token),)).fetchone()
            rules.check(invite is not None and invite['expires'] > time.time(), '邀请码无效或已过期。', 400)
            rules.check(invite['used_by'] is None, '邀请码已经使用。', 409)
            rules.check(invite['role'] == g.user['role'], '邀请码对应的身份与你的注册身份不同。', 403)
            try:
                connection.execute('INSERT INTO members VALUES(?,?,?)', (invite['project_id'], g.user['id'], g.user['role']))
            except sqlite3.IntegrityError:
                raise rules.Problem('你已经在这个项目中。', 409)
            connection.execute('UPDATE invitations SET used_by=? WHERE token_hash=?', (g.user['id'], token_hash(token)))
            row = connection.execute('SELECT data FROM projects WHERE id=?', (invite['project_id'],)).fetchone()
            project = json.loads(row['data'])
            rules.event(project, g.user, '加入项目', rules.ROLES[g.user['role']])
            connection.execute('UPDATE projects SET data=?,revision=revision+1 WHERE id=?', (json.dumps(project, ensure_ascii=False), invite['project_id']))
        return jsonify(project_view(invite['project_id']))

    @app.post('/api/projects/<project_id>/changes')
    def create_change(project_id):
        project_row(project_id)
        data = payload()
        simple = data.get('simple') is True
        role = g.user['role']
        rules.check(role == 'owner' or (simple and role == 'contractor'),
                    '请由住户提出需求，或由施工方上报材料变更。', 403)
        text = rules.required(data.get('text'), '住户变更要求')
        template_id = data.get('template_id', 'tiles')
        rules.check(isinstance(template_id, str) and template_id in rules.TEMPLATES, '请选择有效的工序模板。')
        analysis = ({'mode': 'rules', 'label': '住户变更', 'facts': [], 'questions': []}
                    if simple else analyze(text, template_id))
        wording = translate_project_text(text, True) if simple else None
        with edit_project(project_id, data.get('revision')) as project:
            change = rules.new_change(project, g.user, text, members(project_id), analysis, template_id)
            if simple:
                owner_id = g.user['id'] if role == 'owner' else next(
                    (person['id'] for person in members(project_id) if person['role'] == 'owner'), None)
                rules.check(owner_id, '请先邀请住户加入项目。', 409)
                change['collaboration'] = {
                    'wording': wording, 'version': 1, 'decisions': {}, 'status': 'review',
                    'trigger': 'materials' if role == 'contractor' else 'request',
                    'owner_id': owner_id,
                    'proposal': text,
                }
                rules.current(change)['approvers']['owner'] = owner_id
            change_id = change['id']
        return jsonify(project=project_view(project_id), change_id=change_id), 201

    @app.post('/api/projects/<project_id>/demo-refund')
    def demo_refund(project_id):
        rules.check(demo_available() and g.user['role']=='owner' and is_demo_profile(), '仅演示住户可以创建此样例。', 403)
        data = payload()
        with edit_project(project_id, data.get('revision')) as project:
            profiles = demo_profiles(request.cookies.get('taskflow_demo', ''))
            rules.check(project.get('synthetic') and project.get('demo_creator_id') == profiles.get('coordinator', {}).get('id')
                        and profiles.get('owner', {}).get('id') == g.user['id'], '仅可在自己的演示项目中操作。', 403)
            change = next((c for c in project['changes'] if c.get('refund')), None)
            if not change:
                def add_file(change, actor, kind, reference, name, description):
                    fid, at, version = rules.ident(), rules.now()
                    encoded = description.encode()
                    db().execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                 (fid, project_id, change['id'], version, kind, reference, name,
                                  len(encoded), encoded, actor['id'], at))
                    return {'id': fid, 'kind': kind, 'reference': reference, 'change_id': change['id'], 'at': at}
                change = prepare_refund(project, g.user, members(project_id), add_file)
            if not rules.approved(change, 'owner'):
                rules.approve(project, change, g.user, {
                    'kind': 'owner', 'decision': 'approve',
                    'note': '演示确认：仅保留客厅通铺，已核对预计返费 600 元及调整后的交付日期。',
                }, files(project_id))
        return jsonify(project=project_view(project_id), change_id=change['id'])

    @app.post('/api/projects/<project_id>/changes/<change_id>/translate')
    def translate_change(project_id, change_id):
        project = json.loads(project_row(project_id)['data'])
        change = next((c for c in project['changes'] if c['id'] == change_id), None)
        rules.check(change is not None, '变更不存在。', 404)
        event_id = payload().get('event_id')
        if g.user['role'] == 'owner':
            participants = {m['id'] for m in members(project_id)
                            if m['role'] in ('designer', 'contractor', 'coordinator')}
            event = next((e for e in project['events'] if e['id'] == event_id
                          and e['change_id'] == change_id and e['actor_id'] in participants), None)
            rules.check(event is not None, '请选择本次变更的专业方记录。', 404)
            return jsonify(translate_project_text(event['detail'], False))
        rules.check(g.user['role'] in ('designer', 'contractor', 'coordinator') and not event_id,
                    '请查看本次变更的住户原话。', 403)
        return jsonify(translate_project_text(change['source']['text'], True))

    @app.post('/api/projects/<project_id>/changes/<change_id>/<command>')
    def change_action(project_id, change_id, command):
        data = payload()
        with edit_project(project_id, data.get('revision')) as project:
            change = next((c for c in project['changes'] if c['id'] == change_id), None)
            rules.check(change is not None, '变更不存在。', 404)
            rules.check(g.user['role'] != 'mediator' or command == 'dispute', '外部复核账号仅能提交争议意见。', 403)
            collaboration = change.get('collaboration')
            if collaboration:
                rules.check(command in ('comment', 'feasibility'), '请使用当前变更单的协商操作。', 409)
                if command == 'feasibility':
                    role = g.user['role']
                    status = collaboration['status']
                    decisions = collaboration['decisions']
                    rules.check(data.get('version') == collaboration['version'], '版本已变更，请刷新。', 409)
                    note = rules.required(data.get('note'), '确认说明', 500)
                    decision = data.get('decision')
                    review_role = {'designer': 'design', 'contractor': 'construction'}.get(role)
                    approvers = rules.current(change)['approvers']
                    if review_role and not approvers[review_role] and status in ('review', 'returned'):
                        approvers[review_role] = g.user['id']
                    if decision == 'revise':
                        rules.check((status in ('returned', 'review') or (status == 'owner'
                                    and change['baseline']['version'] != project['plan']['version'])) and review_role
                                    and rules.current(change)['approvers'][review_role] == g.user['id'],
                                    '仅指定设计师或施工方可重新提交。', 403)
                        collaboration.update(status='review', version=collaboration['version']+1,
                                             decisions={}, proposal=note)
                        change['baseline'] = dict(project['plan'])
                    elif status == 'owner':
                        rules.check(g.user['id'] == collaboration.get('owner_id', change['source']['author_id']),
                                    '请由项目住户确认。', 403)
                        rules.check(decision in ('approve', 'return'), '请选择确认或退回。')
                        if decision == 'approve':
                            rules.check(change['baseline']['version'] == project['plan']['version'],
                                        '执行方案已更新，请基于新版修订后重新确认。', 409)
                            decisions['owner'] = {'note': note, 'decision': decision}
                        collaboration['status'] = 'active' if decision == 'approve' else 'returned'
                    else:
                        rules.check(status == 'review' and review_role
                                    and rules.current(change)['approvers'][review_role] == g.user['id'],
                                    '当前身份或阶段无法确认。', 403)
                        rules.check(role not in decisions, '本版本已确认。', 409)
                        rules.check(decision in ('approve', 'return'), '请选择确认或退回。')
                        decisions[role] = {'note': note, 'decision': decision}
                        if decision == 'return':
                            collaboration['status'] = 'returned'
                        elif len(decisions) == 2:
                            collaboration['status'] = 'owner'
                    action = {'approve': '确认可行', 'return': '退回方案', 'revise': '提交修订'}[decision]
                    rules.event(project, g.user, f"变更 v{collaboration['version']} · {action}", note, change_id)
                    if collaboration['status'] == 'active':
                        collaboration['activated_at'] = rules.now()
                        plan = project['plan']
                        plan.update(version=plan['version']+1,
                                    text=plan['text'] + '\n本次已确认调整：' + collaboration.get('proposal', change['source']['text']),
                                    change_id=change_id, change_version=collaboration['version'])
                else:
                    rules.check(g.user['role'] in ('owner','designer','contractor'), '请由协作方留言。', 403)
                    rules.event(project, g.user, '协商留言', rules.required(data.get('text'), '留言'), change_id)
            elif command == 'revise':
                rules.revise(project, change, g.user, data, members(project_id))
            elif command == 'approve':
                rules.approve(project, change, g.user, data, files(project_id))
            elif command == 'publish':
                rules.publish(project, change, g.user, files(project_id))
            elif command == 'task':
                if data.get('command')=='submit':
                    rules.check(not schedule.locked_for_change(change, data.get('task_id')),
                                '本任务涉及尚未生效的变更，须确认并发布后才能执行。',409)
                rules.handle_task(project, change, g.user, data, files(project_id))
            elif command == 'accept':
                rules.accept(project, change, g.user, data)
            elif command == 'dispute':
                rules.handle_dispute(project, change, g.user, data, files(project_id))
            elif command == 'site-issue':
                note = rules.required(data.get('note'), '现场情况或处理结果', 500)
                if g.user['role'] == 'contractor':
                    rules.check(not data.get('issue_id'), '仅项目经理可处理异常。', 403)
                    rules.event(project, g.user, '协商留言', '施工问题：' + note, change_id)
                else:
                    rules.check(g.user['role'] == 'coordinator', '仅项目经理可处理异常。', 403)
                    issue = next((event for event in project['events']
                                  if event['id'] == data.get('issue_id')
                                  and event['change_id'] == change_id
                                  and event['action'] == '协商留言'
                                  and event['detail'].startswith('施工问题：')), None)
                    rules.check(issue is not None, '未找到本变更的施工异常。', 404)
                    rules.check(not issue.get('resolution'), '该异常已处理，请刷新查看。', 409)
                    issue['resolution'] = {'note': note, 'by': g.user['name'], 'at': rules.now()}
                    rules.event(project, g.user, '施工异常已处理', issue['detail'] + ' → ' + note, change_id)
            elif command == 'comment':
                rules.event(project, g.user, '协商留言', rules.required(data.get('text'), '留言'), change_id)
            else:
                raise rules.Problem('操作不存在。', 404)
        return jsonify(project_view(project_id))

    @app.post('/api/projects/<project_id>/changes/<change_id>/schedule/<command>')
    def schedule_action(project_id, change_id, command):
        data = payload()
        if command == 'preview':
            row = project_row(project_id)
            project = json.loads(row['data'])
            rules.check(row['revision'] == data.get('revision'), '项目已由其他成员更新，请刷新。', 409)
            change = next((c for c in project['changes'] if c['id'] == change_id and c.get('published_plan') and c['tasks']), None)
            rules.check(change, '请先发布施工计划。', 409)
            return jsonify(schedule.preview(change, data.get('nodes'), data.get('fees', {})))
        if command=='analyze-note':
            project = json.loads(project_row(project_id)['data'])
            rules.check(any(c['id']==change_id for c in project['changes']), '变更不存在。',404)
            return jsonify(analyze_site_note(rules.required(data.get('text'),'施工备注',500)))
        rules.check(command in ('save', 'propose', 'decide', 'publish', 'rehearse'), '操作不存在。', 404)
        with edit_project(project_id, data.get('revision')) as project:
            change = next((c for c in project['changes'] if c['id'] == change_id), None)
            rules.check(change, '请刷新页面。') if False else None
            rules.check(change is not None, '变更不存在。', 404)
            kitchen = change.get('kitchen_change')
            if kitchen and command in ('propose','publish'):
                available = {(f['kind'], f['reference']) for f in files(project_id) if f['change_id']==change_id}
                rules.check({('drawing',kitchen['drawing']),('quote',kitchen['quote_reference'])}<=available,
                            '缺少新版图纸或换砖报价。', 409)
            if command=='rehearse':
                profiles=demo_profiles(request.cookies.get('taskflow_demo',''))
                rules.check(demo_available() and project.get('synthetic') and change.get('kitchen_change')
                            and profiles.get('coordinator',{}).get('id')==g.user['id']
                            and project.get('demo_creator_id')==g.user['id'], '仅自己的厨房演示可准备确认。',403)
                active=change.get('schedule_proposals',[])
                rules.check(active and active[-1]['status']=='pending' and active[-1]['id']==data.get('proposal_id'),
                            '请先提交可行排程。',409)
                proposal=active[-1]
                for kind, role in [('design','designer'),('construction','contractor')]:
                    simulated=profiles[role]
                    rules.check(proposal['approvers'][kind]==simulated['id'], '演示确认人不匹配。',409)
                    if kind not in proposal['decisions']:
                        schedule.handle(project,change,simulated,'decide',
                                        {'proposal_id':proposal['id'],'decision':'approve','note':'路演预置确认（合成案例）'})
            else:
                schedule.handle(project, change, g.user, command, data)
        return jsonify(project_view(project_id))

    @app.post('/api/projects/<project_id>/changes/<change_id>/files')
    def upload(project_id, change_id):
        kind = request.form.get('kind')
        rules.check(kind in ('drawing', 'quote', 'site'), '请选择文件用途。')
        allowed_roles = {'drawing': ('designer',), 'quote': ('contractor', 'coordinator'), 'site': ('contractor',)}
        rules.check(g.user['role'] in allowed_roles[kind], '当前身份无法上传此类资料。', 403)
        file = request.files.get('file')
        rules.check(file is not None and file.filename, '请选择文件。')
        name = file.filename.replace('\\', '/').split('/')[-1][:160]
        rules.check(Path(name).suffix.lower() in ('.pdf', '.png', '.jpg', '.jpeg', '.txt', '.docx'), '支持 PDF、图片、TXT 和 DOCX。')
        content = file.read(8 * 1024 * 1024 + 1)
        rules.check(0 < len(content) <= 8 * 1024 * 1024, '文件需在 8 MB 以内。')
        reference = rules.required(request.form.get('reference'), '文件版本或用途说明', 100)
        try:
            expected = int(request.form.get('revision', ''))
        except ValueError:
            raise rules.Problem('请刷新页面后再上传。')
        with edit_project(project_id, expected) as project:
            change = next((c for c in project['changes'] if c['id'] == change_id), None)
            rules.check(change is not None, '变更不存在。', 404)
            if change.get('collaboration'):
                rules.check(kind == 'site', '请在此变更单上传现场照片。', 409)
                rules.check(Path(name).suffix.lower() in ('.jpg', '.jpeg', '.png')
                            and (content.startswith(b'\x89PNG\r\n\x1a\n') or content.startswith(b'\xff\xd8\xff')),
                            '请选择 JPG 或 PNG 照片。')
            elif kind in ('drawing', 'quote'):
                rules.check(change['status'] == 'clarifying', '请在澄清阶段补充审批资料。', 409)
                rules.check(not any(rules.approved(change, k) for k in rules.APPROVAL_ROLES), '当前版本已有确认，请先创建修订再补充审批材料。', 409)
            else:
                rules.check(change['status'] == 'executing', '请在施工任务发布后回传现场记录。', 409)
                rules.validate_site_reference(reference, rules.work_template(change)['evidence'])
            db().execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (rules.ident(), project_id, change_id, rules.current(change)['number'], kind, reference, name,
                          len(content), content, g.user['id'], rules.now()))
            rules.event(project, g.user, '上传资料', name + ' · ' + reference, change_id)
        return jsonify(project_view(project_id))

    @app.post('/api/projects/<project_id>/changes/<change_id>/tasks/<task_id>/photos')
    def upload_task_photo(project_id, change_id, task_id):
        row = project_row(project_id)
        try:
            expected = int(request.form.get('revision', ''))
        except ValueError:
            raise rules.Problem('请刷新页面后再上传。')
        rules.check(expected == row['revision'], '项目已由其他成员更新，请刷新后重试。', 409)
        project = json.loads(row['data'])
        change = next((c for c in project['changes'] if c['id'] == change_id), None)
        rules.check(change is not None, '变更不存在。', 404)
        task = next((t for t in change['tasks'] if t['id'] == task_id), None)
        rules.check(task is not None, '任务不存在。', 404)
        rules.check(not schedule.locked_for_change(change, task_id), '请先确认并发布施工变更。', 409)
        rules.check(task['owner_id'] == g.user['id'], '仅任务执行人可上传现场照片。', 403)
        rules.check(change['status'] == 'executing' and task['status'] in ('ready', 'returned'),
                    '当前任务没有开放补交。', 409)
        statuses = {t['id']: t['status'] for t in change['tasks']}
        rules.check(all(statuses[d] == 'approved' for d in task['depends_on']), '前置任务尚未确认。', 409)
        template_id = change.get('template_id', 'tiles')
        key = request.form.get('standard')
        rules.check(key in TASK_STANDARDS[template_id].get(task_id, ()), '请选择本任务的拍摄标准。')
        standard = next(s for s in rules.work_template(change)['evidence'] if s['key'] == key)
        note = rules.required(request.form.get('note'), '拍摄部位与说明', 85)
        file = request.files.get('file')
        rules.check(file is not None and file.filename, '请选择照片。')
        name = file.filename.replace('\\', '/').split('/')[-1][-160:]
        rules.check(Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg'), '请选择 JPG 或 PNG 原图。')
        content = file.read(8 * 1024 * 1024 + 1)
        received = datetime.now(rules.TZ)
        rules.check(0 < len(content) <= 8 * 1024 * 1024, '照片需在 8 MB 以内。')
        current_version = rules.current(change)
        review = inspect_photo(content, received, standard, current_version['data'])
        file_id = rules.ident()
        with edit_project(project_id, expected) as stored:
            db().execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (file_id, project_id, change_id, current_version['number'], 'site', key + ' | ' + note,
                          name, len(content), content, g.user['id'], received.isoformat()))
            db().execute('INSERT INTO photo_reviews VALUES(?,?,?)',
                         (file_id, task_id, json.dumps(review, ensure_ascii=False)))
            rules.event(stored, g.user, '上传工序照片并初审', task['title'] + ' · ' + key + ' · ' + name, change_id)
        return jsonify(project_view(project_id)), 201

    @app.post('/api/projects/<project_id>/changes/<change_id>/evidence-review')
    def evidence_review(project_id, change_id):
        rules.check(g.user['role'] != 'mediator', '外部复核账号仅能提交争议意见。', 403)
        data = payload()
        view = project_view(project_id)
        rules.check(data.get('revision') == view['revision'], '项目已由其他成员更新，请刷新后重试。', 409)
        change = next((c for c in view['data']['changes'] if c['id'] == change_id), None)
        rules.check(change is not None, '变更不存在。', 404)
        fields = rules.current(change)['data']
        candidates = [f for f in view['files'] if f['change_id'] == change_id and (
            f['kind'] == 'site' or f['reference'] == fields.get('drawing_version' if f['kind'] == 'drawing' else 'quote_reference'))]
        missing = [label for kind, label in [('drawing', '确认版设计图纸'), ('quote', '报价依据'), ('site', '施工交付记录')]
                   if not any(f['kind'] == kind for f in candidates)]
        documents = []
        for file in candidates[-12:]:
            if file['name'].lower().endswith('.txt'):
                content = db().execute('SELECT content FROM files WHERE id=?', (file['id'],)).fetchone()['content']
                documents.append({'name': file['name'], 'text': content.decode('utf-8-sig', errors='replace')[:6000]})
        assessment = rules.evidence_assessment(view['files'], change, rules.current(change)['number'])
        report = review_evidence(fields, documents, missing, candidates, rules.work_template(change)['evidence'])
        report.update(assessment)
        with edit_project(project_id, data.get('revision')) as project:
            target = next(c for c in project['changes'] if c['id'] == change_id)
            report.update(at=rules.now(), version=rules.current(target)['number'], by=g.user['name'])
            target.setdefault('evidence_reports', []).append(report)
            rules.event(project, g.user, '核对提交材料', f"缺项 {len(missing)} 项，待复核提示 {len(report['findings'])} 项。", change_id)
        return jsonify(project_view(project_id))

    @app.get('/api/files/<file_id>/preview')
    def preview(file_id):
        """Inline image preview for site-trace photos; membership is checked."""
        file = db().execute('SELECT name, content, project_id FROM files WHERE id=?', (file_id,)).fetchone()
        rules.check(file is not None, '文件不存在。', 404)
        project_row(file['project_id'])
        suffix = Path(file['name']).suffix.lower()
        rules.check(suffix in ('.png', '.jpg', '.jpeg'), '仅支持预览图片留痕。', 400)
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[suffix]
        return send_file(BytesIO(file['content']), mimetype=mime, as_attachment=False)

    @app.get('/api/files/<file_id>')
    def download(file_id):
        file = db().execute('SELECT * FROM files WHERE id=?', (file_id,)).fetchone()
        rules.check(file is not None, '文件不存在。', 404)
        project_row(file['project_id'])
        return send_file(BytesIO(file['content']), as_attachment=True, download_name=file['name'], mimetype='application/octet-stream')

    return app


if __name__ == '__main__':
    from waitress import serve
    port = int(os.getenv('TASKFLOW_PORT', '8765'))
    print(f'工序共识已启动：http://localhost:{port}', flush=True)
    host = os.getenv('TASKFLOW_HOST', '0.0.0.0')
    demo_access = os.getenv('TASKFLOW_DEMO_ACCESS') == '1' and host == '127.0.0.1'
    proxy = {}
    if os.getenv('TASKFLOW_PUBLIC_DEMO_HOST'):
        if host != '127.0.0.1' or not demo_access:
            raise SystemExit('Public demo requires a loopback-only backend.')
        proxy = {'trusted_proxy':'127.0.0.1',
                 'trusted_proxy_headers':{'x-forwarded-for','x-forwarded-proto','x-forwarded-host'}}
    elif os.getenv('TASKFLOW_TRUST_PROXY') == '1':
        proxy = {'trusted_proxy': '*',
                 'trusted_proxy_headers': {'x-forwarded-for', 'x-forwarded-proto'}}
    serve(create_app(demo_access=demo_access), host=host, port=port, threads=8,
          max_request_body_size=10 * 1024 * 1024, **proxy)
