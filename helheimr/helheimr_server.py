import http.server
import json
import logging
import socketserver
from urllib.parse import urlparse

import helheimr_utils as hu

#https://gist.github.com/nitaku/10d0662536f37a087e1b

class HelheimrServer(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super(HelheimrServer, self).__init__(*args, **kwargs)


    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()


    def do_GET(self):
        self._set_headers()
        up = urlparse(self.path)
        logging.getLogger().info('Incoming query: {}\n\n{}\n\n'.format(self.path, up))
        self.wfile.write(json.dumps({'request':'get', 'status':True}).encode())


    def do_HEAD(self):
        self._set_headers()


    def do_POST(self):
        self._set_headers()
        print('POST IT')
        query = urlparse(self.path)
        query_components = parse_qs(urlparse(self.path).query)
        logging.getLogger().info('Incoming query: {}\n\n{}\n\n'.format(query, query_components))
        self.wfile.write(json.dumps({'request':'post', 'status':False}).encode())

        # # import cgi
        # ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        
        # # refuse to receive non-json content
        # if ctype != 'application/json':
        #     self.send_response(400)
        #     self.end_headers()
        #     return
        # # read the message and convert it into a python dictionary
        # length = int(self.headers.getheader('content-length'))
        # message = json.loads(self.rfile.read(length))
        
        # # add a property to the object, just to mess with data
        # message['received'] = 'ok'
        
        # # send the message back
        # self._set_headers()
        # self.wfile.write(json.dumps(message))


def run_ctrl_server():
    cfg = hu.load_configuration('configs/ctrl.cfg')

    #logging.getLogger().info(cfg)
    listen_on_host = cfg['server']['host']
    listen_on_port = cfg['server']['port']

    with socketserver.TCPServer((listen_on_host, listen_on_port), HelheimrServer) as httpd:
        logging.getLogger().info('Helheimr is now serving at {:s}:{:d}'.format(listen_on_host, listen_on_port))
        httpd.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, #TODO switch to info!
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    run_ctrl_server()
