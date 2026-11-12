"""Game-time weather from Open-Meteo (free, no key): wind, rain and temperature at outdoor stadiums.

Past games use the Open-Meteo archive; upcoming games (up to ~2 weeks out) use the forecast.
Values are averaged over the 3 hours from kickoff. Domes and closed roofs get calm, dry, 70°F.
"""
import os, json, time, urllib.request, urllib.parse
import numpy as np, pandas as pd
from .model import G

CACHE = os.path.join(os.path.dirname(__file__), '..', 'data', 'weather.csv')
STADIUMS = {  # stadium_id: (lat, lon)
    'ATL97': (33.7554, -84.4008), 'BAL00': (39.2780, -76.6227), 'BOS00': (42.0909, -71.2643), 'BUF00': (42.7738, -78.7870),
    'CAR00': (35.2258, -80.8528), 'CHI98': (41.8623, -87.6167), 'CIN00': (39.0955, -84.5161), 'CLE00': (41.5061, -81.6995),
    'DAL00': (32.7473, -97.0945), 'DEN00': (39.7439, -105.0201), 'GNB00': (44.5013, -88.0622), 'HOU00': (29.6847, -95.4107),
    'IND00': (39.7601, -86.1639), 'JAX00': (30.3239, -81.6373), 'KAN00': (39.0489, -94.4839), 'LAX97': (33.8644, -118.2611),
    'LAX99': (34.0141, -118.2879), 'LAX01': (33.9535, -118.3392), 'MIA00': (25.9580, -80.2389), 'NAS00': (36.1665, -86.7713),
    'NYC01': (40.8135, -74.0745), 'OAK00': (37.7516, -122.2005), 'PHI00': (39.9008, -75.1675), 'PHO00': (33.5276, -112.2626),
    'PIT00': (40.4468, -80.0158), 'SEA00': (47.5952, -122.3316), 'SFO01': (37.4030, -121.9700), 'TAM00': (27.9759, -82.5033),
    'WAS00': (38.9076, -76.8645), 'LON00': (51.5560, -0.2796), 'LON01': (51.4560, -0.3415), 'LON02': (51.6043, -0.0664),
    'FRA00': (50.0686, 8.6455), 'GER00': (48.2188, 11.6247), 'MUN01': (48.2188, 11.6247), 'MEX00': (19.3029, -99.1505),
    'SAO00': (-23.5455, -46.4742), 'RIO00': (-22.9122, -43.2302), 'MEL00': (-37.8200, 144.9834), 'PAR00': (48.9245, 2.3601),
    'MAD01': (40.4531, -3.6883),
}
INDOOR = {'dome', 'closed'}
HOURLY = 'wind_speed_10m,precipitation,temperature_2m'


def _get(url, params):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f'{url}?{urllib.parse.urlencode(params)}', timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2 ** attempt)
    return None


def _series(lat, lon, start, end, forecast):
    p = {'latitude': lat, 'longitude': lon, 'hourly': HOURLY, 'wind_speed_unit': 'mph', 'temperature_unit': 'fahrenheit',
         'precipitation_unit': 'mm', 'timezone': 'GMT', 'start_date': start, 'end_date': end}
    url = 'https://api.open-meteo.com/v1/forecast' if forecast else 'https://archive-api.open-meteo.com/v1/archive'
    j = _get(url, p)
    if not j or 'hourly' not in j:
        return pd.DataFrame()
    h = pd.DataFrame(j['hourly']); h['time'] = pd.to_datetime(h.time)
    return h


def kickoff_utc(g):
    t = pd.to_datetime(g.gameday.astype(str) + ' ' + g.gametime.fillna('13:00'))
    return t.dt.tz_localize('America/New_York', ambiguous='NaT', nonexistent='shift_forward').dt.tz_convert('UTC').dt.tz_localize(None)


