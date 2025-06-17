# ── 標準 & 外部 ──────────────────────────────────────────
import os, logging
from datetime import datetime as dt, timezone
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, jsonify, abort
)
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Text
from sqlalchemy.orm import sessionmaker

# ── 自作モジュール（ここで必要関数を直接 import）───────────
import email_sync_app
from email_sync_app import (
    Base, EmailModel,
    fetch_past_month_and_save,
    fetch_and_save
)

# ── MODEL（Note & Photo は元のまま）──────────────────────
class NoteModel(Base):
    __tablename__ = 'notes'
    id          = Column(Integer, primary_key=True)
    uidvalidity = Column(BigInteger, nullable=False)
    uid         = Column(BigInteger, nullable=False)
    page        = Column(Integer,  nullable=False)
    content     = Column(Text,     default='')
    uploaded_at = Column(DateTime, default=lambda: dt.now(timezone.utc))

class PhotoModel(Base):
    __tablename__ = 'photos'
    id          = Column(Integer, primary_key=True)
    uidvalidity = Column(BigInteger, nullable=False)
    uid         = Column(BigInteger, nullable=False)
    filename    = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=lambda: dt.now(timezone.utc))

# ── Flask / DB ─────────────────────────────────────────
load_dotenv()
DB_URL  = os.getenv('DATABASE_URL', 'sqlite:///emails.db')
SECRET  = os.getenv('FLASK_SECRET_KEY', 'dev')
UPLOAD  = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD, exist_ok=True)

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET, UPLOAD_FOLDER=UPLOAD)

engine  = create_engine(DB_URL, echo=False, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# ── メール同期ラッパ ────────────────────────────────
def sync_last_month():
    app.logger.info("▶ Initial 30-day fetch")
    fetch_past_month_and_save()

def sync_latest(limit=50):
    app.logger.info("▶ Periodic fetch")
    fetch_and_save(limit=limit)

# ── APScheduler ───────────────────────────────────────
def start_scheduler():
    sched = BackgroundScheduler(timezone="Asia/Tokyo")
    # プロセス起動直後に 1 回だけ
    sched.add_job(sync_last_month,
                  id='initial_once',
                  next_run_time=dt.now(timezone.utc),
                  max_instances=1)
    # 15 分おきに差分取得
    sched.add_job(sync_latest,
                  'interval', minutes=15,
                  id='loop', kwargs={'limit': 50})
    sched.start()
    app.logger.info("Scheduler started")

start_scheduler()

# ── ルーティング（一覧だけ例示、他は元のまま残して下さい）───
@app.route('/')
def index():
    sess = Session()
    emails = sess.query(EmailModel).order_by(EmailModel.date.desc()).all()
    sess.close()
    return render_template('emails.html', emails=emails)

# ▼ 追加：今すぐ取り込むボタン用 API ───────────────────
@app.route('/sync_now', methods=['POST'])
def sync_now():
    try:
        sync_latest(limit=10)      # ← ここを 10 に変更
        return jsonify({'ok': True}), 200
    except Exception as e:
        app.logger.exception("Manual sync failed")
        return jsonify({'ok': False, 'error': str(e)}), 500
# ▲ ここまで追加 ──────────────────────────────────
# --- いま DB に入っているメール件数を返すだけの簡易 API ---
@app.route('/count')
def count_mails():
    sess = Session()
    n = sess.query(EmailModel).count()
    sess.close()
    return {'count': n}

# ── 画像配信など既存エンドポイントは元のまま ────────────
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
