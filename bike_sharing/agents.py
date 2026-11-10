"""Entities of the conceptual model: bikes, parking locations, users, vehicles and depot."""

import math
from collections import deque, namedtuple

import mesa

# What a vehicle does when it reaches `target`:
#   pickup/drop  move usable bikes out of / into a station
#   collect      take broken bikes from a station
#   load/unload  take repaired bikes from / leave everything at the depot
Task = namedtuple('Task', 'target action amount')


class Bike:
    """One bicycle. Its container (station, user, vehicle or depot) defines where it is."""

    __slots__ = ('bike_id', 'broken', 'km', 'trips', 'state')

    def __init__(self, bike_id):
        self.bike_id = bike_id
        self.broken = False
        self.km = 0.0
        self.trips = 0
        self.state = 'docked'  # docked | in_use | in_vehicle | in_repair | in_depot


class StationAgent(mesa.Agent):
    """A parking location: a docked station or a virtual (dockless) parking zone."""

    def __init__(self, model, row, kind='station', capacity_scale=1.0):
        super().__init__(model)
        self.station_id = row['id']
        self.name = row['name']
        self.lat, self.lon = float(row['lat']), float(row['lon'])
        self.kind = kind
        self.capacity = max(1, round(int(row['bike_racks']) * capacity_scale))
        self.zone = 'center'
        self.index = 0
        self.usable, self.broken = [], []
        self.queue = deque()      # users waiting for a bike, first come first served
        self.claimed_by = None    # vehicle currently heading here
        self.neighbours = []      # other locations, nearest first
        self.requests = self.served = self.pickups = self.failed_pickups = 0
        self.returns = self.failed_returns = self.empty_minutes = self.full_minutes = 0

    @property
    def bikes(self):
        return len(self.usable) + len(self.broken)

    @property
    def available(self):
        return len(self.usable)

    @property
    def free_docks(self):
        return self.capacity - self.bikes

    def dock(self, bike):
        bike.state = 'docked'
        (self.broken if bike.broken else self.usable).append(bike)


class UserAgent(mesa.Agent):
    """A person from the moment they ask for a bike until they dock it (or give up)."""

    def __init__(self, model, origin, destination, profile):
        super().__init__(model)
        self.profile = profile
        self.requested = origin      # where the request was made (used for equity)
        self.origin = origin         # where the bike is picked up
        self.goal = destination      # where the user wants to go
        self.destination = destination  # where the bike is docked
        self.state = 'new'           # walking | waiting | riding
        self.bike = None
        self.discount = 0.0
        self.walked = 0              # minutes on foot because of the system state
        self.wait_start = None
        self.deadline = 0
        self.redirected = False
        self.move_from = self.move_to = origin
        self.t0 = self.t1 = self.ride_start = model.minute

    def request(self):
        """First contact with the system: ride, walk to a nearby station or wait."""
        station = self.origin
        if station.usable and not station.queue:
            return self.start_ride()
        alternative = self.model.nearest(
            station, lambda s: s.available > len(s.queue), self.profile.max_walk_km)
        if alternative is None:
            return self.wait()
        self.state = 'walking'
        self.origin = alternative
        self._move(station, alternative, self.model.walk_minutes(station, alternative))

    def wait(self):
        self.state = 'waiting'
        self.wait_start = self.model.minute
        patience = self.model.rng.exponential(self.profile.patience)
        self.deadline = self.model.minute + max(1, round(patience))
        self.origin.queue.append(self)

    def step(self):
        minute = self.model.minute
        if self.state == 'waiting':
            if minute >= self.deadline:
                self.give_up()
        elif minute >= self.t1:
            if self.state == 'walking':
                self.walked += self.t1 - self.t0
                if self.origin.usable and not self.origin.queue:
                    self.start_ride()
                else:
                    self.wait()
            elif self.state == 'riding':
                self.try_return()

    def give_up(self):
        model = self.model
        self.origin.queue.remove(self)
        model.failed_pickups += 1
        self.requested.failed_pickups += 1
        model.wait_minutes += model.minute - self.wait_start
        model.walk_minutes_total += self.walked
        self.remove()

    def start_ride(self):
        model = self.model
        self.bike = self.origin.usable.pop()
        self.bike.state = 'in_use'
        self.origin.pickups += 1
        self.requested.served += 1
        model.served += 1
        if self.wait_start is not None:
            model.wait_minutes += model.minute - self.wait_start
            model.waited_users += 1
        self._consider_incentive()
        self.state = 'riding'
        self.ride_start = model.minute
        self._move(self.origin, self.destination,
                   model.ride_minutes(self.origin, self.destination, self.profile))

    def _consider_incentive(self):
        """Maybe accept a discount to dock at a nearby station that needs bikes."""
        model, goal = self.model, self.goal
        if not model.incentive_discount:
            return
        fill = goal.bikes / goal.capacity
        candidates = [s for s in goal.neighbours
                      if s is not self.origin
                      and model.distance(goal, s) <= self.profile.max_walk_km
                      and s.bikes / s.capacity <= fill - 0.3
                      and (model.needs_bikes(s) or model.is_crowded(goal))]
        if not candidates:
            return
        accept = self.profile.incentive_sensitivity * min(1.0, model.incentive_discount / 0.5)
        if model.random.random() < accept:
            self.destination = min(candidates, key=lambda s: s.bikes / s.capacity)
            self.discount = model.incentive_discount
            model.incentive_trips += 1

    def try_return(self):
        model, station = self.model, self.destination
        if station.free_docks > 0:
            return self._finish(station)
        station.failed_returns += 1
        model.failed_returns += 1
        self.redirected = True
        # Full stations can change while travelling: retry docking on arrival.
        alternative = model.nearest(station, lambda s: s.free_docks > 0)
        if alternative is None:
            self.t1 = model.minute + 1
            return
        self.destination = alternative
        self._move(station, alternative, model.ride_minutes(station, alternative, self.profile, direct=True))

    def _finish(self, station):
        model, bike = self.model, self.bike
        minutes = model.minute - self.ride_start
        km = minutes / 60 * model.speed_kmh * self.profile.speed_factor
        bike.km += km
        bike.trips += 1
        if model.random.random() < 1 - math.exp(-model.failure_rate * km):
            bike.broken = True
            model.failures += 1
        station.dock(bike)
        station.returns += 1
        full_price = model.price_unlock + minutes * model.price_minute
        model.revenue += full_price * (1 - self.discount)
        model.incentive_cost += full_price * self.discount
        if station is not self.goal:  # walk the rest of the way
            self.walked += model.walk_minutes(station, self.goal)
        model.walk_minutes_total += self.walked
        model.ride_minutes_total += minutes
        model.completed_trips += 1
        model.redirected_trips += self.redirected
        self.remove()

    def _move(self, start, end, minutes):
        self.move_from, self.move_to = start, end
        self.t0, self.t1 = self.model.minute, self.model.minute + minutes


class DepotAgent(mesa.Agent):
    """Base of the vehicles; repairs broken bikes and stores spare ones."""

    def __init__(self, model, lat, lon, capacity, repair_minutes, workshops):
        super().__init__(model)
        self.name, self.kind = 'Depot', 'depot'
        self.lat, self.lon = lat, lon
        self.capacity = capacity
        self.repair_minutes, self.workshops = repair_minutes, workshops
        self.index = 0
        self.stock = []     # usable bikes ready to be deployed
        self.waiting = deque()   # broken bikes waiting for a workshop
        self.repairing = []      # (ready_minute, bike)

    @property
    def bikes(self):
        return len(self.stock) + len(self.waiting) + len(self.repairing)

    def receive(self, bike):
        if bike.broken:
            bike.state = 'in_repair'
            self.waiting.append(bike)
        else:
            bike.state = 'in_depot'
            self.stock.append(bike)

    def step(self):
        minute = self.model.minute
        for item in [r for r in self.repairing if r[0] <= minute]:
            self.repairing.remove(item)
            item[1].broken = False
            self.model.repairs += 1
            self.receive(item[1])
        while self.waiting and len(self.repairing) < self.workshops:
            self.repairing.append((minute + self.repair_minutes, self.waiting.popleft()))


class VehicleAgent(mesa.Agent):
    """Electric van that rebalances usable bikes and collects broken ones."""

    def __init__(self, model, depot, capacity, speed_kmh):
        super().__init__(model)
        self.capacity, self.speed_kmh = capacity, speed_kmh
        self.location = self.target = self.move_from = depot
        self.cargo, self.broken = [], []
        self.state = 'idle'  # idle | moving | servicing
        self.task = None
        self.t0 = self.t1 = self.busy_until = self.idle_since = model.minute
        self.km = 0.0
        self.active_minutes = self.bikes_moved = self.stops = 0

    @property
    def space(self):
        return self.capacity - len(self.cargo) - len(self.broken)

    def step(self):
        model = self.model
        if self.state == 'moving':
            if model.minute >= self.t1:
                self._arrive()
            return
        if self.state == 'servicing':
            if model.minute < self.busy_until:
                return
            self.state, self.idle_since = 'idle', model.minute
        task = model.dispatcher.next_task(self)
        if task is None:
            return
        self.task, self.target = task, task.target
        if task.target is not model.depot:
            task.target.claimed_by = self
        if task.target is self.location:
            return self._arrive()
        km = model.road_km(self.location, task.target)
        self.km += km
        self.state, self.move_from = 'moving', self.location
        self.t0 = model.minute
        self.t1 = model.minute + max(1, math.ceil(km / self.speed_kmh * 60))

    def _arrive(self):
        model, task, place = self.model, self.task, self.task.target
        self.location = self.move_from = place
        self.state, self.busy_until = 'servicing', model.minute + model.stop_minutes
        self.t0 = self.t1 = model.minute
        self.stops += 1
        if place is model.depot:
            for bike in self.broken:
                place.receive(bike)
            self.broken = []
            if task.action == 'load':
                for _ in range(min(task.amount, len(place.stock), self.space)):
                    self._carry(place.stock.pop())
            else:
                for bike in self.cargo:
                    place.receive(bike)
                self.cargo = []
            return
        place.claimed_by = None
        self._collect(place)  # frees docks before dropping
        need = model.dispatcher.need(place)
        if task.action == 'pickup':
            for _ in range(min(task.amount, max(0, -need), self.space)):
                self._carry(place.usable.pop())
        elif task.action == 'drop':
            count = min(task.amount, len(self.cargo), place.free_docks)
            for _ in range(count):
                place.dock(self.cargo.pop())
            self.bikes_moved += count
            model.bikes_moved += count
            self._collect(place)

    def _carry(self, bike):
        bike.state = 'in_vehicle'
        self.cargo.append(bike)

    def _collect(self, station):
        while station.broken and self.space > 0:
            bike = station.broken.pop()
            bike.state = 'in_vehicle'
            self.broken.append(bike)
            self.model.broken_collected += 1
