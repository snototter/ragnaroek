#!/usr/bin/python
# coding=utf-8
"""Basic drawing/plotting capabilities for temperature graphs, e-ink display, etc."""

import os
import matplotlib
# Set up headless on pi
if os.uname().machine.startswith('arm'):
    matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import logging
from PIL import Image
import io

from . import time_utils


def curve_color(idx, colormap=plt.cm.viridis, distinct_colors=10):
    """Return a unique color for the given idx (if idx < distinct_colors)."""
    lookup = np.linspace(0., 1., distinct_colors)
    c = colormap(lookup[idx % distinct_colors])
    return c[:3]


def plot_temperature_curves(width_px, height_px, temperature_log, 
    return_mem=True, xkcd=True, reverse=True, name_mapping=None,
    line_alpha=0.9, grid_alpha=0.3, linewidth=2.5, 
    every_nth_tick=3, tick_time_unit='minutes', #TODO!!!
    min_temperature_span=9,
    font_size=20, legend_columns=3):
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
        _, sensors = reading
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

    # Extract curves
    temperature_curves = {sn:list() for sn in sensor_names}
    x_tick_labels = list()
    was_heating = list()
    for idx in range(len(temperature_log)):
        dt_local, sensors, heating = temperature_log[idx]
        # x_tick_labels.append(dt_local) # TODO dt_local.hour : dt_local.minute or timedelta (now-dt_local) in minutes!

        #TODO 
        # timedelta(time_utils.dt_now_local() - dt_local)
        # Then either minutes or hours
        # adjust every_nth_tick (if plotting the full day) + h instead of minutes

        if idx % every_nth_tick == 0:
            x_tick_labels.append('{:d}:{:d}'.format(dt_local.hour, dt_local.minute)) # TODO dt_local.hour : dt_local.minute or timedelta (now-dt_local) in minutes!
        else:
            x_tick_labels.append('')

        was_heating.append((idx, heating))

        if sensors is None:
            continue

        for sn in sensors.keys():
            if sensors[sn] is None:
                continue
            temperature_curves[sn].append((idx, sensors[sn]))
    

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
        ax.plot(unzipped[0], unzipped[1], \
            color=colors[sn], alpha=line_alpha, linestyle='-', linewidth=linewidth, \
            label=plot_labels[sn], marker='.', markersize=5*linewidth, markeredgewidth=linewidth)

    # Adjust x-axis
    ax.tick_params(axis ='x', rotation=45, direction='in') # See https://www.geeksforgeeks.org/python-matplotlib-pyplot-ticks/
    plt.xticks(range(len(x_tick_labels)), x_tick_labels)

    # Adjust y-axis
    ymin, ymax = plt.ylim()
    span = ymax - ymin
    # ... ensure y-axis spans a minimum amount of degrees
    delta = np.ceil(min_temperature_span - span)
    # ... if there are even more, increase the range slightly so 
    # we get a nice top/bottom border
    if delta < 0:
        delta = 2
    ymin = ymin - delta * 0.7
    ymax = ymax + delta * 0.3
    plt.ylim(ymin, ymax)
    
    # Adjust ticks on y-axis
    yminc = np.ceil(ymin)
    # ... we want a sufficient padding between bottom and the lowest temperature grid line
    if yminc - ymin < 0.5:
        yminc += 1
    # ... be consistent: only show even temperature ticks
    if yminc.astype(np.int32) % 2 == 1:
        yminc += 1
    
    y_ticks = range(yminc.astype(np.int32), ymax.astype(np.int32), 2)
    y_tick_labels = ['{:d}°'.format(t) for t in y_ticks]
    ax.tick_params(axis='y', direction='in')
    plt.yticks(y_ticks, y_tick_labels)

    # Plot a curve indicating if heating was active
    unzipped = tuple(zip(*was_heating))
    heating_values = [ymax-1 if wh else yminc for wh in unzipped[1]]
    ax.plot(unzipped[0], heating_values, \
            color=(1,0,0), alpha=line_alpha, linestyle='-', linewidth=linewidth, \
            label='Heizungsstatus')

    # Title and legend
    plt.title('Temperaturverlauf [°C]')
    ax.grid(True, linewidth=linewidth-0.5, alpha=grid_alpha)
    ax.legend(loc='lower center', fancybox=True, 
        frameon=False, ncol=legend_columns)
     #if frameon=True, set framealpha=0.3 See https://matplotlib.org/3.1.1/api/_as_gen/matplotlib.pyplot.legend.html

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

    
