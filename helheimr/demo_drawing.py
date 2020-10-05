# import numpy as np
# import matplotlib
# import matplotlib.pyplot as plt
# from matplotlib import cm

# # Pie chart, where the slices will be ordered and plotted counter-clockwise:
# N = 6
# labels = ['Part #{}'.format(i+1) for i in range(N)]
# sizes = [100/N] * N
# #explode = (0, 0.1, 0, 0)  # only "explode" the 2nd slice (i.e. 'Hogs')
# explode = tuple([0]*N)

# # try different colormaps
# #https://matplotlib.org/3.1.1/tutorials/colors/colormaps.html
# mapfx = [cm.Paired, cm.Set1, cm.Set2, cm.Dark2]
# for mfx in mapfx:
#   cs = mfx(np.arange(N))#/float(N))

#   fig1, ax1 = plt.subplots()
#   ax1.pie(sizes, explode=explode, labels=labels, autopct='%1.1f%%',
#           shadow=True, startangle=90, colors=cs)
#   ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

#   plt.show()


import os
import sys
sys.path.append('.')
import matplotlib.pyplot as plt

from helu import common, drawing, time_utils

abbreviations = {
        'Schlafzimmer': 'SZ',
        'Kinderzimmer': 'KZ',
        'Wohnzimmer': 'WZ',
        'Bad': 'Bad',
        'Büro': 'AZ'
    }
abbreviations2displaynames = {v:k for k,v in abbreviations.items()}

def load_demo_temperature_log():
    lines = common.tail(os.path.join('demo-data', 'temperature.log'), lines=300)
    if lines is None:
        return list()
    
    temperature_readings = list()
    for line in lines:
        tokens = line.split(';')
        dt = time_utils.dt_fromstr(tokens[0])
        temps = dict()
        for i in range(1, len(tokens)-1, 2):
            display_name = tokens[i]
            abbreviation = abbreviations[display_name]
            t = tokens[i+1].strip()
            if t.lower() == 'n/a':
                    temps[abbreviation] = None
            else:
                    temps[abbreviation] = float(t)
        # The last token holds the heating state
        hs = True if tokens[-1] == '1' else False
        temperature_readings.append((dt, temps, hs))
    return temperature_readings

log = load_demo_temperature_log()
drawing.plot_temperature_curves(1024, 768, log,
        return_mem=False, xkcd=True, reverse=True, name_mapping=abbreviations2displaynames,
        line_alpha=0.7, grid_alpha=0.3, linewidth=3.5,
        min_temperature_span=9, smoothing_window=7,
        font_size=20, legend_columns=2,
        draw_marker=False)