def build(games=None, refresh_future=True):
    g = (G if games is None else games)
    g = g[g.game_type == 'REG'][['game_id', 'season', 'gameday', 'gametime', 'stadium_id', 'roof', 'result']].copy()
    g['ko'] = kickoff_utc(g)
    old = pd.read_csv(CACHE) if os.path.exists(CACHE) else pd.DataFrame(columns=['game_id'])
    # keep cached rows for finished games; refetch upcoming ones (forecasts change)
    keep = old[old.game_id.isin(g[g.result.notna()].game_id)] if len(old) else old
    todo = g[~g.game_id.isin(keep.game_id) & g.stadium_id.isin(STADIUMS) & ~g.roof.isin(INDOOR)]
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    rows = []
    for (sid, season, fut), d in todo.groupby(['stadium_id', 'season', d_fut := todo.ko >= today - pd.Timedelta(days=5)]):
        if fut and (d.ko.min() > today + pd.Timedelta(days=15)):
            continue
        lat, lon = STADIUMS[sid]
        print(sid, season, "forecast" if fut else "archive", flush=True)
        h = _series(lat, lon, d.ko.min().strftime('%Y-%m-%d'), (d.ko.max() + pd.Timedelta(hours=4)).strftime('%Y-%m-%d'), fut)
        if h.empty:
            continue
        for r in d.itertuples():
            w = h[(h.time >= r.ko.floor('h')) & (h.time < r.ko.floor('h') + pd.Timedelta(hours=3))]
            if len(w):
                rows.append({'game_id': r.game_id, 'wx_wind': w.wind_speed_10m.mean(), 'wx_precip': w.precipitation.sum(),
                             'wx_temp': w.temperature_2m.mean(), 'wx_source': 'forecast' if fut else 'archive'})
    out = pd.concat([keep, pd.DataFrame(rows)], ignore_index=True).drop_duplicates('game_id', keep='last')
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    out.to_csv(CACHE, index=False)
    return out


def features(game_ids):
    """Weather features for the total model; indoor or unknown games get neutral values."""
    w = pd.read_csv(CACHE) if os.path.exists(CACHE) else pd.DataFrame(columns=['game_id', 'wx_wind', 'wx_precip', 'wx_temp'])
    f = pd.DataFrame({'game_id': list(game_ids)}).merge(w, on='game_id', how='left')
    f['wx_wind'] = f.wx_wind.fillna(0.0)
    f['wx_precip'] = f.wx_precip.fillna(0.0)
    f['wx_temp'] = f.wx_temp.fillna(70.0)
    f['wind_over12'] = (f.wx_wind - 12).clip(lower=0)      # wind hurts passing and kicking mostly above ~12 mph
    f['rain'] = (f.wx_precip >= 1.0).astype(float)
    f['cold'] = (40 - f.wx_temp).clip(lower=0)
    return f[['game_id', 'wx_wind', 'wind_over12', 'rain', 'cold']]


# ---- weather adjustments for player props (fit by scripts/weather_props_backtest.py) ----
PROPS_FILE = os.path.join(os.path.dirname(__file__), '..', 'odds_log', 'weather_props.json')
FORECAST_FILE = os.path.join(os.path.dirname(__file__), '..', 'odds_log', 'weather_forecast.csv')
STAT_NAMES = {'pass': 'pass yds', 'rec': 'rec yds', 'recs': 'catches', 'rush': 'rush yds', 'td': 'TD chance'}


