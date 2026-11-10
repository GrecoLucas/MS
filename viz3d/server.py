"""Web server of the 3D viewer. Run with: python -m viz3d

The browser draws the scene; this process owns the Mesa model and advances it on request.
Only the Python standard library is used.
"""

import argparse
import json
import math
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bike_sharing.agents import UserAgent
from bike_sharing.demand import Weather
from bike_sharing.model import BikeSharingModel
from bike_sharing.policies import POLICIES

STATIC = Path(__file__).with_name('static')
MAX_STEP = 240

# Scenario options the page may change: name -> (type, default, minimum, maximum).
OPTIONS = {
    'occupancy': (float, 0.5, 0.05, 1.0),
    'demand_rate': (float, 0.04, 0.0, 0.2),
    'vehicles': (int, 1, 0, 4),
    'vehicle_capacity': (int, 10, 2, 30),
    'incentive_discount': (float, 0.0, 0.0, 1.0),
    'virtual_zones': (int, 0, 0, 5),
    'capacity_scale': (float, 1.0, 0.5, 2.0),
    'failure_rate': (float, 0.004, 0.0, 0.1),
    'price_minute': (float, 0.05, 0.0, 0.5),
    'mean_temperature': (float, 15.0, -10.0, 40.0),
    'maintenance_threshold': (int, 3, 0, 20),
    'start_weekday': (int, 0, 0, 6),
    'seed': (int, 42, 0, 10 ** 6),
}
CHOICES = {'rebalancing': POLICIES, 'weather': ('dynamic',) + Weather.STATES}
DEFAULTS = {**{name: spec[1] for name, spec in OPTIONS.items()},
            'rebalancing': 'threshold', 'weather': 'dynamic', 'start_hour': 6.5}


def clean(raw):
    """Keep only known options, converted and clamped to their valid range."""
    params = dict(DEFAULTS)
    for name, (kind, _, low, high) in OPTIONS.items():
        if name in raw:
            params[name] = min(high, max(low, kind(raw[name])))
    for name, allowed in CHOICES.items():
        if raw.get(name) in allowed:
            params[name] = raw[name]
    if 'start_hour' in raw:
        params['start_hour'] = min(23.0, max(0.0, float(raw['start_hour'])))
    return params


class Simulation:
    """The model shown in the browser, guarded by a lock (one request at a time)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset({})

    def reset(self, raw):
        self.params = clean(raw)
        options = {k: v for k, v in self.params.items() if k != 'start_hour'}
        self.model = BikeSharingModel(**options)
        for _ in range(round(self.params['start_hour'] * 60)):  # skip the quiet night
            self.model.step()

    def step(self, minutes):
        for _ in range(min(MAX_STEP, max(1, int(minutes)))):
            self.model.step()

    def snapshot(self):
        model = self.model
        lat0, lon0 = model.depot.lat, model.depot.lon
        east = 111.32 * math.cos(math.radians(lat0))

        def position(place):
            return round((place.lon - lon0) * east, 4), round((place.lat - lat0) * 110.57, 4)

        stations = []
        for s in model.stations:
            x, y = position(s)
            decided = s.served + s.failed_pickups
            stations.append({
                'name': s.name, 'kind': s.kind, 'zone': s.zone, 'x': x, 'y': y,
                'capacity': s.capacity, 'available': s.available, 'broken': len(s.broken),
                'waiting': len(s.queue), 'requests': s.requests, 'served': s.served,
                'unmet': s.failed_pickups, 'failed_returns': s.failed_returns,
                'service': s.served / decided if decided else None,
                'needs': bool(model.needs_bikes(s)), 'crowded': bool(model.is_crowded(s)),
                'empty_share': s.empty_minutes / max(1, model.minute),
                'full_share': s.full_minutes / max(1, model.minute),
            })
        users = [{'id': u.unique_id, 'state': u.state, 'profile': u.profile.name,
                  'from': u.move_from.index, 'to': u.move_to.index, 't0': u.t0, 't1': u.t1}
                 for u in model.agents_by_type.get(UserAgent, []) if u.state in ('riding', 'walking')]
        vehicles = [{'id': v.unique_id, 'state': v.state, 'from': v.move_from.index,
                     'to': v.target.index if v.state == 'moving' else v.location.index,
                     't0': v.t0, 't1': v.t1, 'cargo': len(v.cargo), 'broken': len(v.broken),
                     'capacity': v.capacity,
                     'task': v.task.action if v.task and v.state != 'idle' else 'idle'}
                    for v in model.vehicles]
        depot = model.depot
        return {
            'minute': model.minute, 'clock': model.clock, 'hour': model.minute / 60 % 24,
            'weekend': model.weekday >= 5, 'weather': model.weather.condition,
            'temperature': round(model.weather.temperature, 1),
            'demand_now': model.demand.total_rate(model.minute, model.demand_factor()) * 60,
            'params': self.params, 'stations': stations, 'users': users, 'vehicles': vehicles,
            'depot': {'stock': len(depot.stock), 'repairing': len(depot.repairing),
                      'queue': len(depot.waiting)},
            'kpi': {**model.summary(), 'bikes_in_use': model.riding,
                    'users_waiting': sum(len(s.queue) for s in model.stations),
                    'broken_at_stations': sum(len(s.broken) for s in model.stations)},
        }


class Handler(SimpleHTTPRequestHandler):
    simulation = None

    def log_message(self, *args):
        pass  # keep the terminal quiet

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] == '/api/state':
            with self.simulation.lock:
                return self._json(self.simulation.snapshot())
        super().do_GET()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            data = json.loads(self.rfile.read(length) or b'{}')
            with self.simulation.lock:
                if self.path == '/api/step':
                    self.simulation.step(data.get('minutes', 1))
                elif self.path == '/api/reset':
                    self.simulation.reset(data)
                else:
                    return self._json({'error': 'unknown endpoint'}, 404)
                return self._json(self.simulation.snapshot())
        except (ValueError, TypeError, AttributeError) as error:
            self._json({'error': str(error)}, 400)


def main():
    parser = argparse.ArgumentParser(description='Low-poly 3D viewer of the bike-sharing simulation.')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--no-browser', action='store_true', help='do not open the browser')
    args = parser.parse_args()
    Handler.simulation = Simulation()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(STATIC)))
    url = f'http://localhost:{args.port}'
    print(f'3D viewer running at {url}  (Ctrl+C to stop)')
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
