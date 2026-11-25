"""Fetches FX, world gold and EGX prices from EODHD and saves them to prices.json.
Runs on GitHub Actions at 9:00 and 15:30 Cairo time (see .github/workflows/update-prices.yml).
Settings live in config.json. The EODHD key comes from the EODHD_KEY repository secret."""
import datetime, json, os, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo('Africa/Cairo')
BASE = os.environ.get('EODHD_BASE', 'https://eodhd.com/api').rstrip('/')
KEY = os.environ.get('EODHD_KEY', '').strip()
now = datetime.datetime.fromisoformat(os.environ['NOW']).astimezone(CAIRO) if os.environ.get('NOW') else datetime.datetime.now(CAIRO)  # NOW: for testing
today = now.strftime('%Y-%m-%d')
manual = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' or '--force' in sys.argv

def load(path, default):
    try:
        with open(path, encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: return default

cfg = load('config.json', {})
feed = load('prices.json', {})
feed.setdefault('days', {}); feed.setdefault('runs', [])

minutes = now.hour * 60 + now.minute
slot = 'close' if minutes >= 15 * 60 + 30 else 'morning' if minutes >= 9 * 60 else None
if not manual:
    # Cron fires at two UTC times per slot so it works in winter and summer time; only one run per slot per day does the work.
    if slot is None:
        print('Before 9:00 Cairo time; nothing to do.'); sys.exit(0)
    if any(r.get('date') == today and r.get('slot') == slot and r.get('ok') for r in feed['runs']):
        print(f'The {slot} update already ran today.'); sys.exit(0)
slot = slot or 'manual'

ex = cfg.get('exchange', 'EGX')
sym = {'usd': cfg.get('usd', 'USDEGP.FOREX'), 'aed': cfg.get('aed', 'AEDEGP.FOREX'), 'xau': cfg.get('gold', 'XAUUSD.FOREX')}
stock_codes = {t.strip().upper(): f"{t.strip().upper()}.{ex}" for t in cfg.get('stocks', []) if t.strip()}
stock_codes.update({k.strip().upper(): v.strip().upper() for k, v in (cfg.get('extra') or {}).items() if k.strip() and v.strip()})
symbols = list(dict.fromkeys(list(sym.values()) + list(stock_codes.values())))

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json'}), timeout=30) as r:
        return json.loads(r.read().decode())

def cairo_date(ts):
    try: return datetime.datetime.fromtimestamp(int(ts), CAIRO).strftime('%Y-%m-%d')
    except Exception: return ''

quotes, errors, warnings = {}, [], []
if not KEY:
    errors.append('EODHD_KEY secret is missing')
else:
    token = urllib.parse.quote(KEY)
    if cfg.get('useLatestQuotes', True) and symbols:
        try:
            first, rest = symbols[0], symbols[1:]
            url = f"{BASE}/real-time/{urllib.parse.quote(first)}?fmt=json&api_token={token}" + (f"&s={','.join(urllib.parse.quote(s) for s in rest)}" if rest else '')
            data = get(url)
            for row in data if isinstance(data, list) else [data]:
                if not isinstance(row, dict) or not row.get('code'): continue
                price = row.get('close')
                try: price = float(price)
                except (TypeError, ValueError): price = 0
                if price <= 0:
                    try: price = float(row.get('previousClose'))
                    except (TypeError, ValueError): price = 0
                if price > 0: quotes[str(row['code']).upper()] = {'price': price, 'date': cairo_date(row.get('timestamp'))}
        except Exception as e:
            errors.append(f'Latest quotes: {e}')
    since = (now - datetime.timedelta(days=14)).strftime('%Y-%m-%d')
    for s in symbols:
        if s in quotes: continue
        try:
            rows = get(f"{BASE}/eod/{urllib.parse.quote(s)}?fmt=json&order=d&from={since}&api_token={token}")
            row = next((r for r in rows if float(r.get('close') or 0) > 0), None) if isinstance(rows, list) else None
            if row: quotes[s] = {'price': float(row['close']), 'date': str(row.get('date', ''))}
            else: errors.append(f'{s}: no recent price')
        except Exception as e:
            errors.append(f'{s}: {e}')

# Start from the latest saved day so anything missing today keeps its last known value.
prev_days = sorted(d for d in feed['days'] if d <= today)
prev = feed['days'][prev_days[-1]] if prev_days else {}
day = {'usd': prev.get('usd'), 'aed': prev.get('aed'), 'xau': prev.get('xau'),
       'prices': dict(prev.get('prices', {})), 'priceDates': dict(prev.get('priceDates', {}))}
for k, s in sym.items():
    if s in quotes: day[k] = round(quotes[s]['price'], 4)
    elif s: warnings.append(f'{s} not received; kept {day.get(k)}')
if sym['aed'] not in quotes and sym['usd'] in quotes:
    day['aed'] = round(quotes[sym['usd']]['price'] / 3.6725, 4); warnings.append('AED/EGP worked out from USD/EGP ÷ 3.6725')
for ticker, s in stock_codes.items():
    if s in quotes:
        day['prices'][ticker] = round(quotes[s]['price'], 4); day['priceDates'][ticker] = quotes[s]['date'] or today
    else: warnings.append(f'{ticker} not received; kept {day["prices"].get(ticker)}')
day['prices'] = {k: v for k, v in day['prices'].items() if k in stock_codes}
day['priceDates'] = {k: v for k, v in day['priceDates'].items() if k in stock_codes}

ok = len(quotes) > 0 and bool(day.get('usd'))
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
if ok:
    day.update({'slot': slot, 'updatedAt': stamp})
    feed['days'][today] = day
    keep = sorted(feed['days'])[-400:]
    feed['days'] = {d: feed['days'][d] for d in keep}
feed['runs'] = (feed['runs'] + [{'ts': int(datetime.datetime.now().timestamp() * 1000), 'date': today, 'slot': slot, 'ok': ok,
                                 'received': len(quotes), 'requested': len(symbols), 'errors': errors[:5], 'warnings': warnings[:5]}])[-60:]
feed['updatedAt'] = stamp
feed['config'] = {'exchange': ex, 'usd': sym['usd'], 'aed': sym['aed'], 'gold': sym['xau'], 'useLatestQuotes': cfg.get('useLatestQuotes', True)}
with open('prices.json', 'w', encoding='utf-8') as f:
    json.dump(feed, f, ensure_ascii=False, indent=1, sort_keys=True)
print(f"{slot}: {len(quotes)} of {len(symbols)} prices", '; '.join(errors))
if not ok: sys.exit(1)
