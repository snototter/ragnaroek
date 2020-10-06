#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

import matplotlib
# Set up headless on pi
import os
if os.uname().machine.startswith('arm'):
    matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import datetime
import logging
from PIL import Image
import io

from . import time_utils
from dateutil import tz
from rdp import rdp


def curve_color(idx):
    """Return a unique color for the given idx (if idx < distinct_colors)."""
    colors = [
        (0, .8, .8), # cyan
        (1, 0, 1), # violet
        (0, .8, 0), # green
        (0, 0, .8), # blue
        (1, .5, 0), # orange
        (1, 0, 0),  # red
    ]
    return colors[idx % len(colors)]
    # if colormap in [plt.cm.Pastel1, plt.cm.Pastel2, plt.cm.Paired,\
    #         plt.cm.Accent, plt.cm.Dark2, plt.cm.Set1, plt.cm.Set2,\
    #         plt.cm.Set3, plt.cm.tab10, plt.cm.tab20, plt.cm.tab20b, plt.cm.tab20c]:
    #     # For 'qualitative' colormaps, we do a simple lookup
    #     c = colormap(idx % len(colormap.colors))
    # else:
    #     # For all other colormaps, we uniformly sample N distinct_colors
    #     # across the colormap spectrum
    #     lookup = np.linspace(0., 1., distinct_colors % len(colormap.colors))
    #     c = colormap(lookup[idx % distinct_colors])
    # return c[:3]


