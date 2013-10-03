#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 02-out-2013

import multiprocessing
import cookielib
import urllib2
from monutil import MultipartPostHandler
import Queue

class TimeoutException(Exception):
    def __init__(self):
        Exception.__init__(self, _(u"Request timed out"))

WORK_EXIT = "EXIT"
TIMEOUT = 60  # segundos

class Response(object):
    def __init__(self, orig, cookies):
        self._buf = orig.read()
        self._info = orig.info()
        self.url = orig.url
        self.cookies = []
        for cookie in cookies:
            self.cookies.append((cookie.name, cookie.value))
        orig.close()

    def read(self):
        return self._buf

    def close(self):
        pass

    def info(self):
        return self._info

class RequestProcessor(object):
    def __init__(self, defaultHeaders=[]):
        self.headers = defaultHeaders
        self.proc = None
        self.cookies = []

    def _getProc(self):
        if self.proc is not None and not self.proc.is_alive():
            self.reset()
        if self.proc is None:
            self.requests = multiprocessing.Queue(maxsize=1)
            self.responses = multiprocessing.Queue(maxsize=1)
            self.proc = multiprocessing.Process(target=worker, args=(self.requests, self.responses, self.headers))
            self.proc.start()
        return self.proc

    def __del__(self):
        """ Destructor """
        self.reset()

    def reset(self):
        if self.proc is None:
            return
        if self.proc.is_alive():
            try:
                self.requests.put(WORK_EXIT)
                self.proc.join(1)  # 1s
                if self.proc.is_alive():
                    self.proc.terminate()
            except:
                pass
        self.requests = None
        self.responses = None
        self.proc = None
        self.cookies = []

    @property
    def reseted(self):
        return self.proc == None

    def open(self, url, params=None):
        self._getProc()
        try:
            self.requests.put((url, params), timeout=TIMEOUT)
            success, resp = self.responses.get(timeout=TIMEOUT)
        except (Queue.Full, Queue.Empty):
            self.reset()
            raise TimeoutException()
        if success:
            self.cookies = resp.cookies
            return resp
        raise resp


def worker(requests, responses, headers):
    # Inicialização
    cookies = cookielib.CookieJar()  # cookies são necessários para a autenticação
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookies), MultipartPostHandler)
    if headers is not None:
        opener.addheaders = headers

    # Request loop
    for req in iter(requests.get, WORK_EXIT):
        try:
            surl, params = req
            resp = Response(opener.open(surl, params, timeout=TIMEOUT), cookies)
            responses.put((True, resp))
        except Exception as e:
            responses.put((False, e))
