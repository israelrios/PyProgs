import uuid
HTML = """\
<!--
REQUEST %(command)s
%(path)s
%(headers)s
%(body)s

RESPONSE %(resStatus)s
%(resHeaders)s
-->
%(resBody)s
"""

from ProxyHTTPServer import *

class LoggerHTTPRequestHandler(ProxyHTTPRequestHandler):

	def doCommon(self):	
		req = Request(self)
		req.delHeaders("accept-encoding", "host", "proxy-connection")
		
		res = req.getResponse()
		res.delHeader("transfer-encoding")
		
		write(req, res)
		res.toClient()
		
def write(req, res):
	type = res.getHeader("content-type")
	
	if type and type.find("text/htm") != -1:
		f = open(str(uuid.uuid1()) + ".html", "w")
		
		html = HTML % ({ "command" : req.command,
						"path" : req.path,
						"headers" : req.headers,
						"body" : req.body,
						"resStatus" : res.status,
						"resHeaders" : res.headers,
						"resBody" : res.body })
		f.write(html)
		f.close()
		
def test(HandlerClass = LoggerHTTPRequestHandler,
		ServerClass = ThreadingHTTPServer):
	BaseHTTPServer.test(HandlerClass, ServerClass)
	
if __name__ == '__main__':
	test()