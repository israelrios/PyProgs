#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2008 Brett Slatkin
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

__author__ = "Brett Slatkin (bslatkin@gmail.com)"

import os
import re
import urlparse
import urllib
import base64
import logging

################################################################################

# URLs that have absolute addresses
ABSOLUTE_URL_REGEX = r"(http(s?):)?//(?P<url>[^\"'> \t\)]+)"

# URLs that are relative to the base of the current hostname.
BASE_RELATIVE_URL_REGEX = r"/(?!(/)|(http(s?)://)|(url\())(?P<url>[^\"'> \t\)]*)"

# URLs that have '../' or './' to start off their paths.
TRAVERSAL_URL_REGEX = r"(?P<relative>\.(\.)?)/(?!(/)|(http(s?)://)|(url\())(?P<url>[^\"'> \t\)]*)"

# URLs that are in the same directory as the requested URL.
SAME_DIR_URL_REGEX = r"(?!(/)|(http(s?)://)|(url\())(?P<url>[^\"'> \t\)]+)"

# URL matches the root directory.
ROOT_DIR_URL_REGEX = r"(?!//(?!>))/(?P<url>)(?=[ \t\n]*[\"'\)>/])"

# Start of a tag using 'src' or 'href'
TAG_START = r"(?i)\b(?P<tag>src|href|action|url|background)(?P<equals>[\t ]*=[\t ]*)(?P<quote>[\"']?)"

# Start of a CSS import
CSS_IMPORT_START = r"(?i)@import(?P<spacing>[\t ]+)(?P<quote>[\"']?)"

# CSS url() call
CSS_URL_START = r"(?i)\burl\((?P<quote>[\"']?)"

UT_URL = 0 #\g<url>
UT_ACCESSED_DIR = 1 # %(accessed_dir)s\g<url>
UT_ACCESSED_DIR_RELATIVE = 2 # %(accessed_dir)s/\g<relative>/\g<url>
UT_BASE = 3 # %(base)s/\g<url>
UT_BASE_ONLY = 4 # %(base)s/

REPLACEMENT_REGEXES = [
  (TAG_START + SAME_DIR_URL_REGEX,
     "\g<tag>\g<equals>\g<quote>%s", UT_ACCESSED_DIR),

  (TAG_START + TRAVERSAL_URL_REGEX,
     "\g<tag>\g<equals>\g<quote>%s", UT_ACCESSED_DIR_RELATIVE),

  (TAG_START + BASE_RELATIVE_URL_REGEX,
     "\g<tag>\g<equals>\g<quote>/%s", UT_BASE),

  (TAG_START + ROOT_DIR_URL_REGEX,
     "\g<tag>\g<equals>\g<quote>/%s", UT_BASE_ONLY),

  # Need this because HTML tags could end with '/>', which confuses the
  # tag-matching regex above, since that's the end-of-match signal.
  (TAG_START + ABSOLUTE_URL_REGEX,
     "\g<tag>\g<equals>\g<quote>/%s", UT_URL),

  (CSS_IMPORT_START + SAME_DIR_URL_REGEX,
     "@import\g<spacing>\g<quote>%s", UT_ACCESSED_DIR),

  (CSS_IMPORT_START + TRAVERSAL_URL_REGEX,
     "@import\g<spacing>\g<quote>%s", UT_ACCESSED_DIR_RELATIVE),

  (CSS_IMPORT_START + BASE_RELATIVE_URL_REGEX,
     "@import\g<spacing>\g<quote>/%s", UT_BASE),

  (CSS_IMPORT_START + ABSOLUTE_URL_REGEX,
     "@import\g<spacing>\g<quote>/%s", UT_URL),

  (CSS_URL_START + SAME_DIR_URL_REGEX,
     "url(\g<quote>%s", UT_ACCESSED_DIR),
  
  (CSS_URL_START + TRAVERSAL_URL_REGEX,
      "url(\g<quote>%s", UT_ACCESSED_DIR_RELATIVE),

  (CSS_URL_START + BASE_RELATIVE_URL_REGEX,
      "url(\g<quote>/%s", UT_BASE),

  (CSS_URL_START + ABSOLUTE_URL_REGEX,
      "url(\g<quote>/%s", UT_URL),
]

################################################################################

B64_PREFIX = "b64."

def encodeUrl(url):
    newurl = []
    for p in url.split('/'):
        if len(p) > 0 and not p.startswith(B64_PREFIX):
            newurl.append(B64_PREFIX + urllib.quote(base64.b64encode(p)))
        else:
            newurl.append(p)
    return '/'.join(newurl)

