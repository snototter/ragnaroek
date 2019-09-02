import libconf

#######################################################################
# Utilities
def slurp_stripped_lines(filename):
    with open(filename) as f:
        return [s.strip() for s in f.readlines()]

def load_api_token(filename='.api-token'):
    return slurp_stripped_lines(filename)
    #with open(filename) as f:
        #f.read().strip()
        #return [s.strip() for s in f.readlines()] 


def load_authorized_user_ids(filename='.authorized-ids'):
    return [int(id) for id in slurp_stripped_lines(filename)]


def load_configuration(filename='helheimr.cfg'):
    with open(filename) as f:
        return libconf.load(f)