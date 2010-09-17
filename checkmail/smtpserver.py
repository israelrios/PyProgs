#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 16-set-2010

import os
import sys
import re
import smtpd
import asyncore
import urllib2
import urllib
import Queue
import threading
from cStringIO import StringIO
from monutil import MultipartPostHandler


class SmtpServer(smtpd.SMTPServer):
    def __init__(self):
        smtpd.SMTPServer.__init__(self, ('localhost', 8025), ('localhost', 25))
        self.patTo = re.compile('^To:(([ \t].+?\r\n)+)', re.MULTILINE | re.IGNORECASE)
        self.patSubject = re.compile('^Subject:(([ \t].+?\r\n)+)', re.MULTILINE | re.IGNORECASE)
        self.sender = Sender()
        self.sender.start()

    def quit(self):
        self.sender.quit()
        self.sender.join()
        
    def process_message(self, peer, mailfrom, rcpttos, data):
        print "peer:", peer

        if not peer[0] in ('127.0.0.1', 'localhost'):
            return '451 Not Authorized'

        print "mailfrom:", mailfrom
        print "rcptos:", rcpttos
        try:
            endheader = data.index('\n\n')
            headers = data[:endheader].replace('\n', '\r\n').rstrip()
            data = data[endheader+2:]
            
            subject = ''
            to = self.patTo.search(headers).group(1).strip()
            mo = self.patSubject.search(headers)
            if mo is not None:
                subject = mo.group(1).strip()

            headers = self.patTo.sub('', headers)
            headers = self.patSubject.sub('', headers)

            #print 'headers:', headers
            #print 'body:', data[:1000]
            bodyfile = StringIO(data)

            self.sender.send({'subject': subject, 'from': mailfrom, 'to': to, 'headers': headers, 'body': bodyfile})
        except Exception, e:
            print "Error:", e
            return '451 Requested action aborted: error in processing'

class Sender(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.q = Queue.Queue(2) # 2 é o tamanho máximo, acima disso o thread que chamou fica esperando
        self.quitObject = 'quit'
        self.opener = urllib2.build_opener(MultipartPostHandler)
        # pegando o código que libera o envio de email e a url
        curdir = os.path.abspath( os.path.dirname(sys.argv[0]) )
        f = open(os.path.join(curdir, 'smtpconf'), 'r')
        conf = f.readlines()
        f.close()
        self.code = conf[0].strip()
        self.url = conf[1].strip()

    def send(self, params):
        self.q.put(params)

    def quit(self):
        self.q.put(self.quitObject)

    def _send(self, params):
        params['code'] = self.code
        url = self.opener.open(self.url, params)
        resp = str(url.read()).strip()
        url.close()
        print resp
        return (resp == 'Mail sent')

    def _sendback(self, params):
        bodyfile = StringIO((u'Não foi possível enviar o email para ' + params['to'] + '.').encode('iso8859-1'))
        return self._send({'subject': 'Email Falhou: ' + params['subject'], 'to': params['from'],
                           'headers': 'Content-Type: text/plain; charset=iso-8859-1;', 'body': bodyfile})

    def run(self):
        while True:
            params = self.q.get()
            if params == self.quitObject:
                return
            try:
                if not self._send(params):
                    self._sendback(params)
            except Exception, e:
                print e
                try:
                    self._sendback(params)
                except Exception, e:
                    print e


if __name__ == '__main__':
    server = SmtpServer()
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        pass
    finally:
        server.quit()
