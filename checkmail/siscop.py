# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 15-abr-2009

from monitors import Service, TrayIcon, curdir
from monutil import HtmlTextParser, execute

import os
import urllib
import urllib2
import cookielib
import datetime
import dbus
import commands

SEC_HOUR = 60*60 # 1 hora em segundos

SEC_MAX_PERIOD = SEC_HOUR * 5 # 5hs
SEC_ALERT_PERIOD = SEC_MAX_PERIOD - (60 * 2) #4hs e 58mins

class SisCopTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showPage()

    def setIcon(self, ok):
        if ok:
            iconname = 'siscop_idle.png'
            tip = u'Ponto OK'
        else:
            iconname = 'siscop_waiting.png'
            tip = u'Aguarde para registrar o ponto ' + \
                self.service.timeReturn.strftime('(%H:%M)')
        iconname = os.path.join(curdir, iconname)
        self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)


class SisCopService(Service):
    urlSisCop = 'http://siscop.portalcorporativo.serpro/cpf_senha.asp'
    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        # Os campos do formulário
        self.fields = {}
        self.fields['tx_cpf'] = user
        self.fields['tx_senha'] = passwd
        #Inicialização
        cookies = cookielib.CookieJar() #cookies são necessários para a autenticação
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookies))
        #Atualiza a cada 55min
        self.refreshMinutes = 55
        self.lastPageId = None
    
    def createTrayIcon(self):
        return SisCopTrayIcon(self)

    def runService(self, timered=True):
        #o valor de refreshMinutos pode ser alterado em self.check()
        self.refreshMinutes = 55 # não tem necessidade de estressar o servidor
        self.setIcon(self.check())

    def showPage(self, pageId=None):
        """ Mostra a página do SisCop se o pageId for diferente do último. """
        if pageId == None or pageId != self.lastPageId:
            if pageId != None:
                self.lastPageId = pageId
            #abre o browser com a página
            procs = commands.getoutput('/bin/ps xo comm').split('\n')
            if 'chrome' in procs:
                execute(["google-chrome", self.urlSisCop])
                execute(["wmctrl", "-a", "Chrome"])
            else:
                execute(["firefox", self.urlSisCop])
                execute(["wmctrl", "-a", "Firefox"])

        #verifica se o usuário está na máquina
        bus = dbus.SessionBus()
        ssaver = bus.get_object('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver')
        mustShowPage = not ssaver.GetActive()
        try:
            ssaver.SimulateUserActivity() # faz aparecer a tela de login caso o screensaver esteja ativado
        except:
            pass # costuma lançar um erro DBusException: org.freedesktop.DBus.Error.NoReply

    def getPageText(self):
        """ Faz o login no SISCOP. Download da página de registro de ponto. Extrai o texto do HTML da página. """
        try:
            url = self.opener.open(self.urlSisCop)
            url = self.opener.open(self.urlSisCop, urllib.urlencode(self.fields))
        except Exception, e:
            raise Exception(u"It was not possible to connect at SisCop. Error:\n\n" + str(e))

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
        try:
            text = self.getPageText()
        except:
            self.refreshMinutes = 5 # em caso de erro verifica a página novamente em 5 minutos
            raise

        #Atualiza a cada 55min
        self.refreshMinutes = 55
        self.timeReturn = None

        entr1 = self.extractDate(text, 1, entrance=True)
        exit1 = self.extractDate(text, 1, entrance=False)
        entr2 = self.extractDate(text, 2, entrance=True)
        exit2 = self.extractDate(text, 2, entrance=False)

        if self.checkPeriod(entr1, exit1) and self.checkReturn(exit1, entr2):
            self.checkPeriod(entr2, exit2)

        return (self.timeReturn == None)

    def extractDate(self, text, period, entrance):
        """ Extraí a data de entrada ou saída no período informado 
        Formato:
        1º Período
        Saída- 11:58 """
        periodFound = False
        strPeriod = str(period) + u'º Período'
        if entrance:
            type = u'Entrada'
        else:
            type = u'Saída'
        for line in text.split('\n'):
            line = line.strip()
            if line != '':
                if line.startswith(strPeriod):
                    periodFound = True
                if periodFound and  line.startswith(type):
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

########################################
# main

if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow
    app = MonApp()
    app.name = 'SisCop Checker'
    app.addService(SisCopService)
    MonLoginWindow(app).run()
    app.run()
