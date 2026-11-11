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
