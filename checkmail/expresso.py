# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 9-nov-2009

from monitors import Service, execute, CheckMailService, gtkupdate

import threading
from imaplib import IMAP4
import gobject
import gtk

from iexpresso import MailSynchronizer


class ExpressoService(CheckMailService):
    def __init__(self, app, user, passwd):
        CheckMailService.__init__(self, app, user, passwd)
        self.sync = MailSynchronizer()
        self.sync.deleteHandler = self
        self.refreshcount = 0
        self.logged = False
    
    def doLogin(self):
        self.sync.login(self.user, self.passwd)
        self.logged = True
    
    def onQuit(self):
        CheckMailService.onQuit(self)
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
        
        msg = u"Delete %d messages from Expresso?" % msgcount
        if self.haveNotify:
            if not "actions" in self.notifyCaps:
                return True # se não suportar actions então nem mostra a notificação
            
            self.delMsgUserResponse = False
            n = self.notify.Notification("Delete Messages?", msg, gtk.STOCK_DIALOG_QUESTION)
            n.set_urgency(self.notify.URGENCY_NORMAL)
            n.set_timeout(self.notify.EXPIRES_NEVER)
            n.add_action("default", "Abort", self.onMsgDelClick)
            n.add_action("abort", "Abort", self.onMsgDelClick)
            n.add_action("delete", "Delete", self.onMsgDelClick)
            n.attach_to_status_icon(self.getTrayIcon())
            loop = gobject.MainLoop ()
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
        tip = CheckMailService.processTip(self, subjects, tip)
        return tip + '\n' + self.sync.getQuotaStr()
    
    def createImapConnection(self):
        return IMAP4('localhost')
        
    def runService(self, timered):
        if self == threading.currentThread():
            if not self.logged:
                self.doLogin()
            if (self.refreshcount % 60) == 0: # a cada 60 iterações faz um full refresh
                self.sync.loadAllMsgs()
                self.refreshcount += 1
            else:
                self.sync.loadUnseen()
                if timered:
                    self.refreshcount += 1
        else:
            if self.logged:
                self.close()
            self.doLogin()
        CheckMailService.runService(self, timered)