def prop_weather(games):
    """Game-time weather and prop multipliers for upcoming games (rows of games.csv).

    Weather: the Open-Meteo forecast when it can be fetched (rain = 1+ mm over the 3 hours from kickoff), otherwise
    odds_log/weather_forecast.csv (rain = its chance of rain, so 70% counts as 0.7 of a rainy game). Domes and closed
    roofs are neutral. Multipliers use only the backtest effects whose 90% interval excludes zero:
    exp(wind_coef * (wind - 12)+/5 + rain_coef * rain + cold_coef * (40 - temp)+/10).
    """
    coefs = json.load(open(PROPS_FILE)) if os.path.exists(PROPS_FILE) else {}
    g = games[['game_id', 'roof', 'stadium_id', 'gameday', 'gametime', 'season', 'game_type', 'result']].copy()
    last_roof = G[G.roof.notna()].sort_values('gameday').groupby('stadium_id').roof.last()   # upcoming games often have no roof yet
    g['roof'] = g.roof.fillna(g.stadium_id.map(last_roof))
    src = pd.DataFrame(columns=['game_id', 'wind', 'rain', 'temp', 'src'])
    try:   # forecast for just these games (does not touch the history cache)
        g['ko'] = kickoff_utc(g); rows = []
        for sid, d in g[g.stadium_id.isin(STADIUMS) & ~g.roof.isin(INDOOR)].groupby('stadium_id'):
            h = _series(*STADIUMS[sid], d.ko.min().strftime('%Y-%m-%d'), (d.ko.max() + pd.Timedelta(hours=4)).strftime('%Y-%m-%d'), True)
            if h.empty and not rows:
                print('Open-Meteo forecast unreachable; using odds_log/weather_forecast.csv'); break
            for r in d.itertuples():
                w = h[(h.time >= r.ko.floor('h')) & (h.time < r.ko.floor('h') + pd.Timedelta(hours=3))] if len(h) else h
                if len(w):
                    rows.append({'game_id': r.game_id, 'wind': w.wind_speed_10m.mean(), 'rain': min(1.0, w.precipitation.sum()),
                                 'temp': w.temperature_2m.mean(), 'src': 'Open-Meteo forecast'})
        if rows: src = pd.DataFrame(rows)
    except Exception as e:
        print('weather forecast unavailable:', e)
    if os.path.exists(FORECAST_FILE):
        f = pd.read_csv(FORECAST_FILE).drop_duplicates('game_id', keep='last')
        f = f[f.game_id.isin(g.game_id) & ~f.game_id.isin(src.game_id)]
        src = pd.concat([src, pd.DataFrame({'game_id': f.game_id, 'wind': f.wind_mph, 'rain': f.precip_pct / 100.0, 'temp': f.temp_f,
                                            'src': 'forecast (' + f.source.astype(str) + ')'})], ignore_index=True)
    out = g[['game_id', 'roof']].merge(src, on='game_id', how='left')
    for c in ['wind', 'rain', 'temp']:
        out[c] = pd.to_numeric(out[c], errors='coerce').astype(float)
    indoor = out.roof.isin(INDOOR)
    out.loc[indoor, ['wind', 'rain', 'temp']] = [0.0, 0.0, 70.0]; out.loc[indoor, 'src'] = 'indoors'
    known = out.wind.notna()
    x = {'wind12': ((out.wind - 12).clip(lower=0) / 5).fillna(0), 'rain': out.rain.fillna(0), 'cold': ((40 - out.temp).clip(lower=0) / 10).fillna(0)}
    notes = [[] for _ in range(len(out))]
    for stat in STAT_NAMES:
        lm = np.zeros(len(out))
        for k, c in coefs.get(stat, {}).get('coef', {}).items():
            if c['use']:
                lm = lm + c['est'] * x[k].values
        out[f'm_{stat}'] = np.exp(lm)
        for i, m in enumerate(out[f'm_{stat}']):
            if abs(m - 1) >= 0.01:
                notes[i].append(f'{STAT_NAMES[stat]} {(m - 1) * 100:+.0f}%')
    def desc(r):
        if r.src == 'indoors': return 'Indoors'
        if r.wind != r.wind: return 'No forecast yet'
        bits = [f'{r.wind:.0f} mph wind', f'{r.temp:.0f}°F']
        if r.rain >= 0.2: bits.insert(1, f'rain {r.rain * 100:.0f}%' if 'Open-Meteo' not in r.src else 'rain')
        return ', '.join(bits)
    out['desc'] = [desc(r) for r in out.itertuples()]
    out['note'] = [', '.join(n) for n in notes]
    out['known'] = known
    return out
