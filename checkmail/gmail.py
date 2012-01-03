#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 3-jan-2012

from checkmail import CheckMailService, CheckMailTrayIcon

import urllib2
import xml.dom.minidom
import webbrowser

urlGmailInbox = "https://mail.google.com/mail/#inbox"
urlGmailAtom = "https://mail.google.com/mail/feed/atom"

def getText(nodelist):
    text = []
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            text.append(node.data)
        else:
            text.append(getText(node.childNodes))
    return ''.join(text)

class GmailTrayIcon(CheckMailTrayIcon):
    def getIconName(self, hasmail):
        if hasmail:
            return 'gmail-unread.png'
        else:
            return 'gmail-read.png'

class GmailService(CheckMailService):
    def __init__(self, app, user, passwd):
        CheckMailService.__init__(self, app, user, passwd)
        self.newMailIcon = 'gmail-unread-large.png'
        auth_handler = urllib2.HTTPBasicAuthHandler()
        auth_handler.add_password(realm='New mail feed',
                                  uri=urlGmailAtom,
                                  user=user,
                                  passwd=passwd)
        self.opener = urllib2.build_opener(auth_handler)

    def createTrayIcon(self):
        return GmailTrayIcon(self)

    def showMail(self):
        webbrowser.open(urlGmailInbox)

    def getNewMsgs(self):
        url = self.opener.open(urlGmailAtom)
        dom = xml.dom.minidom.parseString(url.read())
        entrys = dom.getElementsByTagName("entry")
        msgs = set()
        for entry in entrys:
            subject = getText(entry.getElementsByTagName("title"))
            id = getText(entry.getElementsByTagName("id"))
            msgs.add((id, subject))
        return msgs

########################################
# main

if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow

    app = MonApp('gmailchecker')
    app.name = 'Gmail Checker'
    app.iconFile = 'gmail-unread.png'
    app.desktopFile = 'gmail-auto.desktop'
    app.addService(GmailService)
    MonLoginWindow(app).run()
    app.run()
