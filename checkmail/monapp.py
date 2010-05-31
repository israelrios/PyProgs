#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009
import os

if 'http_proxy' in os.environ:
    del os.environ['http_proxy'] #não utiliza proxy para acessar as páginas
    
import gtk
import ConfigParser
import signal
import syslog
import gobject

import siscop
import expresso
from monitors import *

#####################################################
# LoginWindow
class LoginWindow(gtk.Window):
    def __init__(self, app):
        self.app = app
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)

        self.connect("delete-event", gtk.main_quit)
        self.set_icon_from_file(os.path.join(curdir, 'mail-unread.png'))

        self.conf = Config()

        #self.set_size_request(250, 150)
        self.set_border_width(10)
        self.set_title("Monitors - Login")
        self.set_position(gtk.WIN_POS_CENTER)
        self.set_modal(True)

        # Load the login entry box
        userLabel = gtk.Label("Username: ")
        userLabel.show()

        self.userEntry = gtk.Entry()
        self.userEntry.set_max_length(50)
        self.userEntry.set_text(self.conf.username)
        self.userEntry.connect("activate", self.login)
        self.userEntry.show()

        # Load the pass entry box
        passLabel = gtk.Label("Password: ")
        passLabel.show()

        self.passEntry = gtk.Entry()
        self.passEntry.set_max_length(50)
        self.passEntry.set_text('')
        self.passEntry.connect("activate", self.login)
        self.passEntry.set_visibility(False)
        self.passEntry.show()

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

        table = gtk.Table(6, 2)
        table.set_row_spacings(8)

        table.attach(userLabel, 0, 1, 0, 1, gtk.FILL, 0)
        table.attach(self.userEntry, 1, 2, 0, 1, gtk.EXPAND|gtk.FILL, 0)

        table.attach(passLabel, 0, 1, 1, 2, gtk.FILL, 0)
        table.attach(self.passEntry, 1, 2, 1, 2, gtk.EXPAND|gtk.FILL, 0)

        table.attach(self.cbEmail, 1, 2, 2, 3, gtk.EXPAND|gtk.FILL, 0)
        table.attach(self.cbProxyUsage, 1, 2, 3, 4, gtk.EXPAND|gtk.FILL, 0)
        table.attach(self.cbSisCop, 1, 2, 4, 5, gtk.EXPAND|gtk.FILL, 0)
        table.attach(self.cbExpresso, 1, 2, 5, 6, gtk.EXPAND|gtk.FILL, 0)
        
        table.show()

        # Append login and pass entry box to vbox
        mainbox = gtk.VBox(False, 0)
        mainbox.set_spacing(15)
        mainbox.pack_start(table, True, True, 0)
        self.add(mainbox)

        okButton = gtk.Button(stock=gtk.STOCK_OK)
        okButton.connect("clicked", self.login)
        okButton.set_flags(gtk.CAN_DEFAULT)
        okButton.show()

        cancelButton = gtk.Button(stock=gtk.STOCK_CANCEL)
        cancelButton.connect("clicked", gtk.main_quit)
        cancelButton.show()

        bbox = gtk.HButtonBox()
        bbox.set_layout(gtk.BUTTONBOX_EDGE)
        bbox.pack_start(cancelButton, True, True, 0)
        bbox.pack_end(okButton, True, True, 0)
        bbox.show()

        mainbox.pack_end(bbox, False, True, 0)

        okButton.grab_default()
        # Ajusta o controle inicial
        if self.userEntry.get_text().strip() == '':
            self.userEntry.grab_focus()
        else:
            self.passEntry.grab_focus()

        mainbox.show()

    def run(self):
        self.show()

    def login(self, param):
        user = self.userEntry.get_text()
        passwd = self.passEntry.get_text()
        if len(user.strip()) == 0 or len(passwd.strip()) == 0:
            showMessage(u"Username and password are required.", "Monitors", self)
            return
        checkmail = self.cbEmail.get_active()
        proxyusage = self.cbProxyUsage.get_active()
        siscopservice = self.cbSisCop.get_active()
        expressoservice = self.cbExpresso.get_active()
        if not checkmail and not proxyusage and not siscopservice and not expressoservice:
            showMessage(u"You must select at least one service.", "Monitors", self)
            return
        if self.app.login(user, passwd, checkmail, proxyusage, siscopservice, expressoservice):
            self.conf.username = user
            self.conf.checkmail = checkmail
            self.conf.proxyusage = proxyusage
            self.conf.siscop = siscopservice
            self.conf.expresso = expressoservice
            self.conf.save()
            self.destroy()

