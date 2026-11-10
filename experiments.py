"""Compare operating strategies over several random seeds.

Two experiments are run:
  policy      rebalancing strategy x fleet size (the main research question)
  sensitivity one factor at a time around a reference scenario

Every scenario faces the same demand and weather for a given seed.
"""

import argparse
import math
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from bike_sharing.model import BikeSharingModel

STRATEGIES = {
    'No rebalancing': {'rebalancing': 'none'},
    'Periodic rounds': {'rebalancing': 'periodic'},
    'Threshold': {'rebalancing': 'threshold'},
    'Predictive': {'rebalancing': 'predictive'},
    'Incentives only': {'rebalancing': 'none', 'incentive_discount': 0.5},
    'Threshold + incentives': {'rebalancing': 'threshold', 'incentive_discount': 0.5},
}
FLEET_SHARES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)  # bikes as a share of the docks
REFERENCE = {'rebalancing': 'threshold', 'occupancy': 0.5}
SENSITIVITY = {
    'Reference (threshold, 1 van)': {},
    'No vehicles (no maintenance)': {'vehicles': 0},
    '2 vehicles': {'vehicles': 2},
    'Vehicle capacity 5': {'vehicle_capacity': 5},
    'Vehicle capacity 20': {'vehicle_capacity': 20},
    'Station capacity x0.75': {'capacity_scale': 0.75},
    'Station capacity x1.5': {'capacity_scale': 1.5},
    '3 virtual zones': {'virtual_zones': 3},
    'Maintenance threshold 1': {'maintenance_threshold': 1},
    'Maintenance threshold 8': {'maintenance_threshold': 8},
    'Price 0.03/min': {'price_minute': 0.03},
    'Price 0.10/min': {'price_minute': 0.10},
    'Demand x0.5': {'demand_rate': 0.02},
    'Demand x1.5': {'demand_rate': 0.06},
    'Always clear': {'weather': 'clear'},
    'Always rain': {'weather': 'rain'},
    'Cold (5 C)': {'mean_temperature': 5.0},
}
METRICS = ('service_rate', 'failed_pickups', 'avg_wait_minutes', 'avg_walk_minutes',
           'redirected_trips', 'empty_station_share', 'full_station_share', 'bike_utilisation',
           'vehicle_utilisation', 'vehicle_km', 'bikes_rebalanced', 'repairs', 'revenue',
           'operational_cost', 'maintenance_cost', 'profit', 'equity_gap')


def run(job):
    experiment, scenario, extra, params, seed, minutes = job
    model = BikeSharingModel(seed=seed, **params)
    for _ in range(minutes):
        model.step()
    summary = model.summary()
    zones = summary.pop('service_rate_by_zone')
    return {'experiment': experiment, 'scenario': scenario, **extra, 'seed': seed, **summary,
            **{f'service_{zone}': rate for zone, rate in zones.items()}}


def jobs(seeds, minutes):
    capacity = BikeSharingModel().total_capacity
    for seed in seeds:
        for name, params in STRATEGIES.items():
            for share in FLEET_SHARES:
                fleet = round(share * capacity)
                yield ('policy', name, {'fleet_share': share}, {**params, 'fleet_size': fleet}, seed, minutes)
        for name, params in SENSITIVITY.items():
            yield ('sensitivity', name, {'fleet_share': 0.5}, {**REFERENCE, **params}, seed, minutes)


def summarise(runs):
    """Mean, standard deviation and 95% confidence half-width for each scenario."""
    grouped = runs.groupby(['experiment', 'scenario', 'fleet_share'], sort=False)[list(METRICS)]
    mean, std, count = grouped.mean(), grouped.std(), grouped.count()
    half = 1.96 * std / count.pow(0.5)
    table = pd.concat({'mean': mean, 'std': std, 'ci95': half}, axis=1).swaplevel(axis=1)
    table = table[[(metric, stat) for metric in METRICS for stat in ('mean', 'std', 'ci95')]]
    table.columns = [f'{metric}_{stat}' for metric, stat in table.columns]
    return table.reset_index()


