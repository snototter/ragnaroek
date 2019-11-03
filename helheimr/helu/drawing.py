#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

import matplotlib
# Set up headless on pi
# import os
# if os.uname().machine.startswith('arm'):
    # matplotlib.use('Agg')
# matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import datetime
import logging
from PIL import Image
import io

from . import time_utils
from dateutil import tz


def curve_color(idx, colormap=plt.cm.viridis, distinct_colors=10):
    """Return a unique color for the given idx (if idx < distinct_colors)."""
    lookup = np.linspace(0., 1., distinct_colors)
    c = colormap(lookup[idx % distinct_colors])
    return c[:3]

def __replace_tz(dt):
    return dt.replace(tzinfo=tz.tzutc())

def __naive_time_diff(dt_a, dt_b):
    a = __replace_tz(dt_a)
    b = __replace_tz(dt_b)
    if a > b:
        return a - b
    return b - a


def __prepare_ticks(temperature_log, desired_num_ticks=10):
    def _tm(reading):
        return reading[0]
    dt_end = _tm(temperature_log[-1])
    # dt_end = time_utils.dt_now_local()
    dt_start = _tm(temperature_log[0])
    
    # Find best fitting tick interval
    # time_span = dt_end - dt_start
    time_span = __naive_time_diff(dt_end, dt_start)
    sec_per_tick = time_span.total_seconds() / desired_num_ticks
    # print('PREPARE TICKS:', dt_start, "...", dt_end, ' time spanned: ', time_span)

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
    # num_ticks = int(np.ceil(time_span.total_seconds() / closest_tick_unit).astype(np.int32))
    # offset = 0
    ## Version B, floor
    num_ticks = int(np.floor(time_span.total_seconds() / closest_tick_unit).astype(np.int32))
    offset = closest_tick_unit

    tick_values = list()
    tick_labels = list()
    for i in range(num_ticks):
        tick_sec = i * closest_tick_unit + offset
        dt_tick = dt_tick_start + datetime.timedelta(seconds=tick_sec)
        tick_lbl = '-' + time_utils.format_timedelta(dt_end - dt_tick, small_space=False)
        tick_values.append(tick_sec)
        tick_labels.append(tick_lbl)
    # Add end/current date
    dt_now = time_utils.dt_now_local()

    tick_sec = num_ticks * closest_tick_unit + offset
    tick_values.append(tick_sec)
    dt_tick = dt_tick_start + datetime.timedelta(seconds=tick_sec)
    if dt_now.date() == dt_tick.date():
        tick_labels.append('{:02d}:{:02d}'.format(dt_tick.hour, dt_tick.minute))
    else:
        tick_labels.append(dt_tick.strftime('%d.%m.%Y %H:%M'))
    
    return tick_values, tick_labels, dt_tick_start


def __prepare_curves(sensor_names, temperature_log, dt_tick_start):
    temperature_curves = {sn:list() for sn in sensor_names}
    was_heating = list()
    for reading in temperature_log:
        dt_local, sensors, heating = reading

        td = __naive_time_diff(dt_local, dt_tick_start)
        dt_tick_offset = td.total_seconds()
        # print('\n', time_utils.format(dt_local), ' VS ', time_utils.format(dt_tick_start), ' === ', time_utils.days_hours_minutes_seconds(td))

        was_heating.append((dt_tick_offset, heating))

        if sensors is None:
            continue

        for sn in sensors.keys():
            if sensors[sn] is None:
                continue
            temperature_curves[sn].append((dt_tick_offset, sensors[sn]))
    return temperature_curves, was_heating



