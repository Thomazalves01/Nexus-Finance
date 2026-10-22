import os, json, re, sqlite3, urllib.request, urllib.error, hmac, hashlib, secrets, math
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, redirect, session, url_for
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
app = Flask(__name__, static_folder=None)
APP_ENV = os.getenv('APP_ENV', 'development').lower()
app.secret_key = os.getenv('FLASK_SECRET_KEY', '')
APP_PASSWORD = os.getenv('NEXUS_PASSWORD', '')
DB_PATH = Path(os.getenv('NEXUS_DB_PATH', str(BASE / 'nexus.db')))
VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '')
META_APP_SECRET = os.getenv('META_APP_SECRET', '')
if APP_ENV == 'production' and (len(app.secret_key) < 32 or len(APP_PASSWORD) < 12 or not META_APP_SECRET):
    raise RuntimeError('Em produção, configure FLASK_SECRET_KEY (32+ caracteres), NEXUS_PASSWORD (12+ caracteres) e META_APP_SECRET.')
if not app.secret_key:
    app.secret_key = secrets.token_urlsafe(48)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1', PERMANENT_SESSION_LIFETIME=3600)

ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN', '')
PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
ALLOWED_PHONE = re.sub(r'\D', '', os.getenv('ALLOWED_WHATSAPP_PHONE', ''))
GRAPH_VERSION = os.getenv('WHATSAPP_GRAPH_VERSION', 'v22.0')

DEFAULT_DATA = {'tx': [], 'invest': [], 'subs': []}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS processed_messages (message_id TEXT PRIMARY KEY)')
    conn.commit()
    return conn

def get_data():
    conn = db()
    row = conn.execute('SELECT payload FROM app_state WHERE id=1').fetchone()
    if not row:
        conn.execute('INSERT INTO app_state(id,payload) VALUES(1,?)', (json.dumps(DEFAULT_DATA, ensure_ascii=False),))
        conn.commit()
        payload = DEFAULT_DATA
    else:
        payload = json.loads(row[0])
    conn.close()
    return payload

def set_data(payload):
    # Validate data shape and amounts before persisting shared financial records.
    safe = {k: payload.get(k, []) for k in ('tx', 'invest', 'subs')}
    if not all(isinstance(safe[k], list) for k in safe):
        raise ValueError('Formato inválido')
    if any(len(safe[k]) > 10000 for k in safe):
        raise ValueError('Limite de registros excedido')
    for item in safe['tx']:
        if not isinstance(item, dict) or item.get('type') not in ('income', 'expense', 'transfer') or not isinstance(item.get('name'), str) or not item['name'].strip():
            raise ValueError('Movimentação inválida')
        amount = float(item.get('amount', 0))
        if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000_000:
            raise ValueError('Valor de movimentação inválido')
    for item in safe['invest']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('Investimento inválido')
        amount = float(item.get('amount', 0))
        if not math.isfinite(amount) or amount < 0 or amount > 1_000_000_000:
            raise ValueError('Valor de investimento inválido')
    for item in safe['subs']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('Assinatura inválida')
        amount = float(item.get('amount', 0))
        if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000_000:
            raise ValueError('Valor de assinatura inválido')
    conn = db()
    conn.execute('INSERT INTO app_state(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (json.dumps(safe, ensure_ascii=False),))
    conn.commit()
    conn.close()
    return safe

@app.before_request
def require_login():
    # The public WhatsApp webhook is exempt; dashboard and data API require a password.
    if request.endpoint in ('login', 'verify_webhook', 'webhook') or request.path.startswith('/static/'):
        return None
    if not session.get('authenticated'):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Autenticação necessária'}), 401
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if 'login_csrf' not in session:
        session['login_csrf'] = secrets.token_urlsafe(24)
    if request.method == 'POST':
        supplied = request.form.get('password', '')
        csrf = request.form.get('csrf_token', '')
        if not hmac.compare_digest(csrf, session.get('login_csrf', '')):
            error = 'Sessão expirada. Atualize a página e tente novamente.'
        elif APP_PASSWORD and hmac.compare_digest(supplied, APP_PASSWORD):
            session.clear()
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('index'))
        else:
            error = 'Senha incorreta ou NEXUS_PASSWORD não configurada.'
    return f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#101713'><title>Entrar · Nexus Finance</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0c100e;color:#f1f6f1;font:16px system-ui;padding:20px}}form{{width:min(360px,100%);box-sizing:border-box;background:#141b17;border:1px solid #29352d;border-radius:20px;padding:24px}}h1{{font-size:22px}}p{{color:#9ba99f;font-size:14px}}input,button{{width:100%;box-sizing:border-box;padding:13px;border-radius:12px;margin-top:10px;font:inherit}}input{{background:#0e1410;color:#fff;border:1px solid #29352d}}button{{background:#a4f36b;color:#15220f;border:0;font-weight:800}}.error{{color:#ff817f}}</style><form method='post'><h1>Nexus Finance</h1><p>Acesse seu painel pessoal.</p><input type='hidden' name='csrf_token' value='{session['login_csrf']}'><label for='password'>Senha de acesso</label><input id='password' name='password' type='password' autocomplete='current-password' required><button type='submit'>Entrar</button><p class='error'>{error}</p></form></html>"""

