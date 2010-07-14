#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009
import os
import sys
import gtk
import ConfigParser
import gobject
import threading
import syslog
import traceback
import signal

if 'http_proxy' in os.environ:
    del os.environ['http_proxy'] #não utiliza proxy para acessar as páginas
    
curdir = os.path.abspath( os.path.dirname(sys.argv[0]) )

class TrayIcon(gtk.StatusIcon):
    def __init__(self, service):
        self.service = service
        gtk.StatusIcon.__init__(self)
        self.connect('activate', self.onActivate)
        self.connect('popup-menu', self.onPopupMenu)

    def onMenuExit(self, event):
        self.service.quit()

    def onMenuRefresh(self, event):
        self.service.refresh()

    def onActivate(self, event):
        pass

    def createMenuItem(self, stock_id, handler):
        mi = gtk.ImageMenuItem(stock_id)
        mi.connect('activate', handler)
        return mi

    def onPopupMenu(self, status_icon, button, activate_time):
        menu = gtk.Menu()
        menu.append(self.createMenuItem(gtk.STOCK_QUIT, self.onMenuExit))
        menu.append(self.createMenuItem(gtk.STOCK_REFRESH, self.onMenuRefresh))
        menu.show_all()
        menu.popup(None, None, None, button, activate_time)

    def setError(self, error):
        self.set_from_stock('gtk-dialog-error')
        self.set_tooltip(error)
        self.set_visible(True)
    
    def setInitialIcon(self):
        self.set_from_stock('gtk-execute')
        self.set_tooltip("Loading - " + self.service.name)
        self.set_visible(True)

    def destroy(self):
        self.set_visible(False)


def showMessage(text, caption, parentWindow = None, type = gtk.MESSAGE_INFO):
    dlg = gtk.MessageDialog(parentWindow, gtk.DIALOG_MODAL, type, gtk.BUTTONS_OK, text)
    #dlg.set_markup(text)
    dlg.set_title(caption)
    dlg.run()
    dlg.destroy()
    return


########################################################
# Service
class Service(threading.Thread):
    _trayicon = None
    refreshMinutes = 3
    terminated = False

    def __init__(self, app, user, passwd):
        threading.Thread.__init__(self)
        self.app = app
        self.user = user
        self.passwd = passwd
        self.goEvent = threading.Event()
        self.setDaemon(True) # se a thread principal terminar esta thread será finalizada
        self.name = self.__class__.__name__
    
    def setInitialIcon(self):
        if not self.terminated and self.isAlive():
            gobject.idle_add(lambda: self.getTrayIcon().setInitialIcon())
        
    def setIconError(self, error):
        if not self.terminated and self.isAlive():
            gobject.idle_add(lambda: self.getTrayIcon().setError(error))
        
    def setIcon(self, *args):
        if not self.terminated and self.isAlive():
            gobject.idle_add(lambda: self.getTrayIcon().setIcon(*args))

    def run(self):
        try:
            if not self.terminated:
                self.setInitialIcon()
                self._refresh(False)
            while not self.terminated:
                self.goEvent.wait(self.refreshMinutes * 60) #em segundos
                if self.terminated:
                    break
                self._refresh(not self.goEvent.isSet())
                self.goEvent.clear()
        finally:
            gobject.idle_add(self.destroyTrayIcon)
            self.onQuit();

            self.app.serviceQuit(self)
    
    def destroyTrayIcon(self):
        if self._trayicon != None:
            self._trayicon.destroy()
            self._trayicon = None
            
    def onQuit(self):
        pass

    def refresh(self):
        self.goEvent.set()

    def test(self):
        return self._refresh(False)

    def _refresh(self, timered):
        try:
            self.runService(timered)
            return True
        except Exception, e:
            syslog.syslog(syslog.LOG_USER | syslog.LOG_ERR, traceback.format_exc(8))
            if timered :
                self.setIconError(str(e))
                return True # se retornar False o timer para
            errortext = str(e)
            gobject.idle_add(lambda: showMessage(errortext, "Error", type=gtk.MESSAGE_ERROR))
            return False
        return True

    def getTrayIcon(self):
        """ Must be called from main thread. Use gobject.idle_add """
        if self._trayicon == None:
            if not self.isAlive():
                raise Exception("Canno't create tray icon: " + self.name + " is not running.")
            self._trayicon = self.createTrayIcon()
        return self._trayicon

    def quit(self):
        self.terminated = True
        if not self.isAlive():
            print "starting thread", self
            self.start()
        self.goEvent.set()


