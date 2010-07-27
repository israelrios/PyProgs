#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2010 Israel Rios
__author__ = "Israel Rios (isrrios@gmail.com)"

import wsgiref.handlers
from google.appengine.ext import webapp
import os.path
from google.appengine.ext.webapp import template

mime_map = {
            '.deb':'application/x-debian-package',
            '.gz':'application/x-gzip'
            }

def getLangPref(request):
  langs = []
  if not 'Accept-Language' in request.headers:
    return langs
  header = request.headers['Accept-Language']
  if len(header) == 0:
    return langs
  
  map = {}
  for langinfo in header.split(','):
    parts = langinfo.split(';')
    lang = parts[0].strip()
    langs.append(lang)
    if len(parts) == 1:
      map[lang] = 1
    else:
      map[lang] = float(parts[1].strip().strip('q='))
  langs.sort(lambda a, b: int((map[b] - map[a]) * 1000))
  return langs

class MainHandler(webapp.RequestHandler):
  def get(self):
    langs = getLangPref(self.request)
    lang = 'en'
    for l in langs:
      if l.startswith('pt'):
        lang = 'pt'
        break
      if l.startswith('en'):
        lang = 'en'
        break
    if lang == 'pt':
      text = template.render("body_pt.html", {})
    else:
      text = template.render("body_en.html", {})
    self.response.out.write(template.render("main.html", {'text': text}))

class DebHandler(webapp.RequestHandler):
  def get(self, filename):
    
    fpath = os.path.join('deb', filename)
    if not os.path.isfile(fpath):
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
  (r"/(.+)", DebHandler),
  (r"/", MainHandler)
], debug=False)


def main():
  wsgiref.handlers.CGIHandler().run(app)


if __name__ == "__main__":
  main()