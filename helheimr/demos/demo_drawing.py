import matplotlib.pyplot as plt
import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from helu import common, drawing, time_utils

## Example data
# The mapping madness is due to the deconz/zigbee abstraction and plotting
# requirements:
# * deconz sensor IDs may change irregularly (but their name stays the same, ugh)
# * for short legends/table cells we need an abbreviation
# * for log messages we need the full room name
abbreviations = {
        'Schlafzimmer': 'SZ',
        'Kinderzimmer': 'KZ',
        'Wohnzimmer': 'WZ',
        'Bad': 'Bad',
        'Büro': 'AZ'
    }
abbreviations2displaynames = {v:k for k,v in abbreviations.items()}
temp_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temperature.log')

def load_temperature_log(filename):
    lines = common.tail(filename, lines=300)
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

log = load_temperature_log(temp_log)
drawing.plot_temperature_curves(1024, 768, log,
        return_mem=False, xkcd=True, reverse=False,
        name_mapping=abbreviations2displaynames,
        line_alpha=0.7, grid_alpha=0.3, linewidth=3.5,
        min_temperature_span=9, smoothing_window=7,
        font_size=20, legend_columns=2,
        draw_marker=False)