@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.get('/')
def index():
    return send_from_directory(BASE, 'index.html')

@app.get('/api/data')
def api_get_data():
    return jsonify(get_data())

@app.post('/api/data')
def api_save_data():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'JSON inválido'}), 400
    try:
        return jsonify(set_data(payload))
    except (ValueError, TypeError):
        return jsonify({'error': 'Formato de dados inválido'}), 400

def parse_amount(text):
    matches = re.findall(r'(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[,.]\d{1,2})?)\s*(?:reais|real)?', text.lower())
    if not matches:
        return None
    raw = matches[0]
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif raw.count('.') > 1:
        raw = raw.replace('.', '')
    try:
        value = Decimal(raw).quantize(Decimal('0.01'))
        return float(value) if value > 0 else None
    except InvalidOperation:
        return None

def categorize(text):
    t = text.lower()
    rules = [
      (('salário','salario','pagamento','recebi meu salário'), 'Salário'),
      (('almoço','almoco','janta','jantar','lanche','mercado','comida','restaurante'), 'Alimentação'),
      (('uber','ônibus','onibus','gasolina','combustível','combustivel','transporte'), 'Transporte'),
      (('netflix','spotify','assinatura','mensalidade','prime video'), 'Assinatura'),
      (('aluguel','luz','água','agua','internet','moradia'), 'Moradia'),
      (('cinema','jogo','lazer'), 'Lazer'),
      (('médico','medico','farmácia','farmacia','remédio','remedio'), 'Saúde'),
      (('cdb','poupança','poupanca','investi','investimento','ações','acoes','fii'), 'Investimento')]
    for words, category in rules:
        if any(w in t for w in words): return category
    return 'Outros'