#####################################################
# Config
class Config:
    username = ''
    checkmail = True
    proxyusage = True
    siscop = True
    expresso = True
    def __init__(self):
        home = os.getenv('USERPROFILE') or os.getenv('HOME')
        self.filename = os.path.join(home, ".monitors.cfg")
        config = ConfigParser.ConfigParser({'checkmail': '1', 'proxyusage' : '1', 'siscop' : '1', 'expresso' : '1'})
        config.read(self.filename)
        self.username = self.readOption(config, 'login', 'username', '')
        self.checkmail = self.readOption(config, 'services', 'checkmail', True)
        self.proxyusage = self.readOption(config, 'services', 'proxyusage', True)
        self.siscop = self.readOption(config, 'services', 'siscop', True)
        self.expresso = self.readOption(config, 'services', 'expresso', True)

    def readOption(self, config, section, option, default):
        if not config.has_option(section, option):
            return default
        if isinstance(default, bool):
            return config.getboolean(section, option)
        return config.get(section, option)

    def save(self):
        config = ConfigParser.ConfigParser()
        config.add_section('login')
        config.set('login', 'username', self.username)
        config.add_section('services')
        config.set('services', 'checkmail', self.checkmail)
        config.set('services', 'proxyusage', self.proxyusage)
        config.set('services', 'siscop', self.siscop)
        config.set('services', 'expresso', self.expresso)
        configfile = open(self.filename, 'w')
        try:
            config.write(configfile)
        finally:
            configfile.close()


#####################################################
# ServiceRunner
class ServiceRunner:
    service = None
    started = False
    
    def __init__(self, app, serviceClass):
        self.app = app
        self.serviceClass = serviceClass
        
    def check(self, active, user, passwd):
        if self.service != None:
            self.service.quit()
            self.service = None
        if active:
            self.service = self.serviceClass(self, user, passwd)
            return self.service.test()
        else:
            return True
    
    def serviceQuit(self, service):
        if self.started and self.service == service:
            self.started = False
            self.service = None
            app.serviceQuit(service)
    
    def start(self):
        if( self.service != None):
            self.started = True
            self.service.start();
    
    def running(self):
        return (self.service != None)
    
    def quit(self):
        if self.service != None:
            print self.service
            self.service.quit()

    def join(self):
        service = self.service # guarda a instância porque ela pode ser alterada no serviceQuit
        if service != None and service.isAlive():
            service.join(15) # aguarda no máximo 15 segundos


#####################################################################
# App
class App:

    def __init__(self):
        self.cms = ServiceRunner(self, CheckMailService) #checkmail
        self.pus = ServiceRunner(self, ProxyUsageService) #proxyusage
        self.scop = ServiceRunner(self, siscop.SisCopService) #siscop
        self.expresso = ServiceRunner(self, expresso.ExpressoService) #expresso
        self.services = (self.cms, self.pus, self.scop, self.expresso)
        loginWindow = LoginWindow(self)
        loginWindow.run()
        
    #Retorna True se a janela de login puder ser fechada
    def login(self, user, passwd, checkmail, proxyusage, siscopservice, expressoservice):
        
        ret = self.cms.check(checkmail, user, passwd) \
            and self.pus.check(proxyusage, user, passwd) \
            and self.scop.check(siscopservice, user, passwd) \
            and self.expresso.check(expressoservice, user, passwd)
        
        if ret:
            for t in self.services:
                t.start()
        return ret

    def serviceQuit(self, service):
        print "service quit", service
        for t in self.services:
            if t.running():
                return
        gobject.idle_add(gtk.main_quit)

    def quit(self, wait = True):
        running = False
        for t in self.services:
            if t.running():
                running = True
            t.quit()

        if not running:
            try:
                gtk.main_quit()
            except:
                pass # gtk.main_quit pode dar uma exceção se estiver fora do mainloop

        if running and wait:
            for t in self.services:
                t.join()

    def saveyourself(self, *args): #phase, save_style, is_shutdown, interact_style, is_fast):
        """ Chamado pelo gnome antes de fechar a sessão.
            O correto seria só salvar os dados e não fechar o programa. """
        self.quit(True)
        return True

    def die(self, *args):
        self.quit(True)
        return True

    def handlesigterm(self, signum, frame):
        if signum == signal.SIGTERM:
            print 'TERM SIGNAL'
        elif signum == signal.SIGHUP:
            print 'HUP SIGNAL'
        else:
            print 'INT SIGNAL'
        self.quit(False)

    def handleGnomeSession(self):
        """ Define alguns handlers para eventos da sessão Gnome """
        try:
            import gnome
            import gnome.ui
        except:
            pass
        else:
            gnome.program_init('monitors', '2.0')
            self.gclient = gnome.ui.master_client()
            #self.gclient = gnome.ui.Client()
            #self.gclient.connect_to_session_manager()
            self.gclient.connect("save-yourself", self.saveyourself)
            self.gclient.connect("die", self.die)


########################################
# main

def main():
    global app
    gobject.threads_init()
    #gtk.gdk.threads_init() #necessary if gtk.gdk.threads_enter() is called somewhere
    syslog.openlog('monitors')
    app = App()
    signal.signal(signal.SIGINT, app.handlesigterm)
    signal.signal(signal.SIGTERM, app.handlesigterm)
    signal.signal(signal.SIGHUP, app.handlesigterm)
    try:
        app.handleGnomeSession()
        gtk.main()
    finally:
        app.quit(True)

if __name__ == '__main__':
  main()

