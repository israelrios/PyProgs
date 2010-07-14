#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 14-jul-2010

from HTMLParser import HTMLParser
import re
import email.header
import os
import subprocess

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


patHeader = re.compile('\r\n[t ]')
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
