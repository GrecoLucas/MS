import unittest

from bike_sharing.model import BikeSharingModel, UserAgent


class ModelTests(unittest.TestCase):
    def test_day_conserves_fleet(self):
        model = BikeSharingModel(seed=42, demand_rate=0.2)
        for _ in range(1440):
            model.step()
        model.check_invariants()
        self.assertGreater(model.completed_trips, 0)
        self.assertGreater(model.failed_pickups, 0)

    def test_empty_fleet_rejects_requests(self):
        model = BikeSharingModel(occupancy=0, demand_rate=1)
        for _ in range(10):
            model.step()
        self.assertGreater(model.requests, 0)
        self.assertEqual(model.requests, model.failed_pickups)
        self.assertEqual(model.served, 0)

    def test_no_demand_preserves_distribution(self):
        model = BikeSharingModel(demand_rate=0)
        initial = [s.bikes for s in model.stations]
        for _ in range(10):
            model.step()
        self.assertEqual(initial, [s.bikes for s in model.stations])
        self.assertEqual(model.requests, 0)

    def test_full_destination_redirects_bike(self):
        model = BikeSharingModel(occupancy=1, demand_rate=0)
        origin, destination = model.stations[:2]
        origin.bikes -= 1
        model.requests = model.served = 1
        user = UserAgent(model, origin, destination)
        user.arrival_minute = 1
        model.step()
        self.assertEqual(model.failed_returns, 1)
        self.assertIs(user.destination, origin)
        model.check_invariants()
        for _ in range(user.arrival_minute - model.minute):
            model.step()
        self.assertEqual(model.completed_trips, 1)
        model.check_invariants()

    def test_seed_reproduces_metrics(self):
        first, second = BikeSharingModel(seed=7), BikeSharingModel(seed=7)
        for _ in range(60):
            first.step()
            second.step()
        self.assertTrue(first.datacollector.get_model_vars_dataframe().equals(
            second.datacollector.get_model_vars_dataframe()))


if __name__ == '__main__':
    unittest.main()
