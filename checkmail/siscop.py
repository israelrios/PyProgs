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
import sys
import subprocess

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
        if iconname is not None:
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

    def buildOpener(self):
        cookiejar = cookielib.CookieJar() #cookies são necessários para a autenticação
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
        opener.addheaders = [('User-agent', 'Mozilla/5.0 (X11; Linux i686; rv:35.0) Gecko/20100101 Firefox/35.0')]
        return (opener, cookiejar)

    def createTrayIcon(self):
        return SisCopTrayIcon(self)

    def runService(self, timered=True):
        if self != threading.currentThread():
            # não faz nada se chamado de outra thread
            return
        if timered:
            # não roda de madrugada
            hour = datetime.datetime.today().hour
            if hour >= 20 or hour <= 6:
                return
        # o valor de refreshMinutes pode ser alterado em self.check()
        status = self.check()
        self.setIcon(status)

    def showPage(self, pageId=None):
        if pageId is not None and self != threading.currentThread():
            return
        """ Mostra a página do SisCop se o pageId for diferente do último. """
        if pageId is None or pageId != self.lastPageId:
            if pageId is not None:
                self.lastPageId = pageId
            # verifica se a sessão ainda é válida, senão faz login.
            self.checkLogged(self.openUrlRegPonto())
            if not self.logged:
                self.login()
            # abre o browser com a página
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
        if pageId is not None:
            bus = dbus.SessionBus()
            ssaver = bus.get_object('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver')
            try:
                # costuma demorar alguns segundos pra retornar
                ssaver.SimulateUserActivity() # faz aparecer a tela de login caso o screensaver esteja ativado
            except:
                pass # costuma lançar um erro DBusException: org.freedesktop.DBus.Error.NoReply

    def decodeCaptcha(self):
        self.captchaValue = None
        for i in range(10):
            decoded = self.tryDecodeCaptcha()
            if decoded is not None:
                self.captchaValue = decoded
                break

    def tryDecodeCaptcha(self):
        self.tempOpener, self.tempCookiejar = self.buildOpener()
        html = self.tempOpener.open(self.urlLogin).read()
        # get the viewstate value
        mo = re.search(r"<input[^>]+id\s*=\s*['\"]?viewstate['\"]?[^>]+value\s*=\s*'([^']+)'", html, re.DOTALL)
        self.fields['viewstate'] = decode_htmlentities(mo.group(1))
        # get the captcha image url
        mo = re.search(r"src\s*=\s*'(/captcha/[^']+)'", html, re.DOTALL)
        fname = os.path.join(tempfile.gettempdir(), "siscop{0}.captcha.jpg".format(self.user))
        with open(fname, 'w') as f:
            f.write(self.tempOpener.open(self.urlSisCop + decode_htmlentities(mo.group(1))).read())
        decoded = subprocess.check_output(['java', '-jar', '/opt/capres/capres.jar', fname])
        decoded = decoded.strip()
        if len(decoded) != 5:
            return None
        return decoded


    def checkLogged(self, url):
        self.logged = not url.geturl().startswith(self.urlLogin)
        return self.logged
    
    def saveCookies(self):
        cookiesFileName = os.path.join( os.getenv('USERPROFILE') or os.getenv('HOME') or os.path.abspath( os.path.dirname(sys.argv[0]) ), '.siscop_cookies')
        with open(cookiesFileName, 'w') as f:
            for cookie in self.cookiejar:
                f.write("%s=%s\n" % (cookie.name, cookie.value))

    def login(self):
        if self.logged:
            return True
        for i in range(5):
            self.decodeCaptcha()
            if self.captchaValue is None:
                return False
            url = self.tryLogin()
            if 'Sequência de caracteres não confere' in url.read().decode('cp1252'):
                continue
            if self.checkLogged(url):
                self.saveCookies()
            break
        return self.logged

    def tryLogin(self):
        self.opener = self.tempOpener
        self.cookiejar = self.tempCookiejar
        self.fields['captcha'] = self.captchaValue
        self.captchaValue = None
        self.tempOpener = None
        self.tempCookiejar = None
        return self.opener.open(self.urlLogin, urllib.urlencode(self.fields))

    def openUrlRegPonto(self):
        try:
            return self.opener.open(self.urlCadRegPonto)
        except Exception, e:
            raise Exception(u"It was not possible to connect at SisCop. Error:\n\n" + str(e))

    def getPageText(self):
        """ Faz o login no SISCOP. Download da página de registro de ponto. Extrai o texto do HTML da página. """
        url = self.openUrlRegPonto()

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
        if dtEntr is None or dtExit is not None:
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
        if exit1 is None or entr2 is not None:
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
        #Atualiza a cada 40min
        self.refreshMinutes = 40
        if not self.login():
            return NOT_LOGGED
        try:
            text = self.getPageText()
        except NotLoggedException:
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

        if self.timeReturn is None:
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
                            return datetime.datetime(year=today.year, month=today.month,
                                                     day=today.day, hour=int(shour[0]),
                                                     minute=int(shour[1]))
                    except:
                        raise Exception(u'SisCop - The page layout is unknown')
        #se chegar até aqui, é porque o layout é desconhecido
        raise Exception(u'SisCop - The page layout is unknown')


########################################
# main

if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow
    app = MonApp()
    app.appid = 'scc'
    app.name = 'SisCop Checker'
    app.addService(SisCopService)
    MonLoginWindow(app).run()
    app.run()
