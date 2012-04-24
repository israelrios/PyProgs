#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 03-jan-2012

import os
from imaplib import IMAP4_SSL
import checkmail
import threading
from monutil import decode_header, execute

#################################################################
# ImapCheckMail

class ImapCheckMailService(checkmail.CheckMailService):
    def __init__(self, app, user, passwd):
        checkmail.CheckMailService.__init__(self, app, user, passwd)
        self.iclient = None
        self.defaultRefreshMinutes = 3
        self.readConfig()

    def readConfig(self):
        home = os.getenv('USERPROFILE') or os.getenv('HOME')
        filename = os.path.join(home, ".imapcheckmail.conf")
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


    def showMail(self):
        execute('thunderbird')

    def createImapConnection(self):
        return IMAP4_SSL('corp-bsa-exp-mail.bsa.serpro', 993)

    def closeImap(self):
        if not self.iclient is None:
            try:
                self.iclient.logout()
            finally:
                self.iclient = None

    def onQuit(self):
        checkmail.CheckMailService.onQuit(self)
        self.closeImap()

    def getNewMsgs(self):
        try:
            msgs = self.checkNewMail()
        except:
            # em caso de erro fecha a conexão e tenta novamente
            if not self.iclient is None:
                self.closeImap()
                if self == threading.currentThread():
                    print "ImapCheckMailService: possibly connection failure. Trying again."
                    msgs = self.checkNewMail()
                else:
                    raise # deve estar testando a conexão
            else:
                raise # o imap não foi criado, deve ser outra coisa

        # quando tem email usa um refresh menor
        if len(msgs) > 0:
            self.refreshMinutes = 0.5 # 30 segundos
        else:
            self.refreshMinutes = self.defaultRefreshMinutes

        return msgs

    ###########################################################
    # Verifica se existem novas mensagens de email que se encaixam nos filtros
    def checkNewMail(self):
        try:
            msgs = set()

            if self.iclient is None:
                self.iclient = self.createImapConnection()
                self.iclient.login(self.user, self.passwd)

            self.iclient.select(readonly=True)

            typ, msgnums = self.iclient.search("US-ASCII", self.imapcriteria)

            self.parseError(typ, msgnums)

            if len(msgnums) > 0 and len(msgnums[0].strip()) > 0:
                typ, msgdata = self.iclient.fetch( msgnums[0].replace(' ', ',') ,
                                        '(BODY[HEADER.FIELDS (SUBJECT)])')
                #print msgdata
                self.parseError(typ, msgdata)
                for m in msgdata:
                    if isinstance(m, tuple) and m[0].find('SUBJECT') >= 0:
                        #Extrai o subject e decodifica o texto
                        localid = int(m[0][:m[0].index('(')])
                        msgs.add((localid, decode_header(m[1][len('Subject:'):].strip())))

            self.iclient.close()

            return msgs
        except Exception, e:
            raise Exception(_(u"It was not possible to check your mail box. Error:") + "\n\n" + str(e))

    def parseError(self, typ, msgnums):
        if typ != 'OK':
            if len(msgnums) > 0:
                raise Exception(msgnums[0])
            else:
                raise Exception(_('Bad response.'))
