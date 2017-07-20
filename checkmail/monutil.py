#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 14-jul-2010

from HTMLParser import HTMLParser
import re
import email.header
import os
import subprocess
import urllib
import urllib2
from httplib import HTTPSConnection as Https
import mimetypes
import mimetools
from htmlentitydefs import name2codepoint as n2cp
import sys

#Classe para extrair o texto do HTML
class HtmlTextParser(HTMLParser):

    def __init__(self):
        self.texto = ""
        HTMLParser.__init__(self)

    def handle_starttag(self, tag, attrs):
        pass

    def handle_data(self, data):
        self.texto = self.texto + data

    def handle_endtag(self, tag):
        pass


def getProwl():
    prowlkeyfile = os.path.join(
        os.getenv('USERPROFILE') or os.getenv('HOME') or os.path.abspath(os.path.dirname(sys.argv[0])), '.prowl.key')
    if not os.path.exists(prowlkeyfile):
        return None
    with open(prowlkeyfile, 'r') as f:
        key = f.read().strip()
    if not key:
        return None
    return Prowl(key)

patHeader = re.compile('\r\n[\t ]')
def decode_header(header):
    text = []
    lastAscii = None
    # "unfolding"
    dec = email.header.decode_header(patHeader.sub(' ', header.rstrip('\r\n')))
    for item in dec:
        curAscii = item[1] is None
        if lastAscii is not None and lastAscii != curAscii:
            text.append(' ')
        if curAscii:
            text.append(item[0])
        else:
            text.append(item[0].decode(item[1]))
        lastAscii = curAscii
    return ''.join(text)


def execute(cmd):
    pid = os.fork()
    if pid == 0:
        # To become the session leader of this new session and the process group
        # leader of the new process group, we call os.setsid().
        try:
            os.setsid()
            subprocess.Popen(cmd, close_fds=True)
        except:
            pass #ignore exceptions
        os._exit(os.EX_OK)
    else:
        os.waitpid(pid, 0)

###################################
# Response parser functions
def substitute_entity(match):
    ent = match.group(2)
    if match.group(1) == "#":
        return unichr(int(ent))
    else:
        cp = n2cp.get(ent)

        if cp:
            return unichr(cp)
        else:
            return match.group()

def decode_htmlentities(string):
    entity_re = re.compile("&(#?)(\d{1,5}|\w{1,8});")
    return entity_re.subn(substitute_entity, string)[0]

# Controls how sequences are encoded. If true, elements may be given multiple values by
#  assigning a sequence.
doseq = 1

##########################################################
# Peguei na NET esta classe para codificar os campos
# do formulário no formato multipart/form-data
class MultipartPostHandler(urllib2.BaseHandler):
    handler_order = urllib2.HTTPHandler.handler_order - 10 # needs to run first

    def http_request(self, request):
        data = request.get_data()
        if data is not None and type(data) != str:
            v_files = []
            v_vars = []
            try:
                for(key, value) in data.items():
                    if hasattr(value, 'read'):
                        v_files.append((key, value))
                    else:
                        v_vars.append((key, value))
            except TypeError, e:
                raise TypeError("not a valid non-string sequence or mapping object: " + str(e))

            if len(v_files) == 0:
                data = urllib.urlencode(v_vars, doseq)
            else:
                boundary, data = self.multipart_encode(v_vars, v_files)
                contenttype = 'multipart/form-data; boundary=%s' % boundary
                if request.has_header('Content-Type') and request.get_header('Content-Type').find('multipart/form-data') != 0:
                    print ("Replacing %s with %s" % (request.get_header('content-type'), 'multipart/form-data'))
                request.add_unredirected_header('Content-Type', contenttype)

            request.add_data(data)
        return request

    def multipart_encode(self, params, files, boundary = None, body = None):
        if boundary is None:
            boundary = mimetools.choose_boundary()
        if body is None:
            body = ''
        for(key, value) in params:
            body += '--%s\r\n' % boundary
            body += 'Content-Disposition: form-data; name="%s"' % key
            body += '\r\n\r\n' + str(value) + '\r\n'
        for(key, fd) in files:
            fd.seek(0, os.SEEK_END)
            file_size = fd.tell()
            if hasattr(fd, 'name'):
                filename = os.path.basename(fd.name)
            else:
                filename = 'inputfile'
            contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            body += '--%s\r\n' % boundary
            body += 'Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (key, filename)
            body += 'Content-Type: %s\r\n' % contenttype
            body += 'Content-Length: %s\r\n' % file_size
            fd.seek(0, os.SEEK_SET)
            body += '\r\n' + fd.read() + '\r\n'
        body += '--%s--\r\n\r\n' % boundary
        return boundary, body

    https_request = http_request
# end

##################################################################
# copiado do prowlpy e adaptado para incluir o parâmetro url
API_DOMAIN = 'prowl.weks.net'


class Prowl(object):
    def __init__(self, apikey, providerkey=None):
        """
        Initialize a Prowl instance.
        """
        self.apikey = apikey

        # Set User-Agent
        self.headers = {'User-Agent': "Prowlpy/0.42-isr",
                        'Content-type': "application/x-www-form-urlencoded"}

        # Aliasing
        self.add = self.post

    def post(self, application=None, event=None,
             description=None, url="", priority=0, providerkey=None):
        """
        Post a notification..

        You must provide either event or description or both.
        The parameters are :
        - application ; The name of your application or the application
          generating the event.
        - providerkey (optional) : your provider API key.
          Only necessary if you have been whitelisted.
        - priority (optional) : default value of 0 if not provided.
          An integer value ranging [-2, 2] representing:
             -2. Very Low
             -1. Moderate
              0. Normal
              1. High
              2. Emergency (note : emergency priority messages may bypass
                            quiet hours according to the user's settings)
        - event : the name of the event or subject of the notification.
        - description : a description of the event, generally terse.
        - url: url to open when the notification is activated.
        """

        # Create the http object
        h = Https(API_DOMAIN)

        # Perform the request and get the response headers and content
        data = {
            'apikey': self.apikey,
            'application': application,
            'event': event,
            'description': description,
            'url': url,
            'priority': priority
        }

        if providerkey is not None:
            data['providerkey'] = providerkey

        h.request("POST",
                  "/publicapi/add",
                  headers=self.headers,
                  body=urllib.urlencode(data))
        response = h.getresponse()
        request_status = response.status

        if request_status == 200:
            return True
        elif request_status == 401:
            raise Exception("Auth Failed: %s" % response.reason)
        else:
            raise Exception("Failed")