def parse_message(text):
    t = text.lower().strip()
    amount = parse_amount(t)
    if not amount:
        return None, 'Não consegui identificar o valor. Exemplo: “Gastei R$ 25,90 no almoço”.'
    category = categorize(t)
    is_invest = any(w in t for w in ('investi', 'apliquei', 'cdb', 'poupança', 'poupanca', 'ações', 'acoes', 'fii'))
    is_income = any(w in t for w in ('recebi', 'salário', 'salario', 'ganhei', 'caiu na conta', 'dividendo', 'rendimento recebido'))
    is_expense = any(w in t for w in ('gastei', 'paguei', 'comprei', 'despesa', 'custou', 'pago'))
    if is_invest and not is_income:
        name = re.sub(r'\s+', ' ', text.strip())[:70]
        return {'kind':'investment','name':name,'amount':amount,'category':category}, None
    if is_income == is_expense:
        return None, 'Entendi o valor, mas não sei se é receita ou despesa. Escreva “recebi R$ 320 de salário” ou “gastei R$ 25 no almoço”.'
    kind = 'income' if is_income else 'expense'
    name = text.strip()
    # Remove common command prefix for cleaner labels.
    name = re.sub(r'^(gastei|paguei|comprei|recebi|ganhei|registra|registre)\s+', '', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip(' .,!')[:70] or category
    return {'kind':kind,'name':name[:1].upper()+name[1:],'amount':amount,'category':category}, None

def send_whatsapp(to, text):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        app.logger.warning('WhatsApp credentials are not configured; reply skipped.')
        return
    url = f'https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages'
    body = json.dumps({'messaging_product':'whatsapp','to':to,'type':'text','text':{'body':text}}).encode()
    req = urllib.request.Request(url, data=body, headers={'Authorization':f'Bearer {ACCESS_TOKEN}','Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response: response.read()
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        app.logger.error('Failed to send WhatsApp reply: %s', exc)

def process_incoming(sender, message_id, text):
    if not ALLOWED_PHONE or re.sub(r'\D','',sender) != ALLOWED_PHONE:
        app.logger.warning('Rejected message from non-allowlisted number.')
        return
    conn = db()
    try:
        conn.execute('INSERT INTO processed_messages(message_id) VALUES(?)', (message_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return # Webhook retry; don't record twice.
    conn.close()
    result, error = parse_message(text)
    if error:
        send_whatsapp(sender, error)
        return
    data = get_data()
    today = date.today().isoformat()
    if result['kind'] == 'investment':
        # Record the investment asset and the corresponding cash transfer so estimated net worth is not inflated.
        entry_id = int(__import__('time').time()*1000)
        data['invest'].append({'id': entry_id, 'name': result['name'], 'institution': 'Cadastro via WhatsApp', 'amount': result['amount']})
        data['tx'].append({'id': entry_id + 1, 'name': 'Aplicação: ' + result['name'][:55], 'category': 'Investimento', 'type': 'transfer', 'amount': result['amount'], 'date': today, 'account': 'WhatsApp'})
        set_data(data)
        send_whatsapp(sender, f"Investimento registrado: R$ {result['amount']:.2f}. A aplicação também foi registrada como transferência do saldo para evitar contar o mesmo dinheiro duas vezes. Confira o Nexus Finance.")
    else:
        data['tx'].append({'id':int(__import__('time').time()*1000),'name':result['name'],'category':result['category'],'type':result['kind'],'amount':result['amount'],'date':today,'account':'WhatsApp'})
        set_data(data)
        label = 'Receita' if result['kind']=='income' else 'Despesa'
        send_whatsapp(sender, f"{label} registrada: {result['name']} — R$ {result['amount']:.2f}. Categoria: {result['category']}. O Nexus Finance foi atualizado.")

@app.get('/webhook')
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge', '')
    if mode == 'subscribe' and VERIFY_TOKEN and hmac.compare_digest(token or '', VERIFY_TOKEN):
        return challenge, 200
    return 'Verificação inválida', 403

@app.post('/webhook')
def webhook():
    # Verify Meta's HMAC-SHA256 signature over the exact raw body. Never accept unsigned events.
    if not META_APP_SECRET:
        app.logger.error('META_APP_SECRET is not configured; refusing webhook.')
        return 'Webhook não configurado', 503
    signature = request.headers.get('X-Hub-Signature-256', '')
    raw_body = request.get_data(cache=True)
    expected = 'sha256=' + hmac.new(META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return 'Assinatura inválida', 403
    body = request.get_json(silent=True) or {}
    try:
        entries = body.get('entry', [])
        for entry in entries:
            for change in entry.get('changes', []):
                value = change.get('value', {})
                for msg in value.get('messages', []):
                    if msg.get('type') == 'text':
                        process_incoming(msg.get('from',''), msg.get('id',''), msg.get('text',{}).get('body',''))
    except Exception:
        app.logger.exception('Error processing WhatsApp webhook')
    return 'EVENT_RECEIVED', 200

if __name__ == '__main__':
    # Local-only development server. Do not expose this debug server directly to the internet.
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False)