#####################################################
# MonLoginWindow
class MonLoginWindow(gtk.Window):
    def readConfig(self):
        return MonConfig()
    
    def createUserPass(self):
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

        table = gtk.Table(2, 2)
        table.set_row_spacings(8)
        
        table.attach(userLabel, 0, 1, 0, 1, gtk.FILL, 0)
        table.attach(self.userEntry, 1, 2, 0, 1, gtk.EXPAND|gtk.FILL, 0)

        table.attach(passLabel, 0, 1, 1, 2, gtk.FILL, 0)
        table.attach(self.passEntry, 1, 2, 1, 2, gtk.EXPAND|gtk.FILL, 0)
        
        table.show()
        
        return table
    
    def createButtons(self):
        self.okButton = gtk.Button(stock=gtk.STOCK_OK)
        self.okButton.connect("clicked", self.login)
        self.okButton.set_flags(gtk.CAN_DEFAULT)
        self.okButton.show()

        cancelButton = gtk.Button(stock=gtk.STOCK_CANCEL)
        cancelButton.connect("clicked", gtk.main_quit)
        cancelButton.show()

        bbox = gtk.HButtonBox()
        bbox.set_layout(gtk.BUTTONBOX_EDGE)
        bbox.pack_start(cancelButton, True, True, 0)
        bbox.pack_end(self.okButton, True, True, 0)
        bbox.show()
        
        return bbox;
    
    def createCustom(self, mainbox):
        pass
    
    def createControls(self):
        # Append login and pass entry box to vbox
        mainbox = gtk.VBox(False, 0)
        mainbox.set_spacing(15)
        mainbox.pack_start(self.createUserPass(), True, True, 0)
        self.createCustom(mainbox)
        mainbox.pack_end(self.createButtons(), False, True, 0)
        mainbox.show()
        return mainbox
      
    def __init__(self, app):
        self.app = app
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)

        self.connect("delete-event", gtk.main_quit)
        self.set_icon_from_file(os.path.join(curdir, 'mail-unread.png'))

        self.conf = self.readConfig()

        #self.set_size_request(250, 150)
        self.set_border_width(10)
        self.set_title("Monitors - Login")
        self.set_position(gtk.WIN_POS_CENTER)
        self.set_modal(True)
        
        self.add(self.createControls())
        
        self.okButton.grab_default()

        # Ajusta o controle inicial
        if self.userEntry.get_text().strip() == '':
            self.userEntry.grab_focus()
        else:
            self.passEntry.grab_focus()

    def run(self):
        self.show()

    def login(self, param):
        user = self.userEntry.get_text()
        passwd = self.passEntry.get_text()
        if len(user.strip()) == 0 or len(passwd.strip()) == 0:
            showMessage(u"Username and password are required.", "Monitors", self)
            return
        if self.doLogin(user, passwd):
            self.conf.username = user
            self.conf.save()
            self.destroy()

#####################################################
# MonConfig
class MonConfig:
    username = ''
    def __init__(self):
        home = os.getenv('USERPROFILE') or os.getenv('HOME')
        self.filename = os.path.join(home, ".monitors.cfg")
        self.config = ConfigParser.ConfigParser()
        self.config.read(self.filename)
        self.username = self.readOption('login', 'username', '')
        self.loadValues()
    
    def loadValues(self):
        pass
    
    def saveValues(self):
        pass

    def readOption(self, section, option, default):
        if not self.config.has_option(section, option):
            return default
        if isinstance(default, bool):
            return self.config.getboolean(section, option)
        return self.config.get(section, option)

    def save(self):
        config = self.config
        
        if not config.has_section('login'):
            config.add_section('login')
        config.set('login', 'username', self.username)
        
        self.saveValues()
        
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
            self.app.serviceQuit(service)
    
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
# MonApp

class MonApp:

    def __init__(self):
        self.services = []
        syslog.openlog('monitors')
        gobject.threads_init()
        #gtk.gdk.threads_init() #necessary if gtk.gdk.threads_enter() is called somewhere
    
    def addService(self, serviceClass):
        self.services.append(ServiceRunner(self, serviceClass))
    
    def clearServices(self):
        for s in self.services:
            s.quit()
        self.services = []
        
    #Retorna True se a janela de login puder ser fechada
    def startServices(self, user, passwd):        
        ok = True
        for service in self.services:
          ok = ok and service.check(True, user, passwd)
        
        if ok:
            for t in self.services:
                t.start()
        return ok

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
    
    def run(self):
        signal.signal(signal.SIGINT, self.handlesigterm)
        signal.signal(signal.SIGTERM, self.handlesigterm)
        signal.signal(signal.SIGHUP, self.handlesigterm)
        try:
            self.handleGnomeSession()
            gtk.main()
        finally:
            self.quit(True)

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


