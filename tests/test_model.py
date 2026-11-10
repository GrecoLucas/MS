import json
import unittest
from dataclasses import replace

from bike_sharing.demand import PROFILES
from bike_sharing.model import BikeSharingModel
from bike_sharing.agents import UserAgent
from bike_sharing.policies import POLICIES

COMMUTER = PROFILES['commuter']
STAYS_PUT = replace(COMMUTER, max_walk_km=0, patience=10 ** 6)  # never walks, never gives up


def run(model, minutes):
    for _ in range(minutes):
        model.step()  # every step also checks the invariants
    return model


def quiet(**options):
    """A model without demand, failures or vehicles, to script single events."""
    return BikeSharingModel(demand_rate=0, failure_rate=0, vehicles=0, **options)


class BaseModelTests(unittest.TestCase):
    def test_every_policy_conserves_fleet(self):
        for policy in POLICIES:
            with self.subTest(policy=policy):
                model = run(BikeSharingModel(seed=3, demand_rate=0.2, rebalancing=policy, vehicles=2), 1440)
                self.assertGreater(model.completed_trips, 0)
                self.assertGreater(model.failed_pickups, 0)
                states = {bike.state for bike in model.bikes}
                self.assertLessEqual(states, {'docked', 'in_use', 'in_vehicle', 'in_repair', 'in_depot'})

    def test_empty_fleet_rejects_requests(self):
        model = run(BikeSharingModel(occupancy=0, demand_rate=1), 200)
        self.assertGreater(model.requests, 0)
        self.assertGreater(model.failed_pickups, 0)
        self.assertEqual(model.requests, model.failed_pickups + model.pending)
        self.assertEqual(model.served, 0)

    def test_no_demand_preserves_distribution(self):
        model = BikeSharingModel(demand_rate=0)
        initial = [s.bikes for s in model.stations]
        run(model, 60)
        self.assertEqual(initial, [s.bikes for s in model.stations])
        self.assertEqual(model.requests, 0)
        self.assertEqual(sum(v.km for v in model.vehicles), 0)

    def test_seed_reproduces_metrics(self):
        first, second = run(BikeSharingModel(seed=7), 240), run(BikeSharingModel(seed=7), 240)
        self.assertTrue(first.datacollector.get_model_vars_dataframe().equals(
            second.datacollector.get_model_vars_dataframe()))

    def test_scenarios_share_demand_and_weather(self):
        runs = [run(BikeSharingModel(seed=5, rebalancing=policy), 1440) for policy in ('none', 'predictive')]
        self.assertEqual(runs[0].requests, runs[1].requests)
        weather = [m.datacollector.get_model_vars_dataframe()['weather'].tolist() for m in runs]
        self.assertEqual(*weather)

    def test_invalid_parameters_are_rejected(self):
        for options in ({'occupancy': 2}, {'demand_rate': -1}, {'rebalancing': 'magic'},
                        {'weather': 'snow'}, {'incentive_discount': 1.5}, {'fleet_size': 10 ** 6},
                        {'low_threshold': 0.9, 'high_threshold': 0.5}, {'city_id': 'missing'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BikeSharingModel(**options)


class UserTests(unittest.TestCase):
    def test_full_destination_redirects_bike(self):
        model = quiet(occupancy=1)
        origin, destination = model.stations[:2]
        model.requests = 1
        user = UserAgent(model, origin, destination, COMMUTER)
        user.start_ride()  # leaves the only free dock of the system at the origin
        user.t1 = 1
        model.step()
        self.assertEqual(model.failed_returns, 1)
        self.assertIs(user.destination, origin)
        run(model, user.t1 - model.minute)
        self.assertEqual(model.completed_trips, 1)
        self.assertEqual(model.redirected_trips, 1)
        self.assertGreater(model.walk_minutes_total, 0)  # walked back to where they wanted to go

    def test_user_walks_to_nearby_station_with_bikes(self):
        model = quiet(occupancy=1)
        station = model.stations[0]
        neighbour = station.neighbours[0]
        walker = replace(COMMUTER, max_walk_km=model.distance(station, neighbour) + 0.01)
        spare, station.usable = station.usable, []
        model.requests = 1
        user = UserAgent(model, station, model.stations[-1], walker)
        user.request()
        self.assertEqual(user.state, 'walking')
        self.assertIs(user.origin, neighbour)
        station.usable = spare
        run(model, model.walk_minutes(station, neighbour))
        self.assertEqual(user.state, 'riding')
        self.assertEqual(station.served, 1)      # counted where the request was made
        self.assertEqual(neighbour.pickups, 1)   # but the bike left the neighbour

    def test_waiting_user_gets_the_next_bike(self):
        model = quiet(fleet_size=1)
        holder = next(s for s in model.stations if s.usable)
        station = next(s for s in model.stations if s is not holder)
        model.requests = 1
        user = UserAgent(model, station, holder, STAYS_PUT)
        user.request()
        run(model, 5)
        self.assertEqual(user.state, 'waiting')
        station.dock(holder.usable.pop())
        model.step()
        self.assertEqual(user.state, 'riding')
        self.assertEqual(model.waited_users, 1)
        self.assertEqual(model.wait_minutes, 6)

    def test_impatient_user_gives_up(self):
        model = quiet(occupancy=0)
        model.requests = 1
        UserAgent(model, model.stations[0], model.stations[1], replace(COMMUTER, patience=2)).request()
        run(model, 120)
        self.assertEqual(model.failed_pickups, 1)
        self.assertEqual(model.pending, 0)
        self.assertGreater(model.wait_minutes, 0)


class OperationsTests(unittest.TestCase):
    def test_rebalancing_improves_service(self):
        results = {policy: run(BikeSharingModel(seed=11, rebalancing=policy), 3 * 1440)
                   for policy in ('none', 'threshold')}
        # Without rebalancing the van still returns repaired bikes, but moves far fewer.
        self.assertGreater(results['threshold'].bikes_moved, 5 * results['none'].bikes_moved)
        idle = run(BikeSharingModel(seed=11, maintenance_threshold=0), 1440)
        self.assertEqual((idle.bikes_moved, sum(v.km for v in idle.vehicles)), (0, 0))
        self.assertGreater(results['threshold'].service_rate, results['none'].service_rate)
        self.assertGreater(results['threshold'].operational_cost, results['none'].operational_cost)

    def test_periodic_policy_only_works_in_rounds(self):
        model = run(BikeSharingModel(rebalancing='periodic', rebalance_interval=600, maintenance_threshold=0), 599)
        self.assertEqual(model.bikes_moved, 0)
        run(model, 300)
        self.assertGreater(model.bikes_moved, 0)

    def test_broken_bikes_are_collected_and_repaired(self):
        model = run(BikeSharingModel(failure_rate=0.2, maintenance_threshold=2), 2 * 1440)
        self.assertGreater(model.failures, 0)
        self.assertGreater(model.repairs, 0)
        self.assertEqual(model.maintenance_cost, model.repairs * model.economics.repair)
        self.assertEqual(model.failures - model.repairs, sum(b.broken for b in model.bikes))

    def test_without_vehicles_broken_bikes_stay_at_stations(self):
        model = run(BikeSharingModel(failure_rate=0.2, vehicles=0), 1440)
        self.assertGreater(model.failures, 0)
        self.assertEqual(model.repairs, 0)
        self.assertEqual(model.failures, sum(len(s.broken) for s in model.stations))

    def test_incentives_change_destinations_and_cost_revenue(self):
        model = run(BikeSharingModel(incentive_discount=0.5), 2 * 1440)
        self.assertGreater(model.incentive_trips, 0)
        self.assertGreater(model.incentive_cost, 0)
        self.assertEqual(run(BikeSharingModel(), 1440).incentive_trips, 0)

    def test_fleet_size_and_capacity_options(self):
        model = BikeSharingModel(fleet_size=60)
        self.assertEqual(sum(s.bikes for s in model.stations), 60)
        oversized = BikeSharingModel(fleet_size=model.total_capacity + 20)
        self.assertEqual(len(oversized.depot.stock), 20)
        self.assertEqual(BikeSharingModel(capacity_scale=2).total_capacity, 2 * model.total_capacity)

    def test_virtual_zones_extend_the_network(self):
        model = run(BikeSharingModel(virtual_zones=3, virtual_capacity=8), 1440)
        zones = [s for s in model.stations if s.kind == 'virtual']
        self.assertEqual(len(zones), 3)
        self.assertTrue(all(z.capacity == 8 for z in zones))
        self.assertGreater(sum(z.requests for z in zones), 0)

    def test_weather_and_price_reduce_demand(self):
        clear = run(BikeSharingModel(weather='clear'), 1440)
        self.assertLess(run(BikeSharingModel(weather='rain'), 1440).requests, clear.requests)
        self.assertLess(run(BikeSharingModel(weather='clear', price_minute=0.2), 1440).requests, clear.requests)

    def test_commute_moves_bikes_towards_the_centre_in_the_morning(self):
        model = BikeSharingModel()
        morning = model.demand.origin_probabilities(8 * 60)
        evening = model.demand.origin_probabilities(18 * 60)
        periphery = [s.index for s in model.stations if s.zone == 'periphery']
        self.assertGreater(morning[periphery].sum(), evening[periphery].sum())
        self.assertAlmostEqual(morning.sum(), 1)
        self.assertAlmostEqual(model.demand.expected_net_outflow(8 * 60, 120).sum(), 0)

    def test_summary_is_json_serialisable(self):
        summary = run(BikeSharingModel(rebalancing='predictive'), 1440).summary()
        self.assertEqual(json.loads(json.dumps(summary))['requests'], summary['requests'])
        self.assertEqual(set(summary['service_rate_by_zone']), {'center', 'intermediate', 'periphery'})


if __name__ == '__main__':
    unittest.main()
