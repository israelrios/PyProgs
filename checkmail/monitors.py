#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009
import os
import sys
import gtk
import gobject
import subprocess
import threading
import syslog
import traceback
#checkmail
import email.header
from imaplib import IMAP4, IMAP4_SSL
#proxyusage
import urllib
import urllib2
import cookielib
import time
import locale
from HTMLParser import HTMLParser
import re

#Decorator para métodos que atualização a interface gráfica
def gtkupdate(fn):
    def func(*args):
        return fn(*args)
    try:
        gtk.gdk.threads_enter()
        return func
    finally:
        try:
            gtk.gdk.flush()
        finally:
            gtk.gdk.threads_leave()

def execute(cmd):
    pid = os.fork()
    if pid == 0:
        # To become the session leader of this new session and the process group
        # leader of the new process group, we call os.setsid().
        os.setsid()
        subprocess.Popen(cmd, close_fds=True)
        os._exit(os.EX_OK)
    else:
        os.waitpid(pid, 0)

#Desenha o ícone com uma barra
class IconBar(gtk.gdk.Pixbuf):
    def __init__(self, size, percent,
                 safe=[0,255,0], alert=[255,255,0], danger=[255,0,0], overflow=[255,0,0]):
        gtk.gdk.Pixbuf.__init__(self, gtk.gdk.COLORSPACE_RGB, False, 8, size, size)
        self.safe = safe
        self.alert = alert
        self.danger = danger
        self.overflow = overflow
        self.background = [0,100,0]
        self.border = [0,0,0]
        self._draw(percent)

    def _draw(self, percent):
        size = self.get_width()
        # Define a cor da barra de acordo com a percentagem
        if( percent >= 100 ):
            barcolor = self.overflow
        elif percent >= 80:
            barcolor = self.danger
        elif percent >= 50:
            barcolor = self.alert
        else:
            barcolor = self.safe

        totalheight = size-2 # tirando as bordas
        
        barheight = round(percent * totalheight / 100.0) # altura da barra
        if percent > 0 and barheight < 1: #vazio somente quando percent = zero
            barheight = 1

        # A imagem é desenhada de cabeça para baixo
        barstart = totalheight - barheight + 1 # conta com a borda
        s = self.get_pixels_array()
        s[0,:] = self.border # linha de cima
        for i in range(1, size-1): #desenha as linhas da barra
            if i >= barstart:
                color = barcolor
            else:
                color = self.background
            s[i,0] = self.border
            s[i,1:size-1] = color
            s[i,size-1] = self.border

        s[size-1, :] = self.border # linha de baixo

    def update(self, percent):
        self._draw(percent)

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

    @gtkupdate
    def setError(self, error):
        self.set_from_stock('gtk-dialog-error')
        self.set_tooltip(error)
        self.set_visible(True)

    def destroy(self):
        self.set_visible(False)

    @gtkupdate
    def set_visible(self, visible):
        if self.service.isAlive():
            gtk.StatusIcon.set_visible(self, visible)

class ProxyUsageTrayIcon(TrayIcon):
    def __init__(self, service):
        TrayIcon.__init__(self, service)
        self.connect('size-changed', self.onSizeChanged)
        self.percent = 0
        self.icon = IconBar(22, self.percent)

    def onSizeChanged(self, object, size):
        self.icon = IconBar(size, self.percent)
        if self.get_visible():
            self.set_from_pixbuf(self.icon)

    @gtkupdate
    def setIcon(self, percent, tip):
        self.percent = percent
        self.icon.update(percent)
        self.set_from_pixbuf(self.icon)
        self.set_tooltip(tip)
        self.set_visible(True)

class CheckMailTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showMail();

    @gtkupdate
    def setIcon(self, hasmail, tip):
        if hasmail:
            iconname = 'mail-unread.png'
        else:
            iconname = 'mail-read.png'
        iconname = os.path.join(curdir, iconname)
        self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)

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

    def run(self):
        try:
            if not self.terminated:
                self.getTrayIcon().set_visible(True)
                self._refresh(False)
            while not self.terminated:
                self.goEvent.wait(self.refreshMinutes * 60) #em segundos
                if self.terminated:
                    break
                self._refresh(not self.goEvent.isSet())
                self.goEvent.clear()
        finally:
            if self._trayicon != None:
                self._trayicon.destroy()
                self._trayicon = None
            self.onQuit();

            self.app.serviceQuit(self)

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
                self.getTrayIcon().setError(str(e))
                return True # se retornar False o timer para
            mustLock = self == threading.currentThread()
            try:
                if mustLock: gtk.gdk.threads_enter()
                showMessage(str(e), "Error", type=gtk.MESSAGE_ERROR)
                if mustLock: gtk.gdk.flush()
            finally:
                if mustLock: gtk.gdk.threads_leave()
            return False
        return True

    def getTrayIcon(self):
        if self._trayicon == None:
            self._trayicon = self.createTrayIcon()
        return self._trayicon

    def quit(self):
        self.terminated = True
        if not self.isAlive():
            print "starting thread", self
            self.start()
        self.goEvent.set()

#################################################################
# CheckMail

class CheckMailService(Service):
    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        self.haveNotify = False
        self.lastMsg = None
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
        iconname = 'file://' + os.path.join(curdir, 'mail-unread.png')
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
        self.setStatus(self.checkNewMail(), timered)
        
    def processTip(self, subjects, tip):
        return tip # pode ser sobreescrito em classes que derivam desta

    def setStatus(self, subjects, timered = False):
        hasmail = len(subjects) > 0
        if hasmail:
            tip = '* ' + '\n* '.join(subjects)
        else:
            tip = 'No new email'
        self.getTrayIcon().setIcon(hasmail, self.processTip(subjects, tip))
        
        if self.haveNotify:
            if timered and hasmail and self.lastMsg != tip:
                #gobject.idle_add(self.showNotify, tip)
                self.showNotify(tip)
            self.lastMsg = tip
    
    def createImapConnection(self):
        return IMAP4_SSL('corp-bsa-exp-mail.bsa.serpro', 993)

    ###########################################################
    # Verifica se existem novas mensagens de email que se encaixam nos filtros
    def checkNewMail(self):
        try:
            subjects = []
            imap = self.createImapConnection()

            imap.login(self.user, self.passwd)
            try:
                imap.select(readonly=True)
                
                typ, msgnums = imap.search("US-ASCII", self.imapcriteria)
            
                self.parseError(typ, msgnums)
                
                if len(msgnums) > 0 and len(msgnums[0].strip()) > 0:
                    typ, msgs = imap.fetch( msgnums[0].replace(' ', ',') , 
                                            '(BODY[HEADER.FIELDS (SUBJECT)])')
                    #print msgs
                    self.parseError(typ, msgs)
                    for m in msgs:
                        if isinstance(m, tuple) and m[0].find('SUBJECT') >= 0:
                            #Extraí o subject e decodifica o texto
                            dec = email.header.decode_header(m[1].strip('Subject:').strip())
                            subject = ''
                            for item in dec:
                                if item[1] != None:
                                    subject += item[0].decode(item[1]) + ' '
                                else:
                                    subject += item[0] + ' '
                            subjects.append(subject)
            finally:
                imap.close()
                imap.logout()

            return subjects
        except Exception, e:
            raise Exception(u"It was not possible to check your mail box. Error:\n\n" + str(e))

    def parseError(self, typ, msgnums):
        if typ != 'OK':
            if len(msgnums) > 0:
                raise Exception(msgnums[0])
            else:
                raise Exception('Bad response.')


#####################################################################
#ProxyUsage    

#Classe para extrair o texto do HTML
class HtmlTextParser(HTMLParser):

    def __init__(self):
        self.texto = ""
        HTMLParser.__init__(self)

    def handle_starttag(self, tag, attrs):
        pass

    def handle_data(self, data):
        self.texto = self.texto + data

    def handle_endtag(self, tag):
        pass


class ProxyUsageService(Service):
    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        # Os campos do formulário
        self.fields = {}
        self.fields['uid'] = user
        self.fields['pwd'] = passwd
        #Inicialização
        cookies = cookielib.CookieJar() #cookies são necessários para a autenticação
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookies))
        # Expressão regular para extrair os dados do consumo
        self.pattern = re.compile(r"\|\s*(\d{2}\/\d{2}\/\d{4}\s+\d{2}\:\d{2}\:\d{2})" +
                                  r"\s*(\d+(?:\,\d+)?)\s*([KMG])Bytes\s*=\s*(\d+(?:\.\d+)?)\%",
                                  re.MULTILINE | re.IGNORECASE)
    
    def createTrayIcon(self):
        return ProxyUsageTrayIcon(self)

    def runService(self, timered):
        pu = self.getProxyUsage()
        #O site do consumo não segue um padrão para formatação de números com ponto flutuante
        #Os números são ajustados para o padrão americano, convertidos para float e
        # depois convertidos para string utilizando a configuração do usuário
        bytes = float(pu[1].replace(',', 'x').replace('.', ',').replace('x', '.'))
        percent = float(pu[3])
        texto = u"Proxy usage: %s%sB (%s%%)  %s" % \
            (locale.str(bytes), pu[2], locale.str(percent), pu[0])
        self.getTrayIcon().setIcon(percent, texto)

    ###########################################################
    # Extrai o texto do HTML e separa a informação do consumo
    # Formato:
    #   23/01/2009 15:16:01
    #   40,1965 MBytes = 66.99%
    def getProxyUsage(self):
        try:
            url = self.opener.open("https://www.cooseg.celepar.parana/consumo/entrar.php", urllib.urlencode(self.fields, True))
        except Exception, e:
            raise Exception(u"It was not possible to check your proxy usage. Error:\n\n" + str(e))

        parser = HtmlTextParser()
        for line in url.readlines():
            parser.feed(line)
        parser.close()

        mo = self.pattern.search(parser.texto)
        if mo != None:
            return mo.groups()
        else:
            #O parser não suporta HTML entitys (Ex: &aacute)
            if parser.texto.find('No h registro para seu usurio at o momento') >= 0 :
                return [time.strftime("%d/%m/%Y %H:%M:%S", time.localtime()), '0', 'K', '0']
            raise Exception(u"It was not possible to check your proxy usage.\n" +
                            u"Make sure the entered username and password are correct.")


########################################
# main

curdir = os.path.abspath( os.path.dirname(sys.argv[0]) )


