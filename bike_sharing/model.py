"""Minute-based bike-sharing model. Demand and cost parameters are assumptions, not fitted data."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import mesa
import numpy as np

from .agents import Bike, DepotAgent, StationAgent, UserAgent, VehicleAgent
from .demand import PROFILES, ZONES, DemandModel, Weather
from .policies import Dispatcher

DETOUR = 1.3        # streets are longer than the straight line
WALK_KMH = 4.8
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


@dataclass(frozen=True)
class Economics:
    """Cost assumptions in euros."""

    vehicle_km: float = 0.30      # energy and wear of the electric van
    vehicle_hour: float = 14.0    # driver, only while the van is working
    vehicle_day: float = 35.0     # fixed cost of owning one van
    bike_day: float = 0.60        # depreciation of one bike
    dock_day: float = 0.15        # upkeep of one dock or virtual parking place
    repair: float = 12.0          # parts and labour for one repair
    reference_trip_minutes: float = 15.0  # trip used to measure price changes
    reference_unlock: float = 1.0
    reference_minute: float = 0.05


def distance_km(a, b):
    """Great-circle distance between two places."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))


class BikeSharingModel(mesa.Model):
    def __init__(self, city_id='442', data_path=None, occupancy=0.5, demand_rate=0.04,
                 speed_kmh=15, seed=42, *, fleet_size=None, capacity_scale=1.0, virtual_zones=0,
                 virtual_capacity=10, asymmetry=2.5, weather='dynamic', mean_temperature=15.0,
                 start_weekday=0, rebalancing='none', vehicles=1, vehicle_capacity=10,
                 vehicle_speed_kmh=25, low_threshold=0.2, high_threshold=0.85,
                 rebalance_interval=360, maintenance_threshold=3, failure_rate=0.004,
                 repair_minutes=90, price_unlock=1.0, price_minute=0.05,
                 incentive_discount=0.0, economics=None):
        if not 0 <= occupancy <= 1:
            raise ValueError('occupancy must be between 0 and 1')
        if not math.isfinite(demand_rate) or demand_rate < 0:
            raise ValueError('demand_rate must be finite and non-negative')
        if not math.isfinite(speed_kmh) or speed_kmh <= 0:
            raise ValueError('speed_kmh must be finite and positive')
        if not 0 <= incentive_discount <= 1:
            raise ValueError('incentive_discount must be between 0 and 1')
        if not 0 <= low_threshold < high_threshold <= 1:
            raise ValueError('thresholds must satisfy 0 <= low < high <= 1')
        if capacity_scale <= 0 or vehicles < 0 or vehicle_capacity < 1 or rebalance_interval < 1:
            raise ValueError('capacity_scale, vehicle_capacity and rebalance_interval must be positive')
        if min(price_unlock, price_minute, failure_rate, asymmetry) < 0 or virtual_zones < 0:
            raise ValueError('prices, failure_rate, asymmetry and virtual_zones cannot be negative')
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
        self.start_weekday = start_weekday % 7
        self.demand_rate, self.speed_kmh = demand_rate, speed_kmh
        self.low_threshold, self.high_threshold = low_threshold, high_threshold
        self.failure_rate, self.stop_minutes = failure_rate, 3
        self.price_unlock, self.price_minute = price_unlock, price_minute
        self.incentive_discount = incentive_discount
        self.economics = economics or Economics()
        self.rebalancing = rebalancing

        # Counters (all cumulative).
        self.requests = self.served = self.failed_pickups = 0
        self.completed_trips = self.failed_returns = self.redirected_trips = 0
        self.wait_minutes = self.waited_users = self.walk_minutes_total = 0
        self.ride_minutes_total = self.incentive_trips = 0
        self.failures = self.repairs = self.broken_collected = self.bikes_moved = 0
        self.revenue = self.incentive_cost = 0.0

        # Parking locations, zones and distances.
        self.stations = [StationAgent(self, row, capacity_scale=capacity_scale) for row in rows]
        centre_lat = sum(s.lat for s in self.stations) / len(self.stations)
        centre_lon = sum(s.lon for s in self.stations) / len(self.stations)
        self.depot = DepotAgent(self, centre_lat, centre_lon, capacity=sum(s.capacity for s in self.stations),
                                repair_minutes=repair_minutes, workshops=2)
        self._add_virtual_zones(virtual_zones, virtual_capacity)
        by_distance = sorted((s for s in self.stations if s.kind == 'station'),
                             key=lambda s: distance_km(s, self.depot))
        limits = [distance_km(by_distance[max(0, len(by_distance) * k // 3 - 1)], self.depot) for k in (1, 2)]
        nodes = self.stations + [self.depot]
        for index, node in enumerate(nodes):
            node.index = index
        self._km = np.array([[distance_km(a, b) for b in nodes] for a in nodes])
        for s in self.stations:
            distance = self._km[s.index, self.depot.index]
            s.zone = ZONES[sum(distance > limit for limit in limits)]
            s.neighbours = sorted((o for o in self.stations if o is not s), key=lambda o: self._km[s.index, o.index])
        self.total_capacity = sum(s.capacity for s in self.stations)

        # Fleet: every bike is an individual object.
        self._place_fleet(occupancy, fleet_size)

        # Weather and demand use their own random streams, so two scenarios with the same
        # seed face exactly the same weather and the same requests (common random numbers).
        stream = int(self.rng.integers(2 ** 31))
        self.demand_rng = np.random.default_rng(stream + 1)
        self.weather = Weather(np.random.default_rng(stream + 2), weather, mean_temperature)
        size = len(self.stations)
        self.demand = DemandModel(self.stations, self._km[:size, :size], demand_rate, asymmetry, self.start_weekday)
        self.dispatcher = Dispatcher(self, rebalancing, low_threshold, high_threshold,
                                     rebalance_interval, maintenance_threshold)
        self.vehicles = [VehicleAgent(self, self.depot, vehicle_capacity, vehicle_speed_kmh)
                         for _ in range(vehicles)]

        reporters = {name: name for name in (
            'minute', 'requests', 'served', 'failed_pickups', 'completed_trips', 'failed_returns',
            'bikes_moved', 'revenue')}
        reporters.update({
            'bikes_at_stations': lambda m: sum(s.bikes for s in m.stations),
            'bikes_in_use': lambda m: m.riding,
            'bikes_broken': lambda m: sum(len(s.broken) for s in m.stations),
            'bikes_in_vehicles': lambda m: sum(len(v.cargo) + len(v.broken) for v in m.vehicles),
            'bikes_at_depot': lambda m: m.depot.bikes,
            'users_waiting': lambda m: sum(len(s.queue) for s in m.stations),
            'empty_stations': lambda m: sum(s.available == 0 for s in m.stations),
            'full_stations': lambda m: sum(s.free_docks == 0 for s in m.stations),
            'service_rate': lambda m: m.service_rate,
            'operational_cost': lambda m: m.operational_cost,
            'maintenance_cost': lambda m: m.maintenance_cost,
            'profit': lambda m: m.profit,
            'vehicle_km': lambda m: sum(v.km for v in m.vehicles),
            'temperature': lambda m: round(m.weather.temperature, 1),
            'weather': lambda m: m.weather.condition,
        })
        self.datacollector = mesa.DataCollector(model_reporters=reporters)
        self.datacollector.collect(self)

    # ---- set-up --------------------------------------------------------------------

    def _add_virtual_zones(self, count, capacity):
        """Place dockless zones in the largest gaps of the network (midpoints of station pairs)."""
        docked = list(self.stations)
        middles = [((a.lat + b.lat) / 2, (a.lon + b.lon) / 2) for i, a in enumerate(docked) for b in docked[i + 1:]]
        for number in range(1, count + 1):
            def gap(point):
                return min(distance_km(_Point(*point), s) for s in self.stations)
            lat, lon = max(middles, key=gap)
            row = {'id': f'virtual-{number}', 'name': f'Virtual zone {number}', 'lat': lat, 'lon': lon,
                   'bike_racks': capacity}
            self.stations.append(StationAgent(self, row, kind='virtual'))

    def _place_fleet(self, occupancy, fleet_size):
        if fleet_size is None:
            counts = [int(s.capacity * occupancy) for s in self.stations]
            spare = 0
        else:
            if fleet_size < 0 or fleet_size > self.total_capacity + self.depot.capacity:
                raise ValueError('fleet_size does not fit in the stations and the depot')
            # Proportional to capacity (largest remainders first); the excess starts at the depot.
            share = min(1.0, fleet_size / self.total_capacity)
            exact = [s.capacity * share for s in self.stations]
            counts = [int(e) for e in exact]
            left = min(fleet_size, self.total_capacity) - sum(counts)
            for i in sorted(range(len(exact)), key=lambda i: exact[i] - counts[i], reverse=True)[:left]:
                counts[i] += 1
            spare = fleet_size - sum(counts)
        self.bikes = []
        for station, count in zip(self.stations, counts):
            for _ in range(count):
                station.dock(self._new_bike())
        for _ in range(spare):
            self.depot.receive(self._new_bike())
        self.fleet_size = len(self.bikes)

    def _new_bike(self):
        bike = Bike(len(self.bikes) + 1)
        self.bikes.append(bike)
        return bike

    # ---- geography -----------------------------------------------------------------

    def distance(self, a, b):
        return float(self._km[a.index, b.index])

    def road_km(self, a, b):
        return float(self._km[a.index, b.index]) * DETOUR

    def travel_minutes(self, origin, destination):
        """Direct ride at the base speed."""
        return max(1, math.ceil(self.road_km(origin, destination) / self.speed_kmh * 60))

    def ride_minutes(self, origin, destination, profile, direct=False):
        """Stochastic trip duration: speed by profile and weather, noise and leisure time."""
        speed = self.speed_kmh * profile.speed_factor * self.weather.speed_factor
        minutes = self.road_km(origin, destination) / speed * 60
        if not direct:
            minutes *= self.rng.lognormal(0, 0.15)
            if profile.leisure_minutes:
                minutes += self.rng.exponential(profile.leisure_minutes)
        return max(1, math.ceil(minutes))

    def walk_minutes(self, a, b):
        return max(1, math.ceil(self.road_km(a, b) / WALK_KMH * 60))

    def drive_minutes(self, a, b):
        return self.road_km(a, b) / self.vehicles[0].speed_kmh * 60

    def nearest(self, station, condition, max_km=None):
        for other in station.neighbours:
            if max_km is not None and self.distance(station, other) > max_km:
                return None
            if condition(other):
                return other
        return None

    def needs_bikes(self, station):
        return station.available <= self.low_threshold * station.capacity

    def is_crowded(self, station):
        return station.free_docks <= (1 - self.high_threshold) * station.capacity

    # ---- clock ---------------------------------------------------------------------

    @property
    def weekday(self):
        return (self.start_weekday + self.minute // 1440) % 7

    @property
    def clock(self):
        return f'{WEEKDAYS[self.weekday]} {self.minute // 60 % 24:02d}:{self.minute % 60:02d}'

    def price_factor(self, profile):
        """Demand response to prices, relative to the reference tariff."""
        e = self.economics
        reference = e.reference_unlock + e.reference_trip_minutes * e.reference_minute
        price = self.price_unlock + e.reference_trip_minutes * self.price_minute
        if price <= 0:
            return 2.0
        return min(2.0, max(0.2, (price / reference) ** -profile.price_elasticity))

    def demand_factor(self):
        return self.weather.demand_factor

    def step(self):
        self.minute += 1
        self.weather.update(self.minute)
        self.dispatcher.begin_minute()
        self.depot.step()
        # Snapshot: finished users remove themselves from Mesa's agent registry.
        users = self.agents_by_type.get(UserAgent)
        if users is not None:
            users.shuffle_do('step')
        for vehicle in self.random.sample(self.vehicles, len(self.vehicles)):
            vehicle.step()
            vehicle.active_minutes += vehicle.state != 'idle'
        self._serve_queues()
        self._new_requests()
        for station in self.stations:
            station.empty_minutes += station.available == 0
            station.full_minutes += station.free_docks == 0
        self.check_invariants()
        self.datacollector.collect(self)

    def _serve_queues(self):
        for station in self.stations:
            while station.queue and station.usable:
                station.queue.popleft().start_ride()

    def _new_requests(self):
        demand, minute, rng = self.demand, self.minute, self.demand_rng
        arrivals = int(rng.poisson(demand.total_rate(minute, self.demand_factor())))
        if not arrivals:
            return
        commuters = demand.commuter_share(minute)
        origins = rng.choice(len(self.stations), size=arrivals, p=demand.origin_probabilities(minute))
        for origin in origins:
            profile = PROFILES['commuter' if rng.random() < commuters else 'casual']
            target = rng.choice(len(self.stations), p=demand.destination_probabilities(origin, minute))
            # Prices above the reference tariff remove requests; cheaper ones add some.
            factor = self.price_factor(profile)
            for _ in range(int(factor) + (rng.random() < factor % 1)):
                self.requests += 1
                self.stations[origin].requests += 1
                UserAgent(self, self.stations[origin], self.stations[target], profile).request()

    # ---- indicators ----------------------------------------------------------------

    @property
    def riding(self):
        return self.served - self.completed_trips

    @property
    def pending(self):
        """Users walking to a station or waiting for a bike."""
        return self.requests - self.served - self.failed_pickups

    def circulating_bikes(self):
        return (sum(s.available for s in self.stations) + self.riding
                + sum(len(v.cargo) for v in self.vehicles) + len(self.depot.stock))

    @property
    def service_rate(self):
        decided = self.served + self.failed_pickups
        return self.served / decided if decided else None

    @property
    def days(self):
        return self.minute / 1440

    @property
    def operational_cost(self):
        e = self.economics
        driving = sum(v.km * e.vehicle_km + v.active_minutes / 60 * e.vehicle_hour for v in self.vehicles)
        fixed = len(self.vehicles) * e.vehicle_day + self.fleet_size * e.bike_day + self.total_capacity * e.dock_day
        return driving + self.days * fixed

    @property
    def maintenance_cost(self):
        return self.repairs * self.economics.repair

    @property
    def profit(self):
        return self.revenue - self.operational_cost - self.maintenance_cost

    def zone_service(self):
        """Share of decided requests served in each urban area (the equity indicator)."""
        result = {}
        for zone in ZONES:
            members = [s for s in self.stations if s.zone == zone]
            decided = sum(s.served + s.failed_pickups for s in members)
            result[zone] = sum(s.served for s in members) / decided if decided else None
        return result

    def summary(self):
        zones = self.zone_service()
        rates = [r for r in zones.values() if r is not None]
        minutes = max(1, self.minute)
        decided = self.served + self.failed_pickups
        return {
            'city_id': self.city_id, 'minutes': self.minute, 'rebalancing': self.rebalancing,
            'stations': sum(s.kind == 'station' for s in self.stations),
            'virtual_zones': sum(s.kind == 'virtual' for s in self.stations),
            'capacity': self.total_capacity, 'fleet_size': self.fleet_size, 'vehicles': len(self.vehicles),
            'requests': self.requests, 'served': self.served, 'failed_pickups': self.failed_pickups,
            'service_rate': self.service_rate,
            'completed_trips': self.completed_trips, 'active_trips': self.riding,
            'failed_return_attempts': self.failed_returns, 'redirected_trips': self.redirected_trips,
            'avg_wait_minutes': self.wait_minutes / decided if decided else None,
            'avg_walk_minutes': self.walk_minutes_total / self.served if self.served else None,
            'users_who_waited': self.waited_users,
            'empty_station_share': sum(s.empty_minutes for s in self.stations) / (minutes * len(self.stations)),
            'full_station_share': sum(s.full_minutes for s in self.stations) / (minutes * len(self.stations)),
            'bike_utilisation': self.ride_minutes_total / (minutes * self.fleet_size) if self.fleet_size else None,
            'trips_per_bike_day': self.completed_trips / self.fleet_size / self.days if self.fleet_size and self.minute else None,
            'vehicle_utilisation': (sum(v.active_minutes for v in self.vehicles) / (minutes * len(self.vehicles))
                                    if self.vehicles else None),
            'vehicle_km': sum(v.km for v in self.vehicles), 'bikes_rebalanced': self.bikes_moved,
            'bike_failures': self.failures, 'repairs': self.repairs,
            'broken_bikes_now': sum(b.broken for b in self.bikes),
            'incentive_trips': self.incentive_trips, 'incentive_cost': self.incentive_cost,
            'revenue': self.revenue, 'operational_cost': self.operational_cost,
            'maintenance_cost': self.maintenance_cost, 'profit': self.profit,
            'service_rate_by_zone': zones,
            'equity_gap': max(rates) - min(rates) if rates else None,
        }

    def check_invariants(self):
        if any(s.free_docks < 0 for s in self.stations):
            raise RuntimeError('Station capacity violated')
        located = (sum(s.bikes for s in self.stations) + self.riding + self.depot.bikes
                   + sum(len(v.cargo) + len(v.broken) for v in self.vehicles))
        if located != self.fleet_size:
            raise RuntimeError('Bike conservation violated')
        users = len(self.agents_by_type.get(UserAgent, []))
        if self.pending < 0 or self.riding < 0 or self.pending + self.riding != users:
            raise RuntimeError('Trip accounting violated')

    def export(self, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.datacollector.get_model_vars_dataframe().to_csv(output_dir / 'metrics.csv', index=False)
        fields = ['station_id', 'name', 'kind', 'zone', 'lat', 'lon', 'capacity', 'bikes', 'available',
                  'requests', 'served', 'pickups', 'failed_pickups', 'returns', 'failed_returns',
                  'empty_minutes', 'full_minutes']
        with (output_dir / 'stations.csv').open('w', encoding='utf-8', newline='') as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: getattr(s, key) for key in fields} for s in self.stations)


class _Point:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon
