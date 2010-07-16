#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009

import os
from monitors import Service, TrayIcon, curdir
from imaplib import IMAP4, IMAP4_SSL
import gobject
import threading
from monutil import decode_header, execute

#################################################################
# CheckMail

class CheckMailTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showMail();

    def setIcon(self, hasmail, tip):
        if hasmail:
            iconname = 'mail-unread.png'
        else:
            iconname = 'mail-read.png'
        iconname = os.path.join(curdir, iconname)
        self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)
  

class CheckMailService(Service):
    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        self.haveNotify = False
        self.lastMsg = None
        self.iclient = None
        try:
            self.notify = __import__('pynotify') 
            if self.notify.init("Monitors"):
                self.haveNotify = True
                self.notifyCaps = self.notify.get_server_caps()
            else:
                print "There was a problem initializing the pynotify module"
        except:
            print "You don't seem to have pynotify installed"
        self.readConfig()
    
    def readConfig(self):
        home = os.getenv('USERPROFILE') or os.getenv('HOME')
        filename = os.path.join(home, ".checkmail.conf")
        self.imapcriteria = "(UNSEEN)"
        if os.path.exists(filename):
            f = open(filename, 'r')
            lines = []
            try:
                for line in f:
                    line = line.strip()
                    if not line.startswith('#'):
                        lines.append(line)
            finally:
                f.close()
            self.imapcriteria = '(' + ' '.join(lines) + ')' # tem que estar entre parenteses pro imap lib não colocar entre aspas
    
    def showNotify(self, tip):
        if not self.terminated and self.isAlive():
            gobject.idle_add(self.idleShowNotify, tip)
    
    def idleShowNotify(self, tip):
        iconname = 'file://' + os.path.join(curdir, 'mail-unread.svg')
        n = self.notify.Notification("New Mail", tip, iconname)
        n.set_urgency(self.notify.URGENCY_NORMAL)
        n.set_timeout(10000) # 10 segundos
        n.attach_to_status_icon(self.getTrayIcon())
        if "actions" in self.notifyCaps:
          loop = gobject.MainLoop ()
          n.connect('closed', lambda sender: loop.quit())
          n.add_action("default", "Open Mail", self.onNotifyClick) # isso faz exibir uma dialog box nas novas versões do ubuntu
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
        #if emailreader == None or emailreader.poll() != None:
        #    self.emailreader = \
        #subprocess.Popen('thunderbird', close_fds=True)
        execute('thunderbird')
        #remove o status "new mail"
        self.setStatus([], False)
        #agenda a execução do próximo refresh para 30seg
        #t = threading.Timer(30, lambda: self.refresh())
        #t.setDaemon(True)
        #t.start()

    def runService(self, timered):
        try:
            subjects = self.checkNewMail()
        except:
            # em caso de erro fecha a conexão e tenta novamente 
            if not self.iclient is None:
                self.closeImap()
                if self == threading.currentThread():
                    print "CheckMailService: possibly connection failure. Trying again."
                    subjects = self.checkNewMail()
                else:
                    raise # deve estar testando a conexão
            else:
                raise # o imap não foi criado, deve ser outra coisa
        
        self.setStatus(subjects, timered)
        
    def processTip(self, subjects, tip):
        return tip # pode ser sobreescrito em classes que derivam desta

    def setStatus(self, subjects, timered = False):
        hasmail = len(subjects) > 0
        if hasmail:
            tip = '* ' + '\n* '.join(subjects)
        else:
            tip = 'No new email'
        self.setIcon(hasmail, self.processTip(subjects, tip))
        
        if self.haveNotify:
            if timered and hasmail and self.lastMsg != tip:
                self.showNotify(tip)
            self.lastMsg = tip
    
    def createImapConnection(self):
        return IMAP4_SSL('corp-bsa-exp-mail.bsa.serpro', 993)
    
    def closeImap(self):
        if not self.iclient is None:
            try:
                self.iclient.logout()
            finally:
                self.iclient = None

    def onQuit(self):
        self.closeImap()

    ###########################################################
    # Verifica se existem novas mensagens de email que se encaixam nos filtros
    def checkNewMail(self):
        try:
            subjects = []
            
            if self.iclient is None:
                self.iclient = self.createImapConnection()
                self.iclient.login(self.user, self.passwd)
            
            self.iclient.select(readonly=True)
            
            typ, msgnums = self.iclient.search("US-ASCII", self.imapcriteria)
        
            self.parseError(typ, msgnums)
            
            if len(msgnums) > 0 and len(msgnums[0].strip()) > 0:
                typ, msgs = self.iclient.fetch( msgnums[0].replace(' ', ',') , 
                                        '(BODY[HEADER.FIELDS (SUBJECT)])')
                #print msgs
                self.parseError(typ, msgs)
                for m in msgs:
                    if isinstance(m, tuple) and m[0].find('SUBJECT') >= 0:
                        #Extrai o subject e decodifica o texto
                        subjects.append(decode_header(m[1].strip('Subject:').strip()))
            
            self.iclient.close()

            return subjects
        except Exception, e:
            raise Exception(u"It was not possible to check your mail box. Error:\n\n" + str(e))

    def parseError(self, typ, msgnums):
        if typ != 'OK':
            if len(msgnums) > 0:
                raise Exception(msgnums[0])
            else:
                raise Exception('Bad response.')
