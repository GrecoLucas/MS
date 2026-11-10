"""Minute-based baseline. Demand parameters are assumptions, not fitted data."""

import csv
import math
from pathlib import Path

import mesa


def distance_km(a, b):
    """Great-circle distance between two stations."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))


class StationAgent(mesa.Agent):
    def __init__(self, model, row, occupancy):
        super().__init__(model)
        self.station_id = row['id']
        self.name = row['name']
        self.lat, self.lon = float(row['lat']), float(row['lon'])
        self.capacity = int(row['bike_racks'])
        self.bikes = int(self.capacity * occupancy)
        self.requests = self.pickups = self.failed_pickups = 0
        self.failed_returns = self.empty_minutes = self.full_minutes = 0


class UserAgent(mesa.Agent):
    """An active trip carrying exactly one bike until successful docking."""

    def __init__(self, model, origin, destination):
        super().__init__(model)
        self.destination = destination
        self.arrival_minute = model.minute + model.travel_minutes(origin, destination)

    def step(self):
        if self.model.minute < self.arrival_minute:
            return
        station = self.destination
        if station.bikes < station.capacity:
            station.bikes += 1
            self.model.completed_trips += 1
            self.remove()
            return
        station.failed_returns += 1
        self.model.failed_returns += 1
        # Full stations can change while travelling: retry docking on arrival.
        alternatives = [s for s in self.model.stations if s is not station and s.bikes < s.capacity]
        if alternatives:
            self.destination = min(alternatives, key=lambda s: distance_km(station, s))
            self.arrival_minute = self.model.minute + self.model.travel_minutes(station, self.destination)
        else:
            self.arrival_minute = self.model.minute + 1


class BikeSharingModel(mesa.Model):
    def __init__(self, city_id='442', data_path=None, occupancy=0.5,
                 demand_rate=0.02, speed_kmh=15, seed=42):
        if not 0 <= occupancy <= 1:
            raise ValueError('occupancy must be between 0 and 1')
        if not math.isfinite(demand_rate) or demand_rate < 0:
            raise ValueError('demand_rate must be finite and non-negative')
        if not math.isfinite(speed_kmh) or speed_kmh <= 0:
            raise ValueError('speed_kmh must be finite and positive')
        path = Path(data_path) if data_path else Path(__file__).resolve().parents[1] / 'data' / 'stations.csv'
        with path.open(encoding='utf-8', newline='') as source:
            rows = sorted((r for r in csv.DictReader(source) if r['city_id'] == str(city_id)), key=lambda r: r['id'])
        if len(rows) < 2:
            raise ValueError('Choose a city with at least two stations')
        if any(int(r['bike_racks'] or 0) <= 0 for r in rows):
            raise ValueError('Selected city has missing or zero capacities; review these stations first')
        super().__init__(seed=seed)
        self.city_id = str(city_id)
        self.minute = 0
        self.demand_rate, self.speed_kmh = demand_rate, speed_kmh
        self.requests = self.served = self.failed_pickups = 0
        self.completed_trips = self.failed_returns = 0
        self.stations = [StationAgent(self, row, occupancy) for row in rows]
        self.fleet_size = sum(s.bikes for s in self.stations)
        self.datacollector = mesa.DataCollector(model_reporters={
            'minute': 'minute', 'requests': 'requests', 'served': 'served',
            'failed_pickups': 'failed_pickups', 'completed_trips': 'completed_trips',
            'failed_returns': 'failed_returns',
            'bikes_at_stations': lambda m: sum(s.bikes for s in m.stations),
            'bikes_in_use': lambda m: len(m.agents_by_type.get(UserAgent, [])),
            'empty_stations': lambda m: sum(s.bikes == 0 for s in m.stations),
            'full_stations': lambda m: sum(s.bikes == s.capacity for s in m.stations),
        })
        self.datacollector.collect(self)

    def travel_minutes(self, origin, destination):
        return max(1, math.ceil(distance_km(origin, destination) / self.speed_kmh * 60))

    def step(self):
        self.minute += 1
        # Snapshot: successful returns remove users from Mesa's agent registry.
        users = self.agents_by_type.get(UserAgent)
        if users is not None:
            users.shuffle_do('step')
        stations = self.random.sample(self.stations, len(self.stations))
        for station in stations:
            arrivals = int(self.rng.poisson(self.demand_rate))
            for _ in range(arrivals):
                self.requests += 1
                station.requests += 1
                if station.bikes == 0:
                    self.failed_pickups += 1
                    station.failed_pickups += 1
                    continue
                destination = self.random.choice([s for s in self.stations if s is not station])
                station.bikes -= 1
                station.pickups += 1
                self.served += 1
                UserAgent(self, station, destination)
        for station in self.stations:
            station.empty_minutes += station.bikes == 0
            station.full_minutes += station.bikes == station.capacity
        self.check_invariants()
        self.datacollector.collect(self)

    def check_invariants(self):
        if any(not 0 <= s.bikes <= s.capacity for s in self.stations):
            raise RuntimeError('Station capacity violated')
        in_use = len(self.agents_by_type.get(UserAgent, []))
        if sum(s.bikes for s in self.stations) + in_use != self.fleet_size:
            raise RuntimeError('Bike conservation violated')
        if self.requests != self.served + self.failed_pickups or self.served != self.completed_trips + in_use:
            raise RuntimeError('Trip accounting violated')

    def export(self, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.datacollector.get_model_vars_dataframe().to_csv(output_dir / 'metrics.csv', index=False)
        fields = ['station_id', 'name', 'lat', 'lon', 'capacity', 'bikes', 'requests',
                  'pickups', 'failed_pickups', 'failed_returns', 'empty_minutes', 'full_minutes']
        with (output_dir / 'stations.csv').open('w', encoding='utf-8', newline='') as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: getattr(s, key) for key in fields} for s in self.stations)