def plots(summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    policy = summary[summary.experiment == 'policy']
    charts = (('service_rate', 'Demand served', 'service_vs_fleet.png'),
              ('profit', 'Profit per run (EUR)', 'profit_vs_fleet.png'),
              ('equity_gap', 'Service gap between zones', 'equity_vs_fleet.png'),
              ('avg_walk_minutes', 'Extra walking per trip (min)', 'walking_vs_fleet.png'))
    for metric, label, name in charts:
        figure, ax = plt.subplots(figsize=(7.5, 4.5), layout='constrained')
        for scenario, rows in policy.groupby('scenario', sort=False):
            ax.errorbar(rows.fleet_share, rows[f'{metric}_mean'], yerr=rows[f'{metric}_ci95'],
                        marker='o', capsize=3, label=scenario)
        ax.set(xlabel='Fleet size (bikes per dock)', ylabel=label, title=f'{label} by strategy and fleet size')
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        figure.savefig(output / name, dpi=150)
        plt.close(figure)

    figure, ax = plt.subplots(figsize=(7.5, 4.5), layout='constrained')
    for scenario, rows in policy.groupby('scenario', sort=False):
        ax.plot(rows.operational_cost_mean + rows.maintenance_cost_mean, rows.service_rate_mean,
                marker='o', label=scenario)
        for _, row in rows.iterrows():
            ax.annotate(f'{row.fleet_share:.0%}', (row.operational_cost_mean + row.maintenance_cost_mean,
                                                   row.service_rate_mean), fontsize=6,
                        xytext=(3, 3), textcoords='offset points')
    ax.set(xlabel='Operating + maintenance cost per run (EUR)', ylabel='Demand served',
           title='Cost versus service (labels: fleet size)')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    figure.savefig(output / 'cost_vs_service.png', dpi=150)
    plt.close(figure)

    sensitivity = summary[summary.experiment == 'sensitivity'].iloc[::-1]
    figure, axes = plt.subplots(1, 2, figsize=(11, 5.5), layout='constrained', sharey=True)
    for ax, metric, label in zip(axes, ('service_rate', 'profit'), ('Demand served', 'Profit per run (EUR)')):
        ax.barh(sensitivity.scenario, sensitivity[f'{metric}_mean'], xerr=sensitivity[f'{metric}_ci95'],
                color='#2563eb', capsize=2)
        ax.axvline(sensitivity[f'{metric}_mean'].iloc[-1], color='#dc2626', linestyle='--', linewidth=1)
        ax.set(xlabel=label)
        ax.grid(alpha=0.3, axis='x')
    axes[0].set_xlim(left=max(0, sensitivity.service_rate_mean.min() - 0.1))
    figure.suptitle('Sensitivity around the reference scenario (dashed line)')
    figure.savefig(output / 'sensitivity.png', dpi=150)
    plt.close(figure)


def report(summary, output, seeds, days):
    def cell(row, metric, digits):
        return f"{row[f'{metric}_mean']:.{digits}f} ± {row[f'{metric}_ci95']:.{digits}f}"

    columns = (('service_rate', 'Served', 3), ('avg_wait_minutes', 'Wait (min)', 2),
               ('avg_walk_minutes', 'Walk (min)', 2), ('full_station_share', 'Full', 3),
               ('equity_gap', 'Zone gap', 3), ('bikes_rebalanced', 'Moved', 0),
               ('vehicle_km', 'Van km', 0), ('profit', 'Profit', 0))
    lines = ['# Experiment results', '',
             f'{len(seeds)} seeds, {days:g} simulated days per run. Values are mean ± 95% confidence half-width.', '']
    for experiment, title in (('policy', 'Rebalancing strategy x fleet size'), ('sensitivity', 'Sensitivity')):
        lines += [f'## {title}', '',
                  '| Scenario | Fleet | ' + ' | '.join(label for _, label, _ in columns) + ' |',
                  '|---|---|' + '---|' * len(columns)]
        for _, row in summary[summary.experiment == experiment].iterrows():
            values = ' | '.join(cell(row, metric, digits) for metric, _, digits in columns)
            lines.append(f'| {row.scenario} | {row.fleet_share:.0%} | {values} |')
        lines.append('')
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seeds', type=int, default=10, help='replications per scenario')
    parser.add_argument('--days', type=float, default=7)
    parser.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument('--output', type=Path, default=Path('results/experiments'))
    args = parser.parse_args()
    if args.seeds < 2 or args.days <= 0:
        parser.error('use at least 2 seeds and a positive duration')
    seeds = list(range(1, args.seeds + 1))
    work = list(jobs(seeds, math.ceil(args.days * 1440)))
    print(f'{len(work)} runs on {args.workers} processes...')
    with ProcessPoolExecutor(args.workers) as pool:
        runs = pd.DataFrame(pool.map(run, work, chunksize=4))
    args.output.mkdir(parents=True, exist_ok=True)
    runs.to_csv(args.output / 'runs.csv', index=False)
    summary = summarise(runs)
    summary.to_csv(args.output / 'summary.csv', index=False)
    plots(summary, args.output)
    report(summary, args.output, seeds, args.days)
    shown = summary[summary.experiment == 'policy'].pivot(index='scenario', columns='fleet_share',
                                                         values='service_rate_mean')
    print('\nDemand served (mean) by strategy and fleet share:')
    print(shown.loc[list(STRATEGIES)].round(3).to_string())
    print(f'\nResults: {args.output.resolve()}')


if __name__ == '__main__':
    main()
