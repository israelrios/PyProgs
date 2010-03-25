HTML = """\
<html>
<body>
	<form method="get">
		<input type="text" name="input1">
		<input type="text" name="input2">
		<input type="submit" value="get">
	</form>
	<form method="post">
		<input type="text" name="input1">
		<input type="text" name="input2">
		<input type="submit" value="post">
	</form>
	<form method="post" enctype="multipart/form-data">
	<input type="text" name="input1">
	<input type="file" name="input2">
	<input type="submit" value="post multipart">
	</form>
	<pre>client_address: %s
command: %s
path: %s
request_version: %s

<b>HEADERS</b>
%s
<b>CONTENT</b>
%s</pre>
</body>
</html>
"""

import BaseHTTPServer

class MonitorHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
		
	def doCommon(self):
		contentLength = self.headers.getheader("content-length")
		if contentLength:
			content = self.rfile.read(int(contentLength))
		else:
			content = None

		html = HTML % (str(self.client_address), self.command, self.path,
			self.request_version, str(self.headers), content)		
				
		self.send_response(200)
		self.send_header("Content-type", "text/html")
		self.send_header("Content-Length", str(len(html)))
		self.end_headers()
		self.wfile.write(html)
		
	def do_GET(self):
		self.doCommon()

	def do_POST(self):
		self.doCommon()
		
def test(HandlerClass = MonitorHTTPRequestHandler,
		ServerClass = BaseHTTPServer.HTTPServer):
	BaseHTTPServer.test(HandlerClass, ServerClass)

if __name__ == '__main__':
	test()
