"""Run one scenario and export reproducible results."""

import argparse
import json
from pathlib import Path

from bike_sharing.demand import Weather
from bike_sharing.model import BikeSharingModel
from bike_sharing.policies import POLICIES


def add_model_arguments(parser):
    """Scenario options shared by the command line tools."""
    parser.add_argument('--city', default='442')
    parser.add_argument('--occupancy', type=float, default=0.5, help='initial share of docks with a bike')
    parser.add_argument('--fleet-size', type=int, help='total bikes (overrides --occupancy)')
    parser.add_argument('--capacity-scale', type=float, default=1.0, help='multiplies every station capacity')
    parser.add_argument('--virtual-zones', type=int, default=0, help='extra dockless parking zones')
    parser.add_argument('--demand-rate', type=float, default=0.04, help='mean requests per station per minute')
    parser.add_argument('--asymmetry', type=float, default=2.5, help='commute strength; 0 = flat uniform demand')
    parser.add_argument('--speed-kmh', type=float, default=15)
    parser.add_argument('--weather', default='dynamic', choices=('dynamic',) + Weather.STATES)
    parser.add_argument('--temperature', type=float, default=15.0, help='mean temperature in Celsius')
    parser.add_argument('--start-weekday', type=int, default=0, help='0 = Monday ... 6 = Sunday')
    parser.add_argument('--rebalancing', default='none', choices=POLICIES)
    parser.add_argument('--vehicles', type=int, default=1)
    parser.add_argument('--vehicle-capacity', type=int, default=10)
    parser.add_argument('--low-threshold', type=float, default=0.2)
    parser.add_argument('--high-threshold', type=float, default=0.85)
    parser.add_argument('--rebalance-interval', type=int, default=360, help='minutes between periodic rounds')
    parser.add_argument('--maintenance-threshold', type=int, default=3,
                        help='broken bikes that trigger a collection tour; 0 = no maintenance')
    parser.add_argument('--failure-rate', type=float, default=0.004, help='bike failures per km')
    parser.add_argument('--price-unlock', type=float, default=1.0)
    parser.add_argument('--price-minute', type=float, default=0.05)
    parser.add_argument('--incentive', type=float, default=0.0,
                        help='discount (0-1) for docking at stations that need bikes')
    parser.add_argument('--seed', type=int, default=42)


def model_from_arguments(args):
    return BikeSharingModel(
        city_id=args.city, occupancy=args.occupancy, fleet_size=args.fleet_size,
        capacity_scale=args.capacity_scale, virtual_zones=args.virtual_zones,
        demand_rate=args.demand_rate, asymmetry=args.asymmetry, speed_kmh=args.speed_kmh,
        weather=args.weather, mean_temperature=args.temperature, start_weekday=args.start_weekday,
        rebalancing=args.rebalancing, vehicles=args.vehicles, vehicle_capacity=args.vehicle_capacity,
        low_threshold=args.low_threshold, high_threshold=args.high_threshold,
        rebalance_interval=args.rebalance_interval, maintenance_threshold=args.maintenance_threshold,
        failure_rate=args.failure_rate, price_unlock=args.price_unlock, price_minute=args.price_minute,
        incentive_discount=args.incentive, seed=args.seed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_model_arguments(parser)
    parser.add_argument('--minutes', type=int, default=1440)
    parser.add_argument('--days', type=float, help='duration in days (overrides --minutes)')
    parser.add_argument('--output', type=Path, default=Path('results/baseline'))
    args = parser.parse_args()
    minutes = round(args.days * 1440) if args.days else args.minutes
    if minutes < 1:
        parser.error('the duration must be positive')
    try:
        model = model_from_arguments(args)
    except ValueError as error:
        parser.error(str(error))
    for _ in range(minutes):
        model.step()
    model.export(args.output)
    summary = {'seed': args.seed, **model.summary()}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print(f'Results: {args.output.resolve()}')


if __name__ == '__main__':
    main()
