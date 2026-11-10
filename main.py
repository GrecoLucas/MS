"""Run the baseline and export reproducible results."""

import argparse
import json
from pathlib import Path

from bike_sharing.model import BikeSharingModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', default='442')
    parser.add_argument('--minutes', type=int, default=1440)
    parser.add_argument('--occupancy', type=float, default=0.5)
    parser.add_argument('--demand-rate', type=float, default=0.02)
    parser.add_argument('--speed-kmh', type=float, default=15)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path, default=Path('results/baseline'))
    args = parser.parse_args()
    if args.minutes < 1:
        parser.error('--minutes must be positive')
    try:
        model = BikeSharingModel(city_id=args.city, occupancy=args.occupancy,
                                 demand_rate=args.demand_rate, speed_kmh=args.speed_kmh, seed=args.seed)
    except ValueError as error:
        parser.error(str(error))
    for _ in range(args.minutes):
        model.step()
    model.export(args.output)
    summary = {
        'city_id': args.city, 'minutes': args.minutes, 'seed': args.seed,
        'occupancy': args.occupancy, 'demand_rate': args.demand_rate,
        'speed_kmh': args.speed_kmh, 'stations': len(model.stations),
        'capacity': sum(s.capacity for s in model.stations), 'fleet_size': model.fleet_size,
        'requests': model.requests, 'served': model.served,
        'failed_pickups': model.failed_pickups, 'completed_trips': model.completed_trips,
        'active_trips': model.served - model.completed_trips,
        'failed_return_attempts': model.failed_returns,
        'service_rate': model.served / model.requests if model.requests else None,
    }
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print(f'Results: {args.output.resolve()}')


if __name__ == '__main__':
    main()
