"""Interactive Mesa dashboard. Run with: solara run app.py."""

import math

import pandas as pd
import solara
from matplotlib.figure import Figure
from mesa.visualization import Slider, SolaraViz, make_plot_component
from mesa.visualization.utils import update_counter

from bike_sharing.demand import Weather
from bike_sharing.model import BikeSharingModel
from bike_sharing.policies import POLICIES


@solara.component
def Overview(model):
    update_counter.get()
    k = model.summary()

    def show(value, pattern):
        return '—' if value is None else pattern.format(value)

    zones = ' · '.join(f'{zone} {show(rate, "{:.0%}")}' for zone, rate in k['service_rate_by_zone'].items())
    solara.Markdown(
        f'### {model.clock} · {model.weather.condition}, {model.weather.temperature:.0f} °C · '
        f'City {model.city_id} · policy: {model.rebalancing}\n'
        f'**Fleet:** {model.fleet_size} · **Requests:** {model.requests} · '
        f'**Demand met:** {show(k["service_rate"], "{:.1%}")} · **In use:** {model.riding} · '
        f'**Waiting:** {model.pending}\n\n'
        f'**Avg wait:** {show(k["avg_wait_minutes"], "{:.1f} min")} · '
        f'**Extra walking:** {show(k["avg_walk_minutes"], "{:.1f} min")} · '
        f'**Broken bikes:** {k["broken_bikes_now"]} · **Rebalanced:** {k["bikes_rebalanced"]} · '
        f'**Van km:** {k["vehicle_km"]:.0f}\n\n'
        f'**Revenue:** €{k["revenue"]:.0f} · **Operating cost:** €{k["operational_cost"]:.0f} · '
        f'**Maintenance:** €{k["maintenance_cost"]:.0f} · **Profit:** €{round(k["profit"]) + 0}\n\n'
        f'**Demand met by area:** {zones}\n\n'
        'Each step is one minute. Demand is synthetic. Change the parameters and restart with Reset.'
    )


@solara.component
def StationMap(model):
    update_counter.get()
    figure = Figure(figsize=(8, 5), layout='constrained')
    ax = figure.subplots()
    stations = model.stations
    points = ax.scatter(
        [s.lon for s in stations], [s.lat for s in stations],
        c=[s.bikes / s.capacity for s in stations],
        s=[40 + s.capacity * 5 for s in stations],
        marker='o', cmap='RdYlGn', vmin=0, vmax=1, edgecolors='#334155',
        linewidths=[2.5 if s.kind == 'virtual' else 1 for s in stations],
    )
    for number, station in enumerate(stations, start=1):
        ax.annotate(str(number), (station.lon, station.lat),
                    xytext=(5, 5), textcoords='offset points', fontsize=8)
    ax.scatter([model.depot.lon], [model.depot.lat], marker='s', s=90, color='#64748b', label='Depot')
    for vehicle in model.vehicles:  # drawn at the place it left or reached last
        place = vehicle.location
        ax.scatter([place.lon], [place.lat], marker='^', s=110, color='#2563eb', edgecolors='white',
                   label=f'Van ({len(vehicle.cargo)} bikes, {vehicle.state})')
    ax.set(title='Stations · size = capacity · thick border = virtual zone',
           xlabel='Longitude', ylabel='Latitude')
    ax.set_aspect(1 / max(0.01, math.cos(math.radians(stations[0].lat))))
    ax.ticklabel_format(useOffset=False, style='plain')
    ax.legend(fontsize=7, loc='upper left')
    figure.colorbar(points, ax=ax, label='Occupancy (0 = empty; 1 = full)')
    solara.FigureMatplotlib(figure)


@solara.component
def StationTable(model):
    update_counter.get()
    solara.Markdown('### Station status\nThe numbers correspond to the map view.')
    solara.DataFrame(pd.DataFrame([
        {'No.': number, 'Station': s.name, 'Area': s.zone, 'Usable': s.available, 'Broken': len(s.broken),
         'Capacity': s.capacity, 'Waiting': len(s.queue), 'Requests': s.requests,
         'Unmet': s.failed_pickups, 'Failed returns': s.failed_returns}
        for number, s in enumerate(model.stations, start=1)
    ]), items_per_page=15)


def demand_axes(ax):
    ax.set(title='Cumulative demand', xlabel='Minute', ylabel='Requests / pickups')


def fleet_axes(ax):
    ax.set(title='Fleet distribution', xlabel='Minute', ylabel='Bikes')


def money_axes(ax):
    ax.set(title='Money', xlabel='Minute', ylabel='EUR (cumulative)')


@solara.component
def Page():
    # A separate model for each browser session.
    model = solara.use_memo(lambda: BikeSharingModel(), [])
    SolaraViz(
        model,
        components=[
            (Overview, 0), (StationMap, 0),
            make_plot_component({'requests': '#2563eb', 'served': '#16a34a',
                                 'failed_pickups': '#dc2626'}, post_process=demand_axes),
            make_plot_component({'bikes_at_stations': '#2563eb', 'bikes_in_use': '#f59e0b',
                                 'bikes_broken': '#dc2626', 'users_waiting': '#7c3aed'},
                                post_process=fleet_axes),
            make_plot_component({'revenue': '#16a34a', 'operational_cost': '#f59e0b',
                                 'maintenance_cost': '#dc2626', 'profit': '#2563eb'},
                                post_process=money_axes),
            (StationTable, 0),
        ],
        model_params={
            'city_id': '442',
            'rebalancing': {'type': 'Select', 'value': 'none', 'values': list(POLICIES),
                            'label': 'Rebalancing policy'},
            'occupancy': Slider('Fleet (bikes per dock)', 0.5, min=0.0, max=1.0, step=0.05),
            'vehicles': Slider('Rebalancing vans', 1, min=0, max=3, step=1),
            'demand_rate': Slider('Requests / station / minute', 0.04, min=0.0, max=0.2, step=0.005),
            'incentive_discount': Slider('Incentive discount', 0.0, min=0.0, max=0.8, step=0.1),
            'weather': {'type': 'Select', 'value': 'dynamic', 'values': ['dynamic', *Weather.STATES],
                        'label': 'Weather'},
            'virtual_zones': Slider('Virtual parking zones', 0, min=0, max=4, step=1),
            'failure_rate': Slider('Bike failures per km', 0.004, min=0.0, max=0.03, step=0.002),
            'price_minute': Slider('Price per minute (EUR)', 0.05, min=0.0, max=0.2, step=0.01),
            'speed_kmh': Slider('Cycling speed (km/h)', 15, min=5, max=30, step=1),
            'seed': Slider('Random seed', 42, min=0, max=1000, step=1),
        },
        name='Bike Sharing · Mesa Simulation',
        play_interval=200,
    )
