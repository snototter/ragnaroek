import http.server
import socketserver
import json
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
        print('GOT GET')
        self.wfile.write(json.dumps({'request':'get', 'status':True}).encode())

    def do_HEAD(self):
        self._set_headers()
        
    def do_POST(self):
        self._set_headers()
        print('POST IT')
        self.wfile.write(json.dumps({'request':'post', 'status':False}).encode())
        
def run():#server_class=HTTPServer, handler_class=S, port=80):
    PORT = 8080
    handler = HelheimrServer
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()
    # server_address = ('', port)
    # httpd = server_class(server_address, handler_class)
    # print 'Starting httpd...'
    # httpd.serve_forever()

if __name__ == "__main__":
    # from sys import argv

    # if len(argv) == 2:
    #     run(port=int(argv[1]))
    # else:
    run()
