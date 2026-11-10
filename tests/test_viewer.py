import json
import unittest

from viz3d.server import DEFAULTS, STATIC, Simulation, clean


class ViewerTests(unittest.TestCase):
    def test_snapshot_is_json_and_describes_the_scene(self):
        simulation = Simulation()
        simulation.reset({'rebalancing': 'predictive', 'virtual_zones': 2, 'start_hour': 8})
        simulation.step(30)
        state = json.loads(json.dumps(simulation.snapshot()))
        self.assertEqual(state['minute'], 8 * 60 + 30)
        self.assertEqual(sum(s['kind'] == 'virtual' for s in state['stations']), 2)
        depot = len(state['stations'])  # the depot is the node after the last station
        for mover in state['users'] + state['vehicles']:
            self.assertTrue(0 <= mover['from'] <= depot and 0 <= mover['to'] <= depot)
            self.assertLessEqual(mover['t0'], mover['t1'])
        self.assertIn('service_rate_by_zone', state['kpi'])

    def test_options_are_validated(self):
        params = clean({'vehicles': 99, 'occupancy': '0.3', 'rebalancing': 'magic', 'unknown': 1})
        self.assertEqual(params['vehicles'], 4)          # clamped
        self.assertEqual(params['occupancy'], 0.3)       # converted
        self.assertEqual(params['rebalancing'], DEFAULTS['rebalancing'])  # invalid choice ignored
        self.assertNotIn('unknown', params)

    def test_step_is_bounded_and_page_exists(self):
        simulation = Simulation()
        start = simulation.model.minute
        simulation.step(10 ** 6)
        self.assertEqual(simulation.model.minute - start, 240)
        self.assertTrue((STATIC / 'index.html').is_file() and (STATIC / 'app.js').is_file())


if __name__ == '__main__':
    unittest.main()
