#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2010 Israel Rios
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Changed by Israel Rios for better support to POST requests and to provide url "obfuscation"
#
# Based on work from Brett Slatkin (bslatkin@gmail.com)
__author__ = "Israel Rios (isrrios@gmail.com)"

import cgi
import logging
import re
import os
import urllib
import urlparse

from google.appengine.api import urlfetch
import webapp2 as webapp
import jinja2
from google.appengine.runtime import apiproxy_errors

import transform_content

jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

################################################################################

DEBUG = False
EXPIRATION_DELTA_SECONDS = 3600
EXPIRATION_RECENT_URLS_SECONDS = 90

# # DEBUG = True
# # EXPIRATION_DELTA_SECONDS = 10
# # EXPIRATION_RECENT_URLS_SECONDS = 1

HTTP_PREFIX = "http://"
HTTPS_PREFIX = "http://"

IGNORE_HEADERS = frozenset([
  # Ignore hop-by-hop headers
  'connection',
  'proxy-connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
])

TRANSFORMED_CONTENT_TYPES = frozenset([
  "text/html",
  "text/css",
])

MIRROR_HOSTS = frozenset([
  'mirrorr.com',
  'mirrorrr.com',
  'www.mirrorr.com',
  'www.mirrorrr.com',
  'www1.mirrorrr.com',
  'www2.mirrorrr.com',
  'www3.mirrorrr.com',
])

MAX_CONTENT_SIZE = 10 ** 6

MAX_URL_DISPLAY_LENGTH = 50

class Client(object):
    def __init__(self):
        pass

    def go(self, base_url, mirrored_url, rdata, rheaders_orig):
        """Fetch a page.

        Args:
          base_url: The hostname of the page that's being mirrored.
          mirrored_url: The URL of the original page. Hostname should match
            the base_url.
          rdata: request body.
          rheaders: request headers.

        Returns:
          True on success.
        """
        # Check for the X-Mirrorrr header to ignore potential loops.
        if base_url in MIRROR_HOSTS:
            logging.warning('Encountered recursive request for "%s"; ignoring', mirrored_url)
            return False

        try:
            rheaders = dict()

            for key in rheaders_orig.keys():
                if not key in ['Referer', 'Content-Length', 'Connection', 'Proxy-Connection', 'Keep-Alive', 'Host']:
                    rheaders[key] = rheaders_orig.get(key, "")

            logging.debug(str(rheaders))

            if rdata is not None and len(rdata) > 0:
                logging.debug('Doing Post...')
                self.response = urlfetch.fetch(mirrored_url, payload=rdata, method=urlfetch.POST, headers=rheaders, follow_redirects=False, deadline=10)
            else:
                # logging.debug("Cookie: %s", rheaders.get('Cookie', ''))
                self.response = urlfetch.fetch(mirrored_url, headers=rheaders, follow_redirects=False, deadline=10)
        except (urlfetch.Error, apiproxy_errors.Error):
            logging.exception("Could not fetch URL")
            return False

        return True

################################################################################

class BaseHandler(webapp.RequestHandler):
    def get_relative_url(self):
        slash = self.request.url.find("/", len(self.request.scheme + "://"))
        if slash == -1:
            return "/"
        return self.request.url[slash:]


class HomeHandler(BaseHandler):
    def get(self):
        return self.post()

    def post(self):
        # Handle the input form to redirect the user to a relative url
        form_url = self.request.get("url")
        logging.info("Request url: %s", form_url)
        if form_url:
            # Accept URLs that still have a leading 'http://'
            inputted_url = urllib.unquote(form_url)
            if inputted_url.startswith(HTTP_PREFIX):
                inputted_url = inputted_url[len(HTTP_PREFIX):]

            return self.redirect("/" + transform_content.encodeUrl(inputted_url))

        template = jinja_env.get_template('main.html')
        self.response.write(template.render())


