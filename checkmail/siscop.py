# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 15-abr-2009

from monitors import Service, TrayIcon, curdir, showMessage
from monutil import HtmlTextParser, execute, decode_htmlentities

import os
import urllib
import urllib2
import cookielib
import datetime
import dbus
import commands
import threading
import gtk
import re
import tempfile
import gobject

SEC_HOUR = 60*60 # 1 hora em segundos

SEC_MAX_PERIOD = SEC_HOUR * 5 # 5hs
SEC_ALERT_PERIOD = SEC_MAX_PERIOD - (60 * 2) #4hs e 58mins

NOT_LOGGED = 3
PONTO_OK = 1
PONTO_NOK = 2

class SisCopTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showPage()

    def prepareMenu(self, menu):
        TrayIcon.prepareMenu(self, menu)
        menu.append(self.createMenuItem(gtk.STOCK_CONNECT, self.onMenuConnect))

    def onMenuConnect(self, event):
        self.service.decodeCaptcha()

    def setIcon(self, status):
        iconname = None
        if status == PONTO_OK:
            iconname = 'siscop_idle.png'
            tip = u'Ponto OK'
        elif status == PONTO_NOK:
            iconname = 'siscop_waiting.png'
            tip = u'Aguarde para registrar o ponto ' + \
                self.service.timeReturn.strftime('(%H:%M)')
        else:
            self.set_from_stock('gtk-dialog-warning')
            tip = u'Faça o login.'
        if iconname != None:
            iconname = os.path.join(curdir, iconname)
            self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)


class NotLoggedException(Exception):
    def __init__(self):
        Exception.__init__(self, u"Login required.")