def smooth(values, win_size):
    if win_size < 3:
        return values
    smoothed = list()
    neighbors = int((win_size - 1)//2)
    for idx in range(len(values)):
        ifrom = max(0, idx - neighbors)
        ito = min(len(values)-1, idx + neighbors)

        # Reduce span at the beginning/end (where there are less neighbors).
        actual_neighbors = min(idx - ifrom, ito - idx)
        ifrom = idx - actual_neighbors
        ito = idx + actual_neighbors

        # Average all values within the span.
        to_average = 0.0
        for win_idx in range(ifrom, ito+1):
            to_average += values[win_idx]
        avg = to_average / (2*actual_neighbors + 1)
        smoothed.append(avg)
    return smoothed


def __replace_tz(dt):
    return dt.replace(tzinfo=tz.tzutc())


def __naive_time_diff(dt_a, dt_b):
    """Returns the time difference between a and b, assuming both are within the same timezone."""
    a = __replace_tz(dt_a)
    b = __replace_tz(dt_b)
    if a > b:
        return a - b
    return b - a


def __prepare_ticks(temperature_log, desired_num_ticks=10):
    """Returns the best fitting x-axis ticks depending on the time spanned by the temperature-log."""
    def _tm(reading):
        return reading[0]
    # dt_end = _tm(temperature_log[-1])
    dt_end = time_utils.round_nearest(_tm(temperature_log[-1]), datetime.timedelta(minutes=15))
    # dt_end = time_utils.dt_now_local()
    # dt_start = _tm(temperature_log[0])
    # dt_end = time_utils.ceil_dt_hour(dt_end)
    dt_start = _tm(temperature_log[0])
    dt_now = time_utils.dt_now_local()

    # Find best fitting tick interval
    # time_span = dt_end - dt_start
    time_span = __naive_time_diff(dt_end, dt_start)
    sec_per_tick = time_span.total_seconds() / desired_num_ticks

    def _m(x):
        return x * 60

    def _h(x):
        return x * _m(60)

    def _d(x):
        return x * _h(24)

    tick_units = [_m(5), _m(15), _m(30), _h(1), _h(2), _h(3), _h(6), _h(12), _d(1), _d(7)]
    closest_tick_idx = np.argmin([abs(sec_per_tick - tu) for tu in tick_units])
    closest_tick_unit = tick_units[closest_tick_idx]

    # Compute ticks and labels (x-axis represents seconds passed since a reference datetime object)
    num_ticks_ceil = int(np.ceil(time_span.total_seconds() / closest_tick_unit).astype(np.int32))
    dt_tick_start = dt_end - datetime.timedelta(seconds=num_ticks_ceil * closest_tick_unit)
    # ## Version A, ceil
    num_ticks = int(np.ceil(time_span.total_seconds() / closest_tick_unit).astype(np.int32))
    offset = 0
    # ## Version B, floor
    # num_ticks = int(np.floor(time_span.total_seconds() / closest_tick_unit).astype(np.int32))
    # offset = closest_tick_unit

    tick_values = list()
    tick_labels = list()
    for i in range(num_ticks + 1):
        tick_sec = i * closest_tick_unit + offset
        dt_tick = dt_tick_start + datetime.timedelta(seconds=tick_sec)
        if dt_now.date() == dt_tick.date():
            tick_lbl = dt_tick.strftime('%H:%M')
        else:
            tick_lbl = dt_tick.strftime('%d.%m. %H:%M')
        tick_values.append(tick_sec)
        tick_labels.append(tick_lbl)
    # # Add end date
    # tick_sec = num_ticks * closest_tick_unit + offset
    # tick_values.append(tick_sec)
    # dt_tick = dt_tick_start + datetime.timedelta(seconds=tick_sec)
    # if dt_now.date() == dt_tick.date():
    #     tick_labels.append('{:02d}:{:02d}'.format(dt_tick.hour, dt_tick.minute))
    # else:
    #     tick_labels.append(dt_tick.strftime('%d.%m. %H:%M'))

    # logging.getLogger().info('drawing ticks start {}, end {}, time_span {}, dt_tick_start {}'.format(
    #     dt_start.strftime('%d.%m %H:%M'), dt_end.strftime('%d.%m %H:%M'), time_span, dt_tick_start.strftime('%d.%m %H:%M')))
    return tick_values, tick_labels, dt_tick_start


def __prepare_curves(sensor_names, temperature_log, dt_tick_start, simplify):
    """Prepares the temperature curves (x ticks are offsets from the given datetime dt_tick_start)."""
    temperature_curves = {sn: list() for sn in sensor_names}
    was_heating = list()
    for reading in temperature_log:
        dt_local, sensors, heating = reading

        td = __naive_time_diff(dt_local, dt_tick_start)
        dt_tick_offset = td.total_seconds()

        was_heating.append((dt_tick_offset, heating))

        if sensors is None:
            continue

        for sn in sensors.keys():
            if sensors[sn] is None:
                continue
            temperature_curves[sn].append((dt_tick_offset, sensors[sn]))
    if simplify:
        for sn in temperature_curves:
            t = temperature_curves[sn]
            simplified = rdp(t, epsilon=0.01)
            # TODO remove log output
            logging.getLogger().info('Drawing: Simplified {} from {} to {} readings.'.format(sn, len(t), len(simplified)))
            temperature_curves[sn] = simplified
    return temperature_curves, was_heating


def plot_temperature_curves(width_px, height_px, temperature_log,
        return_mem=True, xkcd=True, reverse=True, name_mapping=None,
        line_alpha=0.9, grid_alpha=0.3, linewidth=3.5,
        min_temperature_span=9, smoothing_window=7,
        font_size=20, legend_columns=3,
        draw_marker=False, alternate_line_styles=False,
        simplify_curves=True):
    """
    Plots the temperature readings (@see temperature_log.py).

    width_px, height_px: resolution of plot

    temperature_log: the sensor readings to be plotted
    
    return_mem: return_mem: save plot into a BytesIO buffer and return it, otherwise shows the plot (blocking, for debug)
    
    xkcd: :-) beautification of the plot
    
    reverse: reverse the temperature readings (if temperature_log[0] is the most recent reading)
    
    name_mapping: name_mapping: provide a dictionary if you want to rename the curves

    line_alpha: Alpha value for curves

    grid_alpha: Alpha value for the plot grid

    linewidth: Line width in pixels

    min_temperature_span: min_temperature_span: the y-axis should span at least these many degrees
    
    smoothing_window: number of readings to use for running average

    font_size: in pixels

    legend_columns: number of columns in legend

    draw_marker: in addition to the curves, also plot markers for every reading

    alternate_line_styles: if True, line styles will be alternated

    simplify_curves: Use Ramer-Douglas-Peucker to simplify the temperature plots
    """
    # ## Prepare the data
    if reverse:
        temperature_log = temperature_log[::-1]

    # Get names and number of sensors
    sensor_names = set()
    for reading in temperature_log:
        _, sensors, _ = reading
        if sensors is not None:
            sensor_names.update(sensors.keys())

    # Sort sensor names to ensure consistent colors
    sensor_names = sorted(sensor_names)
    num_sensors = len(sensor_names)

    if num_sensors == 0:
        logging.getLogger().warning('plot_temperature_curves() called with empty list!')
        if return_mem:
            return None
        else:
            return

    # Prepare curve colors and names
    idx = 0
    colors = dict()
    plot_labels = dict()
    for sn in sensor_names:
        colors[sn] = curve_color(idx)
        plot_labels[sn] = sn if name_mapping is None else name_mapping[sn]
        idx += 1

    # ## Extract curves
    # First, get suitable ticks based on the time span of the provided data
    x_tick_values, x_tick_labels, dt_tick_start = __prepare_ticks(temperature_log, desired_num_ticks=10)

    # Then extract the data points
    temperature_curves, was_heating = __prepare_curves(sensor_names, temperature_log, dt_tick_start, simplify_curves)

    # ## Now we're ready to plot
    # Prepare figure of proper size
    dpi = 100  # Dummy DPI value to compute figure size in inches
    fig = plt.figure(figsize=(width_px/dpi, height_px/dpi))
    if xkcd:
        plt.xkcd(scale=1, length=100, randomness=2)
    # Always change rcParams AFTER xkcd(), as it messes with the rcParams
    plt.rcParams.update({'font.size': font_size})
    ax = fig.gca()

    # Plot the curves
    num_skipped = 0
    def _line_style(lsidx):
        if alternate_line_styles:
            # Alternate line styles
            line_styles = ['-', '-.', '--']
            return line_styles[lsidx % len(line_styles)]
        else:
            return '-'
    line_style_idx = 0
    for sn in sensor_names:
        unzipped = tuple(zip(*temperature_curves[sn]))
        if len(unzipped) < 2:
            logging.getLogger().warning("Empty temperature curve for sensor '{:s}'.".format(sn))
            num_skipped += 1
            continue
        if smoothing_window > 2:
            values = smooth(unzipped[1], smoothing_window)
        else:
            values = unzipped[1]
        if draw_marker:
            ax.plot(unzipped[0], values,
                color=colors[sn], alpha=line_alpha, linestyle=_line_style(line_style_idx), linewidth=linewidth,
                label=plot_labels[sn],
                marker='.', markersize=5*linewidth, markeredgewidth=linewidth, zorder=10)
        else:
            ax.plot(unzipped[0], values,
                color=colors[sn], alpha=line_alpha, linestyle=_line_style(line_style_idx), linewidth=linewidth,
                label=plot_labels[sn], zorder=10)
        line_style_idx += 1
    # Skip adjustments if all curves were empty
    if num_skipped < len(sensor_names):
        # Adjust x-axis
        # See https://www.geeksforgeeks.org/python-matplotlib-pyplot-ticks/
        ax.tick_params(axis='x', rotation=65, direction='in')
        plt.xticks(x_tick_values, x_tick_labels)

        # Adjust y-axis
        ymin_initial, ymax = plt.ylim()
        span = ymax - ymin_initial
        # ... ensure y-axis spans a minimum amount of degrees
        delta = np.ceil(min_temperature_span - span)
        # ... if there are even more, increase the range slightly so
        # we get a nice top/bottom border
        if delta < 0:
            delta = 2
        ymin = ymin_initial - delta * 0.7
        ymax = ymax + delta * 0.3
        plt.ylim(ymin, ymax)

        # Adjust ticks on y-axis
        yminc = np.ceil(ymin)
        # ... we want a sufficient padding between bottom and the lowest temperature grid line
        if yminc - ymin < 0.8:
            yminc += 1
        # # ... be consistent: only show even temperature ticks
        # if yminc.astype(np.int32) % 2 == 1:
        #     yminc += 1

        y_ticks = range(yminc.astype(np.int32), ymax.astype(np.int32))
        y_tick_labels = ['{:d}°'.format(t) for t in y_ticks]
        ax.tick_params(axis='y', direction='in')
        plt.yticks(y_ticks, y_tick_labels)

        # Plot a curve (z-order behind temperature plots but above of grid)
        # indicating if heating was active
        unzipped = tuple(zip(*was_heating))
        heating_values = [ymax-1 if wh else ymin_initial-1 for wh in unzipped[1]]
        ax.plot(unzipped[0], heating_values,
                color=(.2, .2, .2), alpha=line_alpha, linestyle='--', linewidth=linewidth,
                label='Heizung', zorder=2)

        # Title and legend
        plt.title('Temperaturverlauf [°C]')
        ax.grid(True, linewidth=linewidth-0.5, alpha=grid_alpha)
        ax.legend(loc='lower center', fancybox=True,
            frameon=False, ncol=legend_columns)

    # => if frameon=True, set framealpha=0.3 See https://matplotlib.org/3.1.1/api/_as_gen/matplotlib.pyplot.legend.html
    # If we need to change the legend ordering:
    # https://stackoverflow.com/questions/22263807/how-is-order-of-items-in-matplotlib-legend-determined
    # handles, labels = plt.gca().get_legend_handles_labels()
    # order = range(len(labels))
    # ax.legend([handles[idx] for idx in order], [labels[idx] for idx in order], loc='lower center', fancybox=True,
    #     frameon=False, ncol=legend_columns)

    # ## Ensure that the figure is drawn/populated:
    # Remove white borders around the plot
    fig.tight_layout(pad=1.01)  # Default is pad=1.08
    fig.canvas.draw()

    # Export figure (and return it - unless we're debugging, then save and show)
    img_np = plt2img(fig, dpi=dpi)
    img_pil = np2pil(img_np)

    if return_mem:
        plt.close(fig)
        return pil2memfile(img_pil)
    else:
        img_pil.save('dummy-temperature.jpg')
        plt.show()


def pil2np(img_pil, flip_channels=False):
    """Convert Pillow.Image to numpy.array."""
    img_np = np.array(img_pil)
    if flip_channels and len(img_np.shape) == 3 and img_np.shape[2] == 3:
        # Convert RGB to BGR or vice versa
        return img_np[:, :, ::-1]
    else:
        return img_np


def pil2memfile(img_pil, name='image.jpg'):
    """Write the image into a buffer kept in RAM."""
    memfile = io.BytesIO()
    memfile.name = name
    img_pil.save(memfile, 'jpeg') #'png')
    memfile.seek(0)
    return memfile


def np2pil(img_np):
    """Convert numpy.array to Pillow.Image."""
    return Image.fromarray(img_np)


def np2memfile(img_np):
    """Convert numpy (image) array to ByteIO stream"""
    return pil2memfile(np2pil(img_np))


def plt2img(fig, dpi=180):
    """Render the matplotlib figure 'fig' as an image (numpy array)."""
    # Save plot to buffer...
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    # ... decode the buffer
    buf.seek(0)
    img_pil = Image.open(io.BytesIO(buf.getvalue()))
    buf.close()
    # ... return as numpy array (and remove alpha channel)
    img_np = pil2np(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 4:
        img_np = img_np[:, :, :3]
    return img_np

# def plt2img_lowres(fig):
#     img_np = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
#     print(fig.canvas.get_width_height())
#     img_np = img_np.reshape(fig.canvas.get_width_height()[::-1] + (3,))
#     return img_np


def rgb2gray(rgb):
    """Grayscale conversion for np.array inputs"""
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
    return gray.astype(rgb.dtype)