class MirrorHandler(BaseHandler):
    def post(self, url):
        return self.get(url)

    def get(self, raw_address):
        if raw_address == 'favicon.ico' or raw_address == 'none':
            return self.error(404)

        translated_address = transform_content.decodeUrl(raw_address)

        base_url = re.search(r"/*([^/]+)", translated_address).group(1);

        assert base_url

        # check for request without a base path, includes the referer base path if necessary
        if raw_address == translated_address and 'Referer' in self.request.headers:
            referer = transform_content.decodeUrl(self.request.headers['Referer'])
            refmo = re.search(r"://[^/]+/+([^/]+)", referer)
            if refmo is not None:
                refbase = refmo.group(1);
                if base_url != refbase:
                    logging.debug("Basing address on: %s", refbase)
                    translated_address = refbase + '/' + translated_address
                    base_url = refbase

        # Log the user-agent and referrer, to see who is linking to us.
        logging.debug('User-Agent = "%s", Referrer = "%s"',
                      self.request.user_agent,
                      transform_content.decodeUrl(self.request.referer))
        logging.debug('Base_url = "%s", url = "%s"', base_url, self.request.url)

        mirrored_url = HTTP_PREFIX + translated_address

        logging.info("Handling request for '%s'", mirrored_url)

        client = Client()
        success = client.go(base_url, mirrored_url, self.request.body, self.request.headers)
        if not success:
            return self.error(404)

        cres = client.response

        for key, value in cres.headers.iteritems():
            if key not in IGNORE_HEADERS:
                if key.lower() == 'location':
                    # redirection
                    if not value.startswith('http://') and not value.startswith('https://'):
                        logging.debug('Adjusting Location: %s', value)
                        value = urlparse.urljoin(mirrored_url, value)

                    logging.debug("Location: %s", value)
                    value = urlparse.urljoin(self.request.uri, transform_content.encodeUrl(re.sub(r"^https?://", "/", value)))
                    logging.info("Redirecting to '%s'", value)
                self.response.headers[key] = value

        content = cres.content
        if content:
            page_content_type = cres.headers.get("content-type", "")
            for content_type in TRANSFORMED_CONTENT_TYPES:
                # Startswith() because there could be a 'charset=UTF-8' in the header.
                if page_content_type.startswith(content_type):
                    content = transform_content.TransformContent(base_url, mirrored_url, content)
                    break
            logging.debug("Len: %dB", len(content))
            self.response.write(content)

        self.response.set_status(cres.status_code)


class ProxyServerHandler(BaseHandler):
    def post(self, url):
        return self.get(url)

    def getContent(self, response):
        return response.content


    def writeHeaders(self, cres):
        for key, value in cres.headers.iteritems():
            if key not in IGNORE_HEADERS:
                self.response.headers[key] = value

    def get(self, url):
        url = url.replace('-', '://', 1)
        mirrored_url = transform_content.decodeUrl(url)

        base_url = re.search(r"/*([^/]+)", mirrored_url).group(1);
        assert base_url
        logging.info("Proxy serving request for '%s'", mirrored_url)

        client = Client()
        success = client.go(base_url, mirrored_url, self.request.body, self.request.headers)
        if not success:
            return self.error(404)

        cres = client.response
        self.writeHeaders(cres)
        content = self.getContent(cres)
        if content:
            logging.debug("Len: %dB", len(content))
            self.response.write(content)
        self.response.set_status(cres.status_code)


class XorProxyServerHandler(ProxyServerHandler):

    def getContent(self, cres):
        content = ProxyServerHandler.getContent(self, cres)
        return ''.join([chr(ord(i) ^ 0xF3) for i in content])


class YoutubeHandler(webapp.RequestHandler):

    def get(self, videoid):
        logging.info("Downloading video '%s'", videoid)

        resp = urlfetch.fetch('http://www.youtube.com/get_video_info?&video_id=' + videoid)
        if hasattr(urlparse, 'parse_qs'):
            parse_qs = urlparse.parse_qs
        else:
            parse_qs = cgi.parse_qs
        infomap = parse_qs(resp.content.decode('utf-8'))
        # token = infomap['token'][0]
        # url = "https://www.youtube.com/get_video?" + urllib.urlencode({'video_id': videoid, 't': token, 'fmt': '18', 'asv': 2})
        url_stream = parse_qs(infomap['url_encoded_fmt_stream_map'][0])
        url = url_stream['url'][0]
        # logging.info(url_stream['url'])
        logging.info("Downloading '%s'", url)
        resp = urlfetch.fetch(url)

        for key, value in resp.headers.iteritems():
            if key not in IGNORE_HEADERS:
                self.response.headers[key] = value
        content = resp.content
        if content:
            logging.debug("Len: %dB", len(content))
            self.response.write(content)
        self.response.set_status(resp.status_code)


app = webapp.WSGIApplication([
  (r"/", HomeHandler),
  (r"/main", HomeHandler),
  (r"/ps/(.+)", ProxyServerHandler),
  (r"/xps/(.+)", XorProxyServerHandler),
  (r"/ytb/(.+)", YoutubeHandler),
  (r"/(.+)", MirrorHandler)
], debug=DEBUG)

