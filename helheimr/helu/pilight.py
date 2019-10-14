"""
Since our OSRAM smart plugs were pretty unreliable (maybe due to 
2.4G interference from my neighbors' WIFI), we switched to 433.92 MHz
controllable power plugs.
Fortunately, pilight provides a REST API ;-)
"""

def get_api_url(cfg):
    gateway = cfg['pilight']['gateway']
    tcp_port = cfg['pilight']['port']
    return 'http://' + gateway + ':' + str(tcp_port)

def get_config_url(cfg):
    return get_api_url(cfg) + '/config'