# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 15-abr-2009

from monitors import Service, HtmlTextParser, TrayIcon, gtkupdate, curdir, execute

import os
import urllib
import urllib2
import cookielib
from HTMLParser import HTMLParser
import datetime
from threading import Timer
import dbus

SEC_HOUR = 60*60 # 1 hora em segundos

class SisCopTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showPage()

    @gtkupdate
    def setIcon(self, ok):
        if ok:
            iconname = 'siscop_idle.png'
            tip = u'Ponto OK'
        else:
            iconname = 'siscop_waiting.png'
            tip = u'Aguarde para registrar o ponto ' + \
                self.service.horaRetorno.strftime('(%H:%M)')
        iconname = os.path.join(curdir, iconname)
        self.set_from_file(iconname)
        self.set_tooltip(tip)
        self.set_visible(True)


class SisCopService(Service):
    urlSisCop = 'http://siscop.portalcorporativo.serpro/cpf_senha.asp'
    timer = None
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
    
    def createTrayIcon(self):
        return SisCopTrayIcon(self)

    def onQuit(self):
        Service.onQuit(self)
        if self.timer != None:
            self.timer.cancel()

    def runService(self, timered=True):
        #o valor de refreshMinutos pode ser alterado em self.check()
        self.refreshMinutes = 55 # não tem necessidade de estressar o servidor
        self.getTrayIcon().setIcon(self.check())

    def showPage(self):
        #abre o browser com a página
        execute(["firefox", self.urlSisCop])

    def onTimer(self):
        mustShowPage = self.timer != None
        #self.getTrayIcon().setIcon(not self.timer != None)
        self.timer = None
        
        if not mustShowPage:
            #verifica se o usuário está na máquina
            bus = dbus.SessionBus()
            ssaver = bus.get_object('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver')
            mustShowPage = not ssaver.GetSessionIdle()
        
        if mustShowPage:
            self.showPage()

    ###########################################################
    # Extrai o texto do HTML e separa a informação do ponto
    # Formato:
    #   1º Período
    #   Saída- 11:58
    def check(self):
        try:
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

        #Extraí a data da última saída
        text = parser.texto
        dtSaida = self.extractDate(text, 1, entrance=False)
        if dtSaida != None:
            print u"Exit date first period: ", dtSaida
            if self.hasEntrada(text):
                self.terminated = True #Está tudo OK
            else:
                #Verifica se a diferença é menor que uma hora
                diff = datetime.datetime.today() - dtSaida
                self.horaRetorno = dtSaida + datetime.timedelta(seconds=SEC_HOUR)
                if diff.seconds < SEC_HOUR: #menor que uma hora
                    if self.timer == None:
                        secDiff = SEC_HOUR - diff.seconds
                        self.timer = Timer(secDiff, self.onTimer)
                        self.timer.setDaemon(True)
                        self.timer.start()
                        print "timer started"
                        #executa novamente em 1 minuto após a hora prevista para registro
                        self.refreshMinutes = 1.0 + float(secDiff)/60.0
                else:
                    self.refreshMinutes = 5 # em 5 minutos verifica novamente
                    self.onTimer()
                return False
        return True
                

    def hasEntrada(self, text):
        return self.extractDate(text, 2, entrance=True) != None

    def extractDate(self, text, period, entrance):
        """ Extraí a data de entrada ou saída no período informado """
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