def decodeUrl(url):
    newurl = []
    iparam = url.find('?')
    params = ""
    if iparam >= 0:
        params = url[iparam:]
        url = url[:iparam]
    for p in url.split('/'):
        try:
            convert = urllib.unquote(p)
            #trata os espaços na url, os espaços são ignorados na regex para urls e isso pode ocasionar na coversão da parte pela metade
            parts = convert.split(' ')
            if len(parts) > 1:
                convert = parts[0]
            #foi necessário fazer um loop para tratar os casos de recodificação
            while convert.startswith(B64_PREFIX):
                convert = base64.b64decode(urllib.unquote(convert[len(B64_PREFIX):]))
                convert = urllib.unquote(convert)
            if len(parts) > 1:
                convert += ' ' + ' '.join(parts[1:])
            newurl.append(urllib.quote(convert))
        except:
            logging.warn('Error converting url from base 64. %s', urllib.unquote(p));
            newurl.append(urllib.unquote(p))
    return '/'.join(newurl) + params

def transformUrl(mo, replacement, urltype, base_url, accessed_dir):
    if urltype == UT_URL: #\g<url>
        url = mo.group('url')
    elif urltype == UT_ACCESSED_DIR: # %(accessed_dir)s\g<url>
        url = "%s%s" % (accessed_dir, mo.group('url'))
    elif urltype == UT_ACCESSED_DIR_RELATIVE: # %(accessed_dir)s/\g<relative>/\g<url>
        url = "%s%s/%s" % (accessed_dir, mo.group('relative'), mo.group('url'))
    elif urltype == UT_BASE: # %(base)s/\g<url>
        url = "%s/%s" % (base_url, mo.group('url'))
    elif urltype == UT_BASE_ONLY: # %(base)s/
        url = "%s/" % base_url
    url = encodeUrl(url)
    #url = urllib.quote(base64.b64encode(url))
    return mo.expand(replacement % url)

def TransformContent(base_url, accessed_url, content):
  url_obj = urlparse.urlparse(accessed_url)
  accessed_dir = os.path.dirname(url_obj.path)
  if not accessed_dir.endswith("/"):
    accessed_dir += "/"

  for pattern, replacement, urltype in REPLACEMENT_REGEXES:
    content = re.sub(pattern, lambda mo: transformUrl(mo, replacement, urltype, base_url, accessed_dir), content)
  return content

#test
if __name__ == "__main__":
    
    text = """
    <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
      "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
    
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        
        <title>8.2. re — Regular expression operations &mdash; Python v2.6.5c1 documentation</title>
        <link rel="stylesheet" href="../_static/default.css" type="text/css" />
        <link rel="stylesheet" href="../_static/pygments.css" type="text/css" />
        <script type="text/javascript">
          var DOCUMENTATION_OPTIONS = {
            URL_ROOT:    '../',
            VERSION:     '2.6.5c1',
            COLLAPSE_MODINDEX: false,
            FILE_SUFFIX: '.html',
            HAS_SOURCE:  true
          };
        </script>
    
        <script type="text/javascript" src="../_static/jquery.js"></script>
        <script type="text/javascript" src="../_static/doctools.js"></script>
        <link rel="search" type="application/opensearchdescription+xml"
              title="Search within Python v2.6.5c1 documentation"
              href="../_static/opensearch.xml"/>
        <link rel="author" title="About these documents" href="../about.html" />
        <link rel="copyright" title="Copyright" href="../copyright.html" />
        <link rel="top" title="Python v2.6.5c1 documentation" href="../index.html" />
        <link rel="up" title="8. String Services" href="strings.html" />
        <link rel="next" title="8.3. struct — Interpret strings as packed binary data" href="struct.html" />
    
        <link rel="prev" title="8.1. string — Common string operations" href="string.html" />
        <link rel="shortcut icon" type="image/png" href="../" />
     
    
      </head>
      
    """
      
    print TransformContent("mydir.com", '', text)
    
    print decodeUrl("b64.cDIudHJyc2YuY29tLmJy/b64.aW1hZ2U%3D/b64.Z2V0P289Y2YmYW1wO3c9ODkmYW1wO2g9NjcmYW1wO3NyYz1odHRwOg%3D%3D//b64.aW1nLnRlcnJhLmNvbS5icg%3D%3D/b64.aQ%3D%3D/b64.MjAxMA%3D%3D/b64.MDM%3D/b64.MDE%3D/b64.MTQ2MTUyOC0yNTgyLWF0bTEwLmpwZw%3D%3D")
