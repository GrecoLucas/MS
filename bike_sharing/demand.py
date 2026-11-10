"""Synthetic demand: time profiles, weather, user profiles and origin-destination flows.

The dataset has no trips, so every number here is an explicit assumption, not fitted data.
"""

import math
from dataclasses import dataclass

import numpy as np

ZONES = ('center', 'intermediate', 'periphery')

# Hourly demand multipliers (value at the start of each hour, linearly interpolated).
WEEKDAY = (0.10, 0.05, 0.04, 0.04, 0.08, 0.30, 0.90, 1.90, 2.30, 1.40, 1.00, 1.05,
           1.25, 1.20, 1.10, 1.25, 1.80, 2.40, 2.10, 1.40, 0.95, 0.60, 0.40, 0.20)
WEEKEND = (0.25, 0.18, 0.10, 0.06, 0.05, 0.08, 0.20, 0.40, 0.75, 1.15, 1.50, 1.75,
           1.85, 1.90, 1.90, 1.80, 1.65, 1.45, 1.20, 0.95, 0.70, 0.55, 0.45, 0.35)
WEEKEND_LEVEL = 0.8  # weekends carry less total demand than weekdays

# How strongly each zone behaves as a trip attractor and as a home/work area.
ZONE_BASE = {'center': 1.3, 'intermediate': 1.0, 'periphery': 0.7}
ZONE_HOME = {'center': 0.0, 'intermediate': 0.5, 'periphery': 1.0}
ZONE_WORK = {'center': 1.0, 'intermediate': 0.4, 'periphery': 0.0}
VIRTUAL_WEIGHT = 0.6  # virtual zones attract less demand than docked stations


@dataclass(frozen=True)
class Profile:
    name: str
    speed_factor: float           # multiplies the base cycling speed
    patience: float               # mean minutes willing to wait for a bike
    max_walk_km: float            # farthest alternative station the user accepts
    price_elasticity: float       # demand response to the trip price
    incentive_sensitivity: float  # probability scale of accepting a discount
    leisure_minutes: float        # mean extra riding time on top of the direct trip


PROFILES = {
    'commuter': Profile('commuter', 1.10, 4.0, 0.6, 0.15, 0.35, 0.0),
    'casual': Profile('casual', 0.85, 8.0, 1.0, 0.80, 0.90, 6.0),
}


def _normalised(curve):
    mean = sum(curve) / len(curve)
    return tuple(v / mean for v in curve)


_WEEKDAY, _WEEKEND = _normalised(WEEKDAY), _normalised(WEEKEND)


def _bump(hour, centre, width):
    return math.exp(-0.5 * ((hour - centre) / width) ** 2)


class Weather:
    """Hourly Markov chain for the sky and a daily temperature cycle with noise."""

    STATES = ('clear', 'cloudy', 'rain')
    TRANSITIONS = {'clear': (0.85, 0.13, 0.02), 'cloudy': (0.25, 0.55, 0.20), 'rain': (0.10, 0.40, 0.50)}
    DEMAND = {'clear': 1.0, 'cloudy': 0.9, 'rain': 0.45}

    def __init__(self, rng, mode='dynamic', mean_temperature=15.0):
        if mode != 'dynamic' and mode not in self.STATES:
            raise ValueError(f"weather must be 'dynamic' or one of {self.STATES}")
        self.rng, self.mode, self.mean_temperature = rng, mode, mean_temperature
        self.condition = 'clear' if mode == 'dynamic' else mode
        self._noise = 0.0
        self.temperature = self._temperature(0)

    def _temperature(self, minute):
        hour = minute / 60 % 24
        daily = 5 * math.sin(2 * math.pi * (hour - 9) / 24)  # coldest ~03h, warmest ~15h
        return self.mean_temperature + daily + self._noise - (2 if self.condition == 'rain' else 0)

    def update(self, minute):
        if minute % 60 == 0:
            if self.mode == 'dynamic':
                self.condition = self.STATES[self.rng.choice(3, p=self.TRANSITIONS[self.condition])]
                self._noise = 0.8 * self._noise + self.rng.normal(0, 1)
            self.temperature = self._temperature(minute)

    @property
    def demand_factor(self):
        comfort = max(0.3, 1 - ((self.temperature - 20) / 25) ** 2)
        return self.DEMAND[self.condition] * comfort

    @property
    def speed_factor(self):
        return 0.9 if self.condition == 'rain' else 1.0


class DemandModel:
    """Who asks for a bike, where and when, and where they want to go."""

    def __init__(self, locations, distances, rate, asymmetry=2.5, start_weekday=0, trip_scale_km=2.0):
        self.rate, self.asymmetry, self.start_weekday = rate, asymmetry, start_weekday
        self.stations = sum(s.kind == 'station' for s in locations)
        kind = np.array([1.0 if s.kind == 'station' else VIRTUAL_WEIGHT for s in locations])
        self.base = kind * np.array([ZONE_BASE[s.zone] for s in locations]) if asymmetry else kind
        self.home = np.array([ZONE_HOME[s.zone] for s in locations])
        self.work = np.array([ZONE_WORK[s.zone] for s in locations])
        self.kernel = np.exp(-distances / trip_scale_km)  # shorter trips are more likely
        np.fill_diagonal(self.kernel, 0.0)

    def is_weekend(self, minute):
        return (self.start_weekday + minute // 1440) % 7 >= 5

    def time_factor(self, minute):
        if not self.asymmetry:
            return 1.0  # flat demand reproduces the original uniform baseline
        curve = _WEEKEND if self.is_weekend(minute) else _WEEKDAY
        hour = minute / 60 % 24
        low = int(hour)
        value = curve[low] + (hour - low) * (curve[(low + 1) % 24] - curve[low])
        return value * (WEEKEND_LEVEL if self.is_weekend(minute) else 1.0)

    def commute(self, minute):
        """Strength (0..1) of the morning and the evening commute."""
        if self.is_weekend(minute) or not self.asymmetry:
            return 0.0, 0.0
        hour = minute / 60 % 24
        return _bump(hour, 8.0, 1.3), _bump(hour, 17.5, 1.5)

    def commuter_share(self, minute):
        if self.is_weekend(minute):
            return 0.15
        return 0.35 + 0.5 * max(self.commute(minute))

    def total_rate(self, minute, factor=1.0):
        """Expected requests per minute in the whole system."""
        return self.rate * self.stations * self.time_factor(minute) * factor

    def origin_probabilities(self, minute):
        morning, evening = self.commute(minute)
        weights = self.base * (1 + self.asymmetry * (morning * self.home + evening * self.work))
        return weights / weights.sum()

    def _destination_weights(self, minute):
        morning, evening = self.commute(minute)
        return self.base * (1 + self.asymmetry * (morning * self.work + evening * self.home))

    def destination_probabilities(self, origin, minute):
        weights = self._destination_weights(minute) * self.kernel[origin]
        return weights / weights.sum()

    def expected_net_outflow(self, minute, horizon, factor=1.0, step=30):
        """Expected pickups minus returns per location over the next `horizon` minutes."""
        net = np.zeros(len(self.base))
        for start in range(minute, minute + horizon, step):
            middle = start + step // 2
            pickups = self.total_rate(middle, factor) * step * self.origin_probabilities(middle)
            flows = self._destination_weights(middle) * self.kernel
            flows /= flows.sum(axis=1, keepdims=True)
            net += pickups - pickups @ flows
        return net