def plot_temperature_curves(width_px, height_px, temperature_log, 
    return_mem=True, xkcd=True, reverse=True, name_mapping=None,
    line_alpha=0.9, grid_alpha=0.3, linewidth=2.5, 
    min_temperature_span=9,
    font_size=20, legend_columns=2,
    draw_marker=False):
    """
    return_mem: save plot into a BytesIO buffer and return it, otherwise shows the plot (blocking, for debug)
    xkcd: :-)
    reverse: reverse the temperature readings (if temperature_log[0] is the most recent reading)
    name_mapping: provide a dictionary if you want to rename the curves

    every_nth_tick: label every n-th tick only
    tick_time_unit: should the time difference (tick label) be stated as 'minutes' or 'hours'
    min_temperature_span: the y-axis should span at least these many degrees
    """
    ### Prepare the data
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
        colors[sn] = curve_color(idx, colormap=plt.cm.winter, distinct_colors=num_sensors)
        plot_labels[sn] = sn if name_mapping is None else name_mapping[sn]
        idx += 1

    ### Extract curves
    # First, get suitable ticks based on the time span of the provided data
    x_tick_values, x_tick_labels, dt_tick_start = __prepare_ticks(temperature_log, desired_num_ticks=10)
    
    # Then extract the data points
    temperature_curves, was_heating = __prepare_curves(sensor_names, temperature_log, dt_tick_start)
    

    ### Now we're ready to plot
    # Prepare figure of proper size
    dpi = 100 # Dummy DPI value to compute figure size in inches
    fig = plt.figure(figsize=(width_px/dpi, height_px/dpi))
    if xkcd:
        plt.xkcd(scale=1, length=100, randomness=2)
    # Always change rcParams AFTER xkcd(), as it messes with the rcParams
    plt.rcParams.update({'font.size': font_size})
    ax = fig.gca()

    # Plot the curves
    for sn in sensor_names:
        unzipped = tuple(zip(*temperature_curves[sn]))
        if draw_marker:
            ax.plot(unzipped[0], unzipped[1], \
                color=colors[sn], alpha=line_alpha, linestyle='-', linewidth=linewidth, \
                label=plot_labels[sn], 
                marker='.', markersize=5*linewidth, markeredgewidth=linewidth, zorder=10)
        else:
            ax.plot(unzipped[0], unzipped[1], \
                color=colors[sn], alpha=line_alpha, linestyle='-', linewidth=linewidth, \
                label=plot_labels[sn], zorder=10)

    # Adjust x-axis
    ax.tick_params(axis ='x', rotation=45, direction='in') # See https://www.geeksforgeeks.org/python-matplotlib-pyplot-ticks/
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
    
    y_ticks = range(yminc.astype(np.int32), ymax.astype(np.int32))#, 2)
    y_tick_labels = ['{:d}°'.format(t) for t in y_ticks]
    ax.tick_params(axis='y', direction='in')
    plt.yticks(y_ticks, y_tick_labels)

    # Plot a curve (z-order behind temperature plots but above of grid) 
    # indicating if heating was active
    unzipped = tuple(zip(*was_heating))
    heating_values = [ymax-1 if wh else ymin_initial-1 for wh in unzipped[1]]
    ax.plot(unzipped[0], heating_values, \
            color=(1,0,0), alpha=line_alpha, linestyle='-', linewidth=linewidth, \
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

    ### Ensure that the figure is drawn/populated:
    # Remove white borders around the plot
    fig.tight_layout(pad=1.01) # Default is pad=1.08
    fig.canvas.draw()

    ### Export figure (and return or show it)
    img_np = plt2img(fig, dpi=dpi)
    img_pil = np2pil(img_np)

    if return_mem:
        return pil2memfile(img_pil)
    else:
        img_pil.save('dummy-temperature.jpg')
        plt.show()


def pil2np(img_pil, flip_channels=False):
    """Convert Pillow.Image to numpy.array."""
    img_np = np.array(img_pil)
    if len(img_np.shape) == 3 and img_np.shape[2] == 3 and flip_channels:
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
    # print('converting {}'.format(np_data.shape))
    # TODO handle grayvalue (call standard data.transpose)
    # if rotate:
    #     np_data = np.flip(np.transpose(np_data, (1,0,2)), axis=1)
    return pil2memfile(np2pil(img_np))


def plt2img(fig, dpi=180):
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
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
    return gray.astype(rgb.dtype)




##### matplotlib:
# * Lookup
#   https://matplotlib.org/api/_as_gen/matplotlib.pyplot.html#module-matplotlib.pyplot
# * Reduce margins/white borders:
#   https://stackoverflow.com/questions/4042192/reduce-left-and-right-margins-in-matplotlib-plot
# * Change font properties:
#   https://matplotlib.org/3.1.1/gallery/text_labels_and_annotations/text_fontdict.html
# * Grid 
#   https://stackoverflow.com/questions/8209568/how-do-i-draw-a-grid-onto-a-plot-in-python
# * Colormaps
#   https://matplotlib.org/3.1.0/tutorials/colors/colormaps.html
#   https://stackoverflow.com/questions/8931268/using-colormaps-to-set-color-of-line-in-matplotlib

if __name__ == '__main__':
    import collections
    dt = collections.namedtuple('dt', ['hour', 'minute'])
    plot_temperature_curves(1024, 768, 
        [(dt(0,5),{'K':23.5}), (dt(0,10),{'K':23.5, 'W':22}), (dt(0,15),{'K':25.5, 'W':24}),
        (dt(0,20), {'K':None, 'W':23}), (dt(0,25), {'K':22}), (dt(0,30), None), (dt(0,35), {'Foo':25}), 
        (dt(0,40), {'Foo':25.2, 'K':22.3})], return_mem=False, name_mapping={'K':'KiZi', 'W':'Wohnen', 'Foo':'xkcd:-)'}, reverse=False)
    if True:
        raise RuntimeError('stop')

    target_fig_size_px = [1024, 768]
    dpi = 100
    fig = plt.figure(figsize=tuple([t/dpi for t in target_fig_size_px]))
    axes = fig.add_subplot(111)
    # axes = fig.gca()

    with plt.xkcd():
        x = np.arange(0., 5., 0.2)
        axes.plot(x, x, 'r--')
        axes.plot(x, x**2, 'bs')
        

    #     ax = fig.gca()
        axes.set_xticks(np.arange(0, 5, 0.5))
        axes.set_yticks(np.arange(0, 20, 2))
    # plt.scatter(x, y)
        plt.xlim(-1, 4.4)
        plt.ylim(0.25, 20)
        # axes.grid()
        plt.grid()
    # plt.show()

        plt.title('jabadabadoo')
        # # Change font, put labels, etc.
        # font = {'family': 'xkcd Script', #'serif',
        #     'color':  'darkred',
        #     'weight': 'normal',
        #     'size': 16,
        #     }
        # plt.title('Title Foo', fontdict=font)
        # plt.text(2, 0.65, r'$\cos(2 \pi t) \exp(-t)$', fontdict=font)
        # plt.xlabel('time (s)', fontdict=font)
        # plt.ylabel('voltage (mV)', fontdict=font)

    # After all axes have been added, we can remove the white space around the axes:
    fig.tight_layout()
    # If run headless, we must ensure that the figure canvas is populated:
    fig.canvas.draw()

    ## Export lowres first (hires changes the figure, so there would be no difference)
    # img_lowres = plt2img_lowres(fig)
    # img_pil = np2pil(img_lowres)
    # img_pil.save('dummy-lowres.jpg')

    img_highres = plt2img(fig, dpi=2*dpi)
    img_pil = np2pil(img_highres)
    img_pil.save('dummy-hires.jpg')

    plt.show()

    
