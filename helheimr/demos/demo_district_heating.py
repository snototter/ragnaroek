import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from helu import common, district_heating

# This needs an actual ctrl.cfg with a valid 'district_heating' section
config = common.load_configuration(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'configs', 'ctrl.cfg'))
# Initialize the grabber
district_heating.DistrictHeating.init_instance(config)
# Parse the web interface
success, response = district_heating.DistrictHeating.instance().query_heating()
if success:
    print('Successfully queried district heating web interface:\n')
    print(response.to_telegram_message(use_markdown=False))
else:
    print('Error: \n{}'.format(response))