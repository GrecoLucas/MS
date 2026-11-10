"""Rebalancing and maintenance policies: they decide the next task of each idle vehicle."""

import numpy as np

from .agents import Task

POLICIES = ('none', 'periodic', 'threshold', 'predictive')


class Dispatcher:
    """Greedy dispatcher shared by all policies.

    Policies differ in the target level of each station and in when a station is
    considered out of balance ("triggered"):

    none        never; vehicles only do maintenance and redeploy repaired bikes
    periodic    rounds every `interval` minutes fix any station 2+ bikes off target
    threshold   reacts when a station is almost empty or almost full
    predictive  like threshold, but targets follow the demand expected in the next hours
    """

    FORECAST_MINUTES = 120

    def __init__(self, model, policy, low, high, interval, maintenance_threshold):
        if policy not in POLICIES:
            raise ValueError(f'rebalancing must be one of {POLICIES}')
        self.model, self.policy = model, policy
        self.low, self.high, self.interval = low, high, interval
        self.maintenance_threshold = maintenance_threshold
        self.round_until = -1
        self._needs, self._needs_minute = {}, -1
        self._forecast, self._forecast_minute = None, -10 ** 9

    # ---- targets -------------------------------------------------------------------

    def _targets(self):
        model = self.model
        capacity = np.array([s.capacity for s in model.stations])
        target = capacity * model.circulating_bikes() / capacity.sum()
        if self.policy == 'predictive':
            if model.minute - self._forecast_minute >= 15:
                self._forecast = model.demand.expected_net_outflow(
                    model.minute, self.FORECAST_MINUTES, model.demand_factor())
                self._forecast_minute = model.minute
            target = target + self._forecast
        return np.clip(np.rint(target), 1, capacity - 1).astype(int)

    def needs(self):
        """Usable bikes each station is missing (positive) or has in excess (negative)."""
        if self._needs_minute != self.model.minute:
            self._needs = {s: int(t) - s.available for s, t in zip(self.model.stations, self._targets())}
            self._needs_minute = self.model.minute
        return self._needs

    def need(self, station):
        self._needs_minute = -1  # stock may have changed within this minute
        return self.needs()[station]

    def begin_minute(self):
        if self.policy == 'periodic' and self.model.minute % self.interval == 0:
            self.round_until = self.model.minute + self.interval // 2

    def triggered(self, station, need):
        if self.policy == 'periodic':
            return self.model.minute <= self.round_until and abs(need) >= 2
        if self.policy == 'threshold':
            return (need > 0 and self.model.needs_bikes(station)) or (need < 0 and self.model.is_crowded(station))
        if self.policy == 'predictive':
            return abs(need) >= max(2, 0.25 * station.capacity)
        return False

    # ---- task selection ----------------------------------------------------------------

    def next_task(self, vehicle):
        model, depot, here = self.model, self.model.depot, vehicle.location
        needs, space = self.needs(), vehicle.space
        minutes = model.drive_minutes
        mine = [s for s in model.stations if s.claimed_by in (None, vehicle)]

        def best(options, gain):
            return max(options, key=lambda s: gain(s) / (1 + minutes(here, s)))

        if len(vehicle.broken) >= max(1, vehicle.capacity // 2):
            return Task(depot, 'unload', 0)

        deficits = [s for s in mine if needs[s] > 0 and self.triggered(s, needs[s])
                    and (s.free_docks > 0 or (s.broken and space > 0))]
        if deficits:
            if vehicle.cargo:
                station = best(deficits, lambda s: min(needs[s], len(vehicle.cargo)))
                return Task(station, 'drop', needs[station])
            wanted = min(space, sum(needs[s] for s in deficits))
            sources = {s: -needs[s] for s in mine if needs[s] < 0}
            if depot.stock:
                sources[depot] = len(depot.stock)
            if sources and wanted > 0:
                source = best(sources, lambda s: min(sources[s], wanted))
                return Task(source, 'load' if source is depot else 'pickup', min(sources[source], wanted))

        crowded = [s for s in mine if needs[s] < 0 and self.triggered(s, needs[s])]
        if crowded and space > 0:
            station = best(crowded, lambda s: min(-needs[s], space))
            return Task(station, 'pickup', min(-needs[station], space))

        takers = [s for s in mine if needs[s] > 0 and s.free_docks > 0]
        if vehicle.cargo:
            if takers:
                station = best(takers, lambda s: min(needs[s], len(vehicle.cargo)))
                return Task(station, 'drop', needs[station])
            return Task(depot, 'unload', 0)

        if self.maintenance_threshold:
            broken = [s for s in mine if s.broken]
            total = sum(len(s.broken) for s in broken)
            if broken and space > 0 and (total >= self.maintenance_threshold or vehicle.broken):
                return Task(best(broken, lambda s: len(s.broken)), 'collect', 0)
            # Repaired bikes go back to the stations that miss the most bikes.
            if len(depot.stock) >= self.maintenance_threshold and takers and space > 0:
                amount = min(space, len(depot.stock), sum(needs[s] for s in takers))
                return Task(depot, 'load', amount)

        if vehicle.broken:
            return Task(depot, 'unload', 0)
        if here is not depot and model.minute - vehicle.idle_since >= 30:
            return Task(depot, 'unload', 0)  # nothing to do: drive back to base
        return None
