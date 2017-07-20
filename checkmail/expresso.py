#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 9-nov-2009

from imapcheckmail import ImapCheckMailService

import threading
from imaplib import IMAP4
import gobject
import gtk
import time

from iexpresso import MailSynchronizer


class ExpressoService(ImapCheckMailService):
    def __init__(self, app, user, passwd):
        ImapCheckMailService.__init__(self, app, user, passwd)
        self.sync = MailSynchronizer()
        self.sync.deleteHandler = self
        self.refreshcount = 0
        # refreshMinutes pode ser alterado pela classe CheckMailService.
        # Só atualiza o iexpresso a cada 3 minutos.
        self.ieRefreshTime = 60 * 3 #segundos
        # time.time() retorna em segundos
        self.lastRefresh = time.time() - self.ieRefreshTime
        self.logged = False

    def doLogin(self):
        self.sync.login(self.user, self.passwd)
        self.logged = True

    def onQuit(self):
        try:
            ImapCheckMailService.onQuit(self)
        finally:
            self.close()

    def close(self):
        self.sync.close()
        self.logged = False

    def askDeleteMessages(self, todelete):
        """ Pergunta ao usuário se devemos continuar com a exclusão das mensagens.
            Só pergunta quando o número de mensagens excluídas fora da lixeira passar de 5. """
        msgcount = 0
        for folder in todelete:
            if folder != 'INBOX/Trash':
                msgcount += len(todelete[folder])

        if msgcount <= 5: # menos que 6 mensagens não pergunta ao usuário
            return True

        msg = _(u"Delete %d messages from Expresso?") % msgcount
        if self.haveNotify:
            if not "actions" in self.notifyCaps:
                return True # se não suportar actions então nem mostra a notificação

            self.delMsgUserResponse = False
            n = self.notify.Notification(_("Delete Messages?"), msg, gtk.STOCK_DIALOG_QUESTION)
            n.set_urgency(self.notify.URGENCY_NORMAL)
            n.set_timeout(self.notify.EXPIRES_NEVER)
            n.add_action("default", _("Abort"), self.onMsgDelClick)
            n.add_action("abort", _("Abort"), self.onMsgDelClick)
            n.add_action("delete", _("Delete"), self.onMsgDelClick)
            if hasattr(n, 'attach_to_status_icon'):
                n.attach_to_status_icon(self.getTrayIcon())
            loop = gobject.MainLoop()
            n.connect('closed', lambda sender: loop.quit())
            if n.show():
                loop.run() #sem o loop não funciona a action da notificação
            return self.delMsgUserResponse
        else:
            return True # não pergunta, gtk.MessageDialog não funciona quando chamada de uma thread

    def onMsgDelClick(self, n, action):
        self.delMsgUserResponse = action == 'delete'
        n.close()

    def processTip(self, subjects, tip):
        tip = ImapCheckMailService.processTip(self, subjects, tip)
        return tip + '\n' + self.sync.getQuotaStr()

    def createImapConnection(self):
        return IMAP4('localhost')

    def runService(self, timered):
        if self == threading.currentThread():
            # deve-se definir o refreshMinutes aqui, para que em caso de erro não fique com o último valor
            self.refreshMinutes = self.defaultRefreshMinutes
            if not self.logged:
                self.doLogin()

            now = time.time()
            if not timered or now - self.lastRefresh >= self.ieRefreshTime:
                if (self.refreshcount % 20) == 0: # a cada 20 iterações faz um full refresh
                    self.sync.loadAllMsgs()
                    self.refreshcount += 1
                else:
                    self.sync.loadUnseen()
                    if timered:
                        self.refreshcount += 1
                self.lastRefresh = time.time()
            # se a data foi alterada para trás reajusta o último refresh
            elif now < self.lastRefresh:
                self.lastRefresh = now - self.ieRefreshTime

            # checks for new mail and notify the user as needed. May redefine refreshMinutes.
            ImapCheckMailService.runService(self, timered)

            # verifica se o próximo refresh deve acontecer antes de passar 'refreshMinutes'
            nextrefresh = self.lastRefresh + self.ieRefreshTime
            if nextrefresh < time.time() + (self.refreshMinutes * 60):
                self.refreshMinutes = max(0, nextrefresh - time.time()) / 60
        else:
            if self.logged:
                self.close()
            self.doLogin()

########################################
# main

if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow
    app = MonApp()
    app.name = 'iExpresso'
    app.desktopFile = 'iexpresso-auto.desktop'
    app.addService(ExpressoService)
    MonLoginWindow(app).run()
    app.run()
