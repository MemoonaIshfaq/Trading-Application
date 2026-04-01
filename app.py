from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
from datetime import datetime
import yfinance as yf

app = Flask(__name__)
app.secret_key = 'paper_trader_secret_key_2024'

DATA_FILE = 'portfolio_data.json'

# ─── Data Helpers ─────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        'users': {
            'demo': {
                'password': 'demo',
                'cash': 10000.0,
                'portfolio': {},          # symbol: quantity
                'transactions': []        # list of transaction dicts
            }
        }
    }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_price(symbol):
    """Fetch the latest price from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='1d')
        if hist.empty:
            return None
        return round(float(hist['Close'].iloc[-1]), 2)
    except Exception:
        return None

def get_historical(symbol, period='1y'):
    """Return list of {date, close} dicts for charting."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            return []
        return [
            {'date': str(idx.date()), 'close': round(float(row['Close']), 2)}
            for idx, row in hist.iterrows()
        ]
    except Exception:
        return []

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = load_data()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = data['users'].get(username)
        if user and user['password'] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = load_data()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('register.html', error='All fields required')
        if username in data['users']:
            return render_template('register.html', error='Username already taken')
        data['users'][username] = {
            'password': password,
            'cash': 10000.0,
            'portfolio': {},
            'transactions': []
        }
        save_data(data)
        session['username'] = username
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    data = load_data()
    user = data['users'][session['username']]
    portfolio_details = []
    total_value = user['cash']
    for symbol, qty in user['portfolio'].items():
        if qty > 0:
            price = get_price(symbol)
            val = round(price * qty, 2) if price else 0
            total_value += val
            portfolio_details.append({
                'symbol': symbol,
                'quantity': qty,
                'price': price,
                'value': val
            })
    return render_template('dashboard.html',
                           username=session['username'],
                           cash=round(user['cash'], 2),
                           portfolio=portfolio_details,
                           total_value=round(total_value, 2),
                           transactions=user['transactions'][-20:][::-1])

# ─── API: Quote ───────────────────────────────────────────────────────────────

@app.route('/api/quote/<symbol>')
def api_quote(symbol):
    symbol = symbol.upper()
    price = get_price(symbol)
    if price is None:
        return jsonify({'error': 'Symbol not found'}), 404
    history = get_historical(symbol, '3mo')
    return jsonify({'symbol': symbol, 'price': price, 'history': history})

# ─── API: Buy / Sell ──────────────────────────────────────────────────────────

@app.route('/api/trade', methods=['POST'])
def api_trade():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    body = request.get_json()
    action = body.get('action', '').lower()   # 'buy' or 'sell'
    symbol = body.get('symbol', '').upper()
    try:
        qty = int(body.get('quantity', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid quantity'}), 400

    if action not in ('buy', 'sell') or qty <= 0 or not symbol:
        return jsonify({'error': 'Invalid request'}), 400

    price = get_price(symbol)
    if price is None:
        return jsonify({'error': 'Symbol not found'}), 404

    data = load_data()
    user = data['users'][session['username']]
    cost = round(price * qty, 2)

    if action == 'buy':
        if user['cash'] < cost:
            return jsonify({'error': 'Insufficient funds'}), 400
        user['cash'] = round(user['cash'] - cost, 2)
        user['portfolio'][symbol] = user['portfolio'].get(symbol, 0) + qty

    else:  # sell
        held = user['portfolio'].get(symbol, 0)
        if held < qty:
            return jsonify({'error': f'You only hold {held} shares'}), 400
        user['cash'] = round(user['cash'] + cost, 2)
        user['portfolio'][symbol] = held - qty
        if user['portfolio'][symbol] == 0:
            del user['portfolio'][symbol]

    user['transactions'].append({
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'action': action.upper(),
        'symbol': symbol,
        'quantity': qty,
        'price': price,
        'total': cost
    })

    save_data(data)
    return jsonify({
        'success': True,
        'action': action,
        'symbol': symbol,
        'quantity': qty,
        'price': price,
        'total': cost,
        'new_cash': user['cash']
    })

# ─── API: Portfolio value history (simple) ────────────────────────────────────

@app.route('/api/portfolio_chart')
def portfolio_chart():
    """Return daily portfolio value for the last year based on transactions."""
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    # Simplified: just return the current breakdown
    data = load_data()
    user = data['users'][session['username']]
    breakdown = []
    for symbol, qty in user['portfolio'].items():
        if qty > 0:
            price = get_price(symbol)
            if price:
                breakdown.append({'symbol': symbol, 'value': round(price * qty, 2)})
    breakdown.append({'symbol': 'Cash', 'value': round(user['cash'], 2)})
    return jsonify(breakdown)

if __name__ == '__main__':
    app.run(debug=True)
