#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009
import gtk

from monitors import MonApp, MonLoginWindow, MonConfig, showMessage

#####################################################
# MonLoginWindow
class LoginWindow(MonLoginWindow):
    def readConfig(self):
        return Config(self.app)

    def createCustom(self, mainbox):
        self.cbEmail = gtk.CheckButton("_CheckMail")
        self.cbEmail.show()
        self.cbEmail.set_active(self.conf.checkmail)
        self.cbProxyUsage = gtk.CheckButton("_ProxyUsage")
        self.cbProxyUsage.show()
        self.cbProxyUsage.set_active(self.conf.proxyusage)
        self.cbSisCop = gtk.CheckButton("_SisCop")
        self.cbSisCop.show()
        self.cbSisCop.set_active(self.conf.siscop)
        self.cbExpresso = gtk.CheckButton("_Expresso")
        self.cbExpresso.show()
        self.cbExpresso.set_active(self.conf.expresso)

        box = gtk.VBox(True, 5)
        box.pack_start(self.cbEmail, False, True, 0)
        box.pack_start(self.cbProxyUsage, False, True, 0)
        box.pack_start(self.cbSisCop, False, True, 0)
        box.pack_start(self.cbExpresso, False, True, 0)

        box.show()

        mainbox.pack_start(box, False, True, 0)

    def doLogin(self, user, passwd):
        checkmail = self.cbEmail.get_active()
        proxyusage = self.cbProxyUsage.get_active()
        siscopservice = self.cbSisCop.get_active()
        expressoservice = self.cbExpresso.get_active()
        if not checkmail and not proxyusage and not siscopservice and not expressoservice:
            showMessage(u"You must select at least one service.", "Monitors", self)
            return False

        self.app.configServices(checkmail, proxyusage, siscopservice, expressoservice)
        self.conf.checkmail = checkmail
        self.conf.proxyusage = proxyusage
        self.conf.siscop = siscopservice
        self.conf.expresso = expressoservice
        return MonLoginWindow.doLogin(self, user, passwd)


#####################################################
# Config
class Config(MonConfig):
    checkmail = True
    proxyusage = True
    siscop = True
    expresso = True

    def loadValues(self):
        MonConfig.loadValues(self)
        self.checkmail = self.readOption('services', 'checkmail', False)
        self.proxyusage = self.readOption('services', 'proxyusage', False)
        self.siscop = self.readOption('services', 'siscop', True)
        self.expresso = self.readOption('services', 'expresso', True)

    def saveValues(self):
        MonConfig.saveValues(self)
        config = self.config
        if not config.has_section('services'):
            config.add_section('services')
        config.set('services', 'checkmail', self.checkmail)
        config.set('services', 'proxyusage', self.proxyusage)
        config.set('services', 'siscop', self.siscop)
        config.set('services', 'expresso', self.expresso)


#####################################################################
# App
class App(MonApp):

    def __init__(self):
        MonApp.__init__(self)
        loginWindow = LoginWindow(self)
        loginWindow.run()

    #Retorna True se a janela de login pode ser fechada
    def configServices(self, checkmail, proxyusage, siscopservice, expressoservice):

        self.clearServices();

        if checkmail:
            import imapcheckmail
            self.addService(imapcheckmail.ImapCheckMailService) #checkmail
        if proxyusage:
            import proxyusage
            self.addService(proxyusage.ProxyUsageService) #proxyusage
        if siscopservice:
            import siscop
            self.addService(siscop.SisCopService) #siscop
        if expressoservice:
            import expresso
            self.addService(expresso.ExpressoService) #expresso


########################################
# main

if __name__ == '__main__':
    App().run()

