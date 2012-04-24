#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009

import os
from monitors import Service, TrayIcon, curdir
import gobject

#################################################################
# CheckMail

class CheckMailTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showMail();

    def getIconName(self, hasmail):
        if hasmail:
            return 'mail-unread.png'
        else:
            return 'mail-read.png'

    def setIcon(self, hasmail, tip):
        iconname = os.path.join(curdir, self.getIconName(hasmail))
        self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)


class CheckMailService(Service):
    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        self.haveNotify = False
        self.lastMsgs = set()
        self.newMailIcon = 'mail-unread.svg'
        try:
            self.notify = __import__('pynotify')
            if self.notify.init("Monitors"):
                self.haveNotify = True
                self.notifyCaps = self.notify.get_server_caps()
            else:
                print "There was a problem initializing the pynotify module"
        except:
            print "You don't seem to have pynotify installed"

    def showNotify(self, tip):
        if not self.terminated and self.isAlive():
            gobject.idle_add(self.idleShowNotify, tip)

    def idleShowNotify(self, tip):
        iconname = 'file://' + os.path.join(curdir, self.newMailIcon)
        n = self.notify.Notification(_("New Mail"), tip, iconname)
        n.set_urgency(self.notify.URGENCY_NORMAL)
        n.set_timeout(10000) # 10 segundos
        n.attach_to_status_icon(self.getTrayIcon())
        if "actions" in self.notifyCaps:
            loop = gobject.MainLoop ()
            n.connect('closed', lambda sender: loop.quit())
            n.add_action("default", _("Open Mail"), self.onNotifyClick) # isso faz exibir uma dialog box nas novas versões do ubuntu
            n.show()
            loop.run() #sem o loop não funciona a action da notificação
        else:
            n.show()
        return False # pra não rodar novamente no caso de ser chamada por idle_add

    def onNotifyClick(self, n, action):
        self.showMail()
        n.close()

    def createTrayIcon(self):
        return CheckMailTrayIcon(self)

    def showMail(self):
        pass

    def getNewMsgs(self):
        raise Exception('Not implemented.')

    def runService(self, timered):
        msgs = self.getNewMsgs()
        self.setStatus(msgs, timered)

    def processTip(self, msgs, tip):
        return tip # pode ser sobreescrito em classes que derivam desta

    def joinMsgSubjects(self, msgs):
        return '* ' + '\n* '.join([msg[1] for msg in sorted(msgs, reverse=True)])

    def setStatus(self, msgs, timered = False):
        #msgs = set com tuples no formato (id, subject)
        new = msgs - self.lastMsgs
        hasmail = len(msgs) > 0
        if hasmail:
            tip = self.joinMsgSubjects(msgs)
        else:
            tip = _('No new email')
        self.setIcon(hasmail, self.processTip(msgs, tip))
        self.lastMsgs = msgs

        if self.haveNotify:
            if timered and len(new) > 0:
                self.showNotify(self.joinMsgSubjects(new))

    def onQuit(self):
        pass
