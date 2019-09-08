import libconf
from emoji import emojize
# import urllib3 #TODO adjust https://stackoverflow.com/questions/3764291/checking-network-connection for py3
# def internet_on():
#     try:
#         urllib3.urlopen('http://216.58.192.142', timeout=1)
#         return True
#     except urllib3.URLError as err: 
#         return False

#######################################################################
# Utilities
# def slurp_stripped_lines(filename):
#     with open(filename) as f:
#         return [s.strip() for s in f.readlines()]

# def load_api_token(filename='.api-token'):
#     return slurp_stripped_lines(filename)
#     #with open(filename) as f:
#         #f.read().strip()
#         #return [s.strip() for s in f.readlines()] 


# def load_authorized_user_ids(filename='.authorized-ids'):
#     return [int(id) for id in slurp_stripped_lines(filename)]

def emo(txt):
    # Convenience wrapper, since I often need/forget optional keywords ;-)
    return emojize(txt, use_aliases=True)

def load_configuration(filename):
    with open(filename) as f:
        return libconf.load(f)