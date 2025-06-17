import os, re, urllib.parse, requests
from datetime import datetime as dt, timezone
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory, jsonify, Response, abort
)
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Text
from sqlalchemy.orm import sessionmaker
import email_sync_app
Base, EmailModel = email_sync_app.Base, email_sync_app.EmailModel

# ── 既存 DB モデル（列名そのまま） ─────────────────────────
class NoteModel(Base):
    __tablename__ = 'notes'
    id          = Column(Integer, primary_key=True)
    uidvalidity = Column(BigInteger, nullable=False)
    uid         = Column(BigInteger, nullable=False)
    page        = Column(Integer, nullable=False)
    content     = Column(Text, default='')
    uploaded_at = Column(DateTime, default=lambda: dt.now(timezone.utc))

class PhotoModel(Base):
    __tablename__ = 'photos'
    id          = Column(Integer, primary_key=True)
    uidvalidity = Column(BigInteger, nullable=False)
    uid         = Column(BigInteger, nullable=False)
    filename    = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=lambda: dt.now(timezone.utc))

# ── util ──────────────────────────────────────────────────────────
from email.header import decode_header
def dec(h:str)->str:
    return ''.join(p.decode(enc or 'utf-8','ignore') if isinstance(p,bytes) else p
                   for p,enc in decode_header(h or ''))
def extract_customer_name(b:str)->str:
    m=re.search(r'(?:お名前|氏名)[:：]\s*([^\r\n<]+)', b or '', flags=re.I)
    return m.group(1).strip() if m else ''
def sender_name(addr:str)->str:
    return re.sub(r'\s*<[^>]+>','',addr or '').strip()
ALLOWED_EXT={'png','jpg','jpeg','gif'}

# ── Flask / DB 初期化 ────────────────────────────────────────
load_dotenv()
DB_URL=os.getenv('DATABASE_URL','sqlite:///emails.db')
SECRET=os.getenv('FLASK_SECRET_KEY','dev')
UPLOAD=os.path.join(os.path.dirname(__file__),'uploads')
os.makedirs(UPLOAD, exist_ok=True)

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET, UPLOAD_FOLDER=UPLOAD)

engine=create_engine(DB_URL, echo=False, future=True)
Session=sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# ── プロキシ: /proxy?url=ENCODED ─────────────────────────────
@app.route('/proxy')
def proxy():
    raw=request.args.get('url','')
    url=urllib.parse.unquote(raw)
    if not url.startswith(('http://','https://')):
        abort(400,'invalid url')
    try:
        r=requests.get(url, timeout=8, stream=True, headers={'User-Agent':'Mozilla/5.0'})
    except Exception as e:
        abort(502,str(e))
    if r.status_code!=200:
        abort(r.status_code)
    ct=r.headers.get('Content-Type','image/jpeg')
    return Response(r.content, content_type=ct,
                    headers={'Cache-Control':'public,max-age=86400'})

# ── 既存ルーティング（変更なし） ───────────────────────────
@app.route('/')
def idx(): return redirect(url_for('list_emails'))

@app.route('/emails')
def list_emails():
    s=Session()
    rows=s.query(EmailModel).order_by(EmailModel.date.desc()).all()
    for r in rows:
        r.subject=dec(r.subject)
        r.customer_name=extract_customer_name(r.body) or sender_name(dec(r.from_addr))
    s.close()
    return render_template('emails.html', emails=rows)

@app.route('/email/<int:uv>/<int:uid>')
def detail(uv,uid):
    s=Session()
    e=s.query(EmailModel).filter_by(uidvalidity=uv,uid=uid).first()
    if not e: s.close(); return jsonify({'error':'not found'}),404
    photos=s.query(PhotoModel).filter_by(uidvalidity=uv,uid=uid).all()
    notes ={n.page:n.content for n in s.query(NoteModel).filter_by(uidvalidity=uv,uid=uid)}
    s.close()
    return jsonify({
        'uidvalidity':uv,'uid':uid,
        'subject':dec(e.subject),
        'from_addr':dec(e.from_addr),
        'customer_name':extract_customer_name(e.body) or sender_name(dec(e.from_addr)),
        'date':e.date.isoformat(' '),
        'body':e.body,'status':e.status,
        'photos':[url_for('uploaded_file',filename=p.filename) for p in photos],
        'notes':notes
    })

@app.route('/emails/<int:uv>/<int:uid>/update_status',methods=['POST'])
def upd_status(uv,uid):
    s=Session(); rec=s.query(EmailModel).filter_by(uidvalidity=uv,uid=uid).first()
    if rec: rec.status=request.form['status']; s.commit()
    s.close(); return '',204

@app.route('/emails/<int:uv>/<int:uid>/save_note',methods=['POST'])
def save_note(uv,uid):
    page=int(request.form['page']); txt=request.form.get('content','')
    if page not in (1,2,3,4): return jsonify({'error':'page'}),400
    s=Session(); n=s.query(NoteModel).filter_by(uidvalidity=uv,uid=uid,page=page).first()
    (n:=n or NoteModel(uidvalidity=uv,uid=uid,page=page)).content=txt
    s.add(n); s.commit(); s.close(); return jsonify({'ok':True})

@app.route('/emails/<int:uv>/<int:uid>/upload_photo',methods=['POST'])
def upload_photo(uv,uid):
    f=request.files.get('photo')
    if not f or f.filename=='' or f.filename.rsplit('.',1)[-1].lower() not in ALLOWED_EXT:
        flash('画像ファイルのみアップできます','error'); return redirect(url_for('list_emails'))
    fname=f"{uv}_{uid}_{dt.now(timezone.utc):%Y%m%d%H%M%S}_{secure_filename(f.filename)}"
    f.save(os.path.join(UPLOAD,fname))
    s=Session(); s.add(PhotoModel(uidvalidity=uv,uid=uid,filename=fname)); s.commit(); s.close()
    return redirect(url_for('list_emails'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename): return send_from_directory(UPLOAD,filename)

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000)