class SisCopService(Service):
    urlSisCop = 'http://siscop.portalcorporativo.serpro'
    urlLogin = urlSisCop + '/cpf_senha.asp'
    urlCadRegPonto = urlSisCop + '/CadRegPonto.asp'

    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        # Os campos do formulário
        self.fields = {}
        self.fields['tx_cpf'] = user
        self.fields['tx_senha'] = passwd
        #Inicialização
        self.opener, self.cookiejar = self.buildOpener()
        self.tempOpener = None
        self.tempCookiejar = None
        #Atualiza a cada 5min
        self.refreshMinutes = 5
        self.lastPageId = None
        self.logged = False
        self.captchaValue = None
        self.decodingCaptcha = False

    def buildOpener(self):
        cookiejar = cookielib.CookieJar() #cookies são necessários para a autenticação
        return (urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar)), cookiejar)

    def createTrayIcon(self):
        return SisCopTrayIcon(self)

    def runService(self, timered=True):
        # o valor de refreshMinutes pode ser alterado em self.check()
        status = self.check()
        if status == NOT_LOGGED and not timered:
            gobject.idle_add(self.decodeCaptcha)
        self.setIcon(status)

    def showPage(self, pageId=None):
        if pageId != None and self != threading.currentThread():
            return
        """ Mostra a página do SisCop se o pageId for diferente do último. """
        if pageId == None or pageId != self.lastPageId:
            if pageId != None:
                self.lastPageId = pageId
            #abre o browser com a página
            procs = commands.getoutput('/bin/ps xo comm').split('\n')
            if 'chrome' in procs:
                if self.logged:
                    # passa os cookies para o browser para evitar a tela de login
                    url = self.urlCadRegPonto + "?"
                    cookies = []
                    for cookie in self.cookiejar:
                        cookies.append("%s=%s" % (cookie.name, cookie.value))
                    url = url + urllib.urlencode({'cookie': '; '.join(cookies)})
                else:
                    url = self.urlLogin
                execute(["google-chrome", url])
                execute(["wmctrl", "-a", "Chrome"])
            else:
                execute(["firefox", self.urlLogin])
                execute(["wmctrl", "-a", "Firefox"])

        #verifica se o usuário está na máquina
        if pageId != None:
            bus = dbus.SessionBus()
            ssaver = bus.get_object('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver')
            try:
                # costuma demorar alguns segundos pra retornar
                ssaver.SimulateUserActivity() # faz aparecer a tela de login caso o screensaver esteja ativado
            except:
                pass # costuma lançar um erro DBusException: org.freedesktop.DBus.Error.NoReply

    def decodeCaptcha(self):
        if self.decodingCaptcha:
            return
        self.tempOpener, self.tempCookiejar = self.buildOpener()
        html = self.tempOpener.open(self.urlLogin).read()
        # get the viewstate value
        mo = re.search(r"<input[^>]+id\s*=\s*['\"]?viewstate['\"]?[^>]+value\s*=\s*'([^']+)'", html, re.DOTALL)
        self.fields['viewstate'] = decode_htmlentities(mo.group(1))
        # get the captcha image url
        mo = re.search(r"src\s*=\s*'(/captcha/[^']+)'", html, re.DOTALL)
        fname = os.path.join(tempfile.gettempdir(), "siscop.captcha.jpg")
        with open(fname, 'w') as f:
            f.write(self.tempOpener.open(self.urlSisCop + decode_htmlentities(mo.group(1))).read())
        self.decodingCaptcha = True
        wnd = CaptchaWindow(self, fname)
        wnd.connect("destroy", self.captchaWindowClosed)
        wnd.run()

    def captchaWindowClosed(self, wnd):
        self.decodingCaptcha = False

    def checkLogged(self, url):
        self.logged = not url.geturl().startswith(self.urlLogin)
        return self.logged

    def login(self):
        if self.logged:
            return True
        if self.captchaValue == None:
            return False
        self.opener = self.tempOpener
        self.cookiejar = self.tempCookiejar
        self.fields['captcha'] = self.captchaValue
        self.captchaValue = None
        self.tempOpener = None
        self.tempCookiejar = None
        url = self.opener.open(self.urlLogin, urllib.urlencode(self.fields))
        return self.checkLogged(url)

    def getPageText(self):
        """ Faz o login no SISCOP. Download da página de registro de ponto. Extrai o texto do HTML da página. """
        try:
            url = self.opener.open(self.urlCadRegPonto)
        except Exception, e:
            raise Exception(u"It was not possible to connect at SisCop. Error:\n\n" + str(e))

        self.checkLogged(url)
        if not self.logged:
            raise NotLoggedException()

        #Extraí as linhas de interese e remove as tags HTML
        start = end = -1
        parser = HtmlTextParser()
        for line in url.readlines():
            line = line.decode('cp1252')
            if start < 0:
                #ascentos não estão funcionando, dá problema de codificação
                start = line.find(u'Período Normal') # Período Normal
            if start >= 0:
                if end < 0:
                    end = line.find(u'Período Extra') # Período Extra
                    parser.feed(line)

        parser.close()
        if start < 0 or end < 0:
            raise Exception(u'SisCop - The page layout is unknown')
        return parser.texto

    def checkPeriod(self, dtEntr, dtExit):
        """ Verifica se já se passou mais de 5 horas da entrada do período. """
        if dtEntr == None or dtExit != None:
            return True
        diff = datetime.datetime.today() - dtEntr
        if diff.seconds < SEC_ALERT_PERIOD: # menor que 5 horas
            secDiff = SEC_ALERT_PERIOD - diff.seconds + 5 # mais 5 segundos pra garantir que vai entrar no else
            self.refreshMinutes = min(self.refreshMinutes, float(secDiff)/60.0)
        elif diff.seconds < SEC_MAX_PERIOD:
            self.showPage(dtEntr)
        else:
            return True
        return False

    def checkReturn(self, exit1, entr2):
        """ Verifica se o retorno do almoço foi registrado. """
        if exit1 == None or entr2 != None:
            return True
        diff = datetime.datetime.today() - exit1
        self.timeReturn = exit1 + datetime.timedelta(seconds=SEC_HOUR)
        if diff.seconds < SEC_HOUR: # menor que uma hora
            secDiff = SEC_HOUR - diff.seconds + 1 # 1 segundo a mais
            self.refreshMinutes = min(self.refreshMinutes, float(secDiff)/60.0)
        else: # Maior que 1 hora
            self.refreshMinutes = 2 # em 2 minutos verifica novamente
            self.showPage(exit1)
        return False

    def check(self):
        """ Verifica se já está na hora de bater o ponto, observando os horários de saída e o limite máximo de um período. """
        #Atualiza a cada 5min
        self.refreshMinutes = 5
        if not self.login():
            return NOT_LOGGED
        try:
            text = self.getPageText()
        except NotLoggedException:
            return NOT_LOGGED

        self.timeReturn = None

        entr1 = self.extractDate(text, 1, entrance=True)
        exit1 = self.extractDate(text, 1, entrance=False)
        entr2 = self.extractDate(text, 2, entrance=True)
        exit2 = self.extractDate(text, 2, entrance=False)

        if self.checkPeriod(entr1, exit1) and self.checkReturn(exit1, entr2):
            self.checkPeriod(entr2, exit2)

        if self.timeReturn == None:
            return PONTO_OK
        return PONTO_NOK

    def extractDate(self, text, period, entrance):
        """ Extraí a data de entrada ou saída no período informado 
        Formato:
        1º Período
        Saída- 11:58 """
        periodFound = False
        strPeriod = str(period) + u'º Período'
        if entrance:
            desc = u'Entrada'
        else:
            desc = u'Saída'
        for line in text.split('\n'):
            line = line.strip()
            if line != '':
                if line.startswith(strPeriod):
                    periodFound = True
                if periodFound and line.startswith(desc):
                    try:
                        parts = line.split('-')
                        if len(parts) < 2:
                            #Sem horário
                            return None
                        else:
                            shour = parts[1].strip().split(':')
                            today = datetime.date.today()
                            return datetime.datetime(year = today.year, month = today.month,
                                                        day = today.day, hour = int(shour[0]),
                                                        minute = int(shour[1]))
                    except:
                        raise Exception(u'SisCop - The page layout is unknown')
        #se chegar até aqui, é porque o layout é desconhecido
        raise Exception(u'SisCop - The page layout is unknown')

