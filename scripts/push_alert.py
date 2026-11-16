"""Send a GoonerGamble alert (Web Push) to every phone set up on board/site/alerts.html.

Runs from GitHub Actions (.github/workflows/alerts.yml) on each push to epa-model that changes a board page:
    python scripts/push_alert.py --from-commit "$COMMIT_MESSAGE"   # picks the sport from the run's commit message
or by hand:
    python scripts/push_alert.py nba "6 value legs, parlays ready" --delay 0

Phones are read from the GG_PUSH environment variable (a GitHub Actions repository secret): one or more alert codes (gg1....) separated by spaces,
commas or new lines, each made on the phone by alerts.html. A code carries that phone's push address and a
signing key made on the phone, so no shared server key or email is needed. It costs no Odds API credits.
Without GG_PUSH the script prints a note and exits 0, so runs never fail because of alerts.

Uses only `cryptography` and the standard library.
"""
import argparse, base64, json, os, re, struct, sys, time, urllib.error, urllib.parse, urllib.request

SITE = 'https://nfl-betting-model-u14v.onrender.com'
PAGES = {'nfl': '/?source=alert', 'nba': '/nba.html?source=alert', 'nhl': '/nhl.html?source=alert', 'bank': '/bank.html?source=alert'}
TITLES = {'nfl': 'NFL picks are up', 'nba': 'NBA picks are up', 'nhl': 'NHL picks are up', 'bank': 'Bank Builder updated'}


def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
def unb64u(s): return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def parse_codes(raw):
    out = []
    for tok in re.split(r'[\s,]+', raw or ''):
        if not tok: continue
        if not tok.startswith('gg1.'):
            print(f'push_alert: skipped a GG_PUSH entry that is not an alert code ({tok[:8]}...)'); continue
        try: out.append(json.loads(unb64u(tok[4:])))
        except Exception as e: print(f'push_alert: skipped an unreadable alert code ({e})')
    return out


def _ec():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec


def vapid_header(code, endpoint, now=None):
    """Authorization header (RFC 8292): an ES256 JWT signed with the phone-made key in the code."""
    ec = _ec()
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    pub = unb64u(code['k'])
    x, y = pub[1:33], pub[33:65]
    key = ec.EllipticCurvePrivateNumbers(int.from_bytes(unb64u(code['d']), 'big'),
                                         ec.EllipticCurvePublicNumbers(int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1())).private_key()
    u = urllib.parse.urlsplit(endpoint)
    claims = {'aud': f'{u.scheme}://{u.netloc}', 'exp': int((now or time.time()) + 12 * 3600), 'sub': SITE}
    signing = b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode()) + '.' + b64u(json.dumps(claims, separators=(',', ':')).encode())
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    return f'vapid t={signing}.{b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}, k={code["k"]}'


def _hkdf(salt, ikm, info, n):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(ikm)


def encrypt(payload, p256dh, auth, salt=None, sender_key=None):
    """Message encryption for Web Push (RFC 8291, aes128gcm content coding, RFC 8188), one record."""
    ec = _ec()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_pub = unb64u(p256dh)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    sk = sender_key or ec.generate_private_key(ec.SECP256R1())
    as_pub = sk.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = sk.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(unb64u(auth), shared, b'WebPush: info\x00' + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)   # 0x02 = last (only) record, no padding
    return salt + struct.pack('!IB', 4096, len(as_pub)) + as_pub + body


def send(code, msg, ttl=6 * 3600):
    data = encrypt(json.dumps(msg).encode(), code['p'], code['a'])
    req = urllib.request.Request(code['e'], data=data, method='POST', headers={
        'Authorization': vapid_header(code, code['e']), 'Content-Encoding': 'aes128gcm',
        'Content-Type': 'application/octet-stream', 'TTL': str(ttl), 'Urgency': 'normal', 'Topic': msg.get('tag', 'board')})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, ''
    except urllib.error.HTTPError as e: return e.code, e.read()[:200].decode('utf-8', 'replace')
    except Exception as e: return 0, str(e)


# which scheduled-run commits announce new picks (grading-only commits stay quiet)
COMMITS = [(r'^NBA board:', 'nba', "Today's NBA picks and parlays are up."),
           (r'^NHL board:', 'nhl', "Today's NHL picks and parlays are up."),
           (r'^Odds log: .*opener', 'nfl', "This week's NFL opener picks are up."),
           (r'^Odds log: .*Saturday props refresh', 'nfl', 'Sunday props refreshed with the latest lines and injuries.'),
           (r'^Game-day injuries:', 'nfl', 'Injury news re-priced some games before kickoff.')]


def from_commit(message):
    first = (message or '').strip().splitlines()[0] if (message or '').strip() else ''
    for pat, sport, body in COMMITS:
        if re.search(pat, first): return sport, body
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('sport', nargs='?', choices=sorted(PAGES))
    ap.add_argument('--from-commit', metavar='MESSAGE', help='choose sport and text from a scheduled run commit message; no alert for other commits')
    ap.add_argument('body', nargs='?', default='')
    ap.add_argument('--title')
    ap.add_argument('--delay', type=int, default=150, help='seconds to wait first so Render can publish the pushed board (default 150)')
    a = ap.parse_args(argv)
    if a.from_commit is not None:
        a.sport, body = from_commit(a.from_commit)
        if not a.sport:
            print('push_alert: not a new-picks commit, no alert'); return 0
        a.body = a.body or body
    if not a.sport: ap.error('give a sport or --from-commit')
    codes = parse_codes(os.environ.get('GG_PUSH', ''))
    if not codes:
        print('push_alert: GG_PUSH is not set, no alert sent (set it up from the bell page on the site, then add it as a GitHub Actions secret)'); return 0
    codes = [c for c in codes if a.sport == 'bank' or a.sport in c.get('s', 'nfl,nba,nhl').split(',')]
    if not codes:
        print(f'push_alert: no phone has {a.sport.upper()} alerts on'); return 0
    msg = {'title': a.title or 'GoonerGamble: ' + TITLES[a.sport], 'body': a.body or 'Tap to see the board.',
           'url': PAGES[a.sport], 'tag': a.sport}
    if a.delay > 0: time.sleep(a.delay)
    ok = 0
    for i, c in enumerate(codes, 1):
        st, why = send(c, msg)
        host = urllib.parse.urlsplit(c['e']).netloc
        if 200 <= st < 300: ok += 1; print(f'push_alert: phone {i} ({host}) sent')
        elif st in (404, 410): print(f'push_alert: phone {i} ({host}) is no longer subscribed: turn alerts on again on that phone and replace its code in GG_PUSH')
        elif st == 0: print(f'push_alert: phone {i} ({host}) not reached ({why})')
        else: print(f'push_alert: phone {i} ({host}) failed with HTTP {st}: {why}')
    print(f'push_alert: {ok}/{len(codes)} alerts sent')
    return 0


if __name__ == '__main__':
    sys.exit(main())
