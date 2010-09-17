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
import mimetypes
import mimetools

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


patHeader = re.compile('\r\n[\t ]')
def decode_header(header):
    text = []
    lastAscii = None
    # "unfolding"
    dec = email.header.decode_header(patHeader.sub(' ', header.rstrip('\r\n')))
    for item in dec:
        curAscii = item[1] == None
        if lastAscii != None and lastAscii != curAscii:
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
                    log( "Replacing %s with %s" % (request.get_header('content-type'), 'multipart/form-data') )
                request.add_unredirected_header('Content-Type', contenttype)

            request.add_data(data)
        return request

    def multipart_encode(self, vars, files, boundary = None, buffer = None):
        if boundary is None:
            boundary = mimetools.choose_boundary()
        if buffer is None:
            buffer = ''
        for(key, value) in vars:
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; name="%s"' % key
            buffer += '\r\n\r\n' + str(value) + '\r\n'
        for(key, fd) in files:
            fd.seek(0, os.SEEK_END)
            file_size = fd.tell()
            if hasattr(fd, 'name'):
                filename = os.path.basename(fd.name)
            else:
                filename = 'inputfile'
            contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (key, filename)
            buffer += 'Content-Type: %s\r\n' % contenttype
            buffer += 'Content-Length: %s\r\n' % file_size
            fd.seek(0, os.SEEK_SET)
            buffer += '\r\n' + fd.read() + '\r\n'
        buffer += '--%s--\r\n\r\n' % boundary
        return boundary, buffer

    https_request = http_request
# end
