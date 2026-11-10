"""Interactive Mesa dashboard. Run with: solara run app.py."""

import math

import pandas as pd
import solara
from matplotlib.figure import Figure
from mesa.visualization import Slider, SolaraViz, make_plot_component
from mesa.visualization.utils import update_counter

from bike_sharing.model import BikeSharingModel


@solara.component
def Overview(model):
    update_counter.get()
    rate = f'{model.served / model.requests:.1%}' if model.requests else '—'
    solara.Markdown(
        f'### Minute {model.minute} · City {model.city_id}\n'
        f'**Fleet:** {model.fleet_size} · **Requests:** {model.requests} · '
        f'**Demand met:** {rate} · '
        f'**Trips in progress:** {model.served - model.completed_trips}\n\n'
        'Each step represents one minute. Synthetic, uniform demand; '
        'scenario without rebalancing. Change the parameters and restart with Reset.'
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
        cmap='RdYlGn', vmin=0, vmax=1, edgecolors='#334155',
    )
    for number, station in enumerate(stations, start=1):
        ax.annotate(str(number), (station.lon, station.lat),
                    xytext=(5, 5), textcoords='offset points', fontsize=8)
    ax.set(title='Stations · size = capacity', xlabel='Longitude', ylabel='Latitude')
    ax.set_aspect(1 / max(0.01, math.cos(math.radians(stations[0].lat))))
    ax.ticklabel_format(useOffset=False, style='plain')
    figure.colorbar(points, ax=ax, label='Occupancy (0 = empty; 1 = full)')
    solara.FigureMatplotlib(figure)


@solara.component
def StationTable(model):
    update_counter.get()
    solara.Markdown('### Station status\nThe numbers correspond to the map view.')
    solara.DataFrame(pd.DataFrame([
        {'No.': number, 'Station': s.name, 'Bikes': s.bikes,
         'Capacity': s.capacity, 'Occupancy (%)': round(100 * s.bikes / s.capacity, 1),
         'Requests': s.requests, 'Failed pickups': s.failed_pickups,
         'Failed returns': s.failed_returns}
        for number, s in enumerate(model.stations, start=1)
    ]), items_per_page=15)


def demand_axes(ax):
    ax.set(title='Cumulative demand', xlabel='Minute', ylabel='Requests / pickups')


def fleet_axes(ax):
    ax.set(title='Fleet distribution', xlabel='Minute', ylabel='Bikes')


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
            make_plot_component({'bikes_at_stations': '#2563eb', 'bikes_in_use': '#f59e0b'},
                                post_process=fleet_axes),
            (StationTable, 0),
        ],
        model_params={
            'city_id': '442',
            'occupancy': Slider('Initial occupancy', 0.5, min=0.0, max=1.0, step=0.05),
            'demand_rate': Slider('Requests / station / minute', 0.02,
                                  min=0.0, max=0.5, step=0.01),
            'speed_kmh': Slider('Speed (km/h)', 15, min=1, max=30, step=1),
            'seed': Slider('Random seed', 42, min=0, max=1000, step=1),
        },
        name='Bike Sharing · Mesa Simulation',
        play_interval=200,
    )