#####################################################
# CaptchaWindow
class CaptchaWindow(gtk.Window):

    def __init__(self, service, imgfilename):
        self.service = service
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)

        #self.set_size_request(250, 150)
        self.set_border_width(10)
        self.set_title("SisCop - Captcha")
        self.set_position(gtk.WIN_POS_CENTER)
        self.set_modal(True)

        self.add(self.createControls())
        self.okButton.grab_default()
        self.img.set_from_file(imgfilename)
        self.value.grab_focus()

    def createImgAndValue(self):
        # Create the img
        self.img = gtk.Image()
        self.img.show()

        # Create the value entry box
        valueLabel = gtk.Label(_("Value: "))
        valueLabel.show()

        self.value = gtk.Entry()
        self.value.set_max_length(50)
        self.value.connect("activate", self.login)
        self.value.show()

        table = gtk.Table(2, 2)
        table.set_row_spacings(8)

        table.attach(self.img, 0, 2, 0, 1, gtk.EXPAND, 0)
        table.attach(valueLabel, 0, 1, 1, 2, gtk.FILL, 0)
        table.attach(self.value, 1, 2, 1, 2, gtk.EXPAND | gtk.FILL, 0)

        table.show()

        return table

    def createButtons(self):
        self.okButton = gtk.Button(stock=gtk.STOCK_OK)
        self.okButton.connect("clicked", self.login)
        self.okButton.set_flags(gtk.CAN_DEFAULT)
        self.okButton.show()

        cancelButton = gtk.Button(stock=gtk.STOCK_CANCEL)
        cancelButton.connect("clicked", self.cancel)
        cancelButton.show()

        bbox = gtk.HButtonBox()
        bbox.set_layout(gtk.BUTTONBOX_EDGE)
        bbox.pack_start(cancelButton, True, True, 0)
        bbox.pack_end(self.okButton, True, True, 0)
        bbox.show()

        return bbox;

    def createControls(self):
        # Append login and pass entry box to vbox
        mainbox = gtk.VBox(False, 0)
        mainbox.set_spacing(15)
        mainbox.pack_start(self.createImgAndValue(), True, True, 0)
        mainbox.pack_end(self.createButtons(), False, True, 0)
        mainbox.show()
        return mainbox

    def show(self):
        # se alguma mensagem filha dessa janela for exibida o ícone precisa ser resetado
        self.set_icon_from_file(os.path.join(curdir, 'siscop_idle.png'))
        gtk.Window.show(self)

    def cancel(self, wnd):
        self.destroy()

    def run(self):
        self.show()

    def login(self, wnd):
        captcha = self.value.get_text().strip()
        if len(captcha) == 0:
            showMessage(_(u"Captcha value is required."), self.get_title(), self)
            return
        self.destroy()
        self.service.captchaValue = captcha
        self.service.refresh()

########################################
# main

if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow
    app = MonApp()
    app.name = 'SisCop Checker'
    app.addService(SisCopService)
    MonLoginWindow(app).run()
    app.run()
