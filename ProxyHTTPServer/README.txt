ProxyHTTPServer (version 0.0.1 - 2007.11.24)
"from the creator of PyWebRun"

Public domain (P) 2007 Davide Rognoni

DAVIDE ROGNONI DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS, IN NO EVENT SHALL DAVIDE ROGNONI BE LIABLE FOR
ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER
IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

E-mail: davide.rognoni@gmail.com


FILES LIST
----------
src/ProxyHTTPServer.py  proxy based on ThreadingTCPServer and BaseHTTPServer
src/logger.py           proxy based on ProxyHTTPServer
src/test.py             web server for proxy testing
README.txt


DEPENDENCES
-----------
Python 2.5.1


TUTORIAL
--------
Type in your console:
python ProxyHTTPServer.py

It run a local proxy server:
Serving HTTP on 0.0.0.0 port 8000 ...

You must configure your browser to use this proxy:
HTTP: 127.0.0.1
PORT: 8000

You can use others ports:
python ProxyHTTPServer.py 8001

The first test is to browse on web.
The second is to run the test server:
python test.py 8080

You must browse on:
http://localhost:8080/


LOGGER
------
Type in your console:
python logger.py

Configure your browser to use this proxy.
Browse on http://www.python.org

The logger proxy will make a HTML file, like this:
e7e3879e-9aa2-11dc-b850-444553540000.html

See the top file with a text editor:

REQUEST GET
http://www.python.org/
[...headers...]
[None with GET]

RESPONSE 200
[...headers...]

[...HTML...]
