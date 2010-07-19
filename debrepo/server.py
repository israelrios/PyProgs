#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2010 Israel Rios
__author__ = "Israel Rios (isrrios@gmail.com)"

import wsgiref.handlers
from google.appengine.ext import webapp
import os.path


mime_map = {
            '.deb':'application/x-debian-package',
            '.gz':'application/x-gzip'
            }

class DebHandler(webapp.RequestHandler):
  def get(self, filename):
    
    fpath = os.path.join('deb', filename)
    if not os.path.exists(fpath):
      return self.error(404)
    
    f = open(fpath, 'rb')
    try:
      fileext = os.path.splitext(filename)[1]
      if fileext in mime_map:
        self.response.headers['Content-Type'] = mime_map[fileext]
      else:
        self.response.headers['Content-Type'] = "application/octet-stream"
      self.response.out.write(f.read())
    finally:
      f.close()

app = webapp.WSGIApplication([
  (r"/(.*)", DebHandler)
], debug=False)


def main():
  wsgiref.handlers.CGIHandler().run(app)


if __name__ == "__main__":
  main()