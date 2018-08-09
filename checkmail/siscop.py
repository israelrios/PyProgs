#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 15-abr-2009

import commands
import datetime
import dbus
import os
import requests
import simplejson
import sys
import threading

from monitors import Service, TrayIcon, curdir
from monutil import execute, getProwl

SEC_HOUR = 60 * 60  # 1 hora em segundos

SEC_INTERVAL = SEC_HOUR / 2  # intervalo de almoço (1/2 hora)

SEC_MAX_PERIOD = SEC_HOUR * 5  # 5hs

SEC_NORMAL_DAY = SEC_HOUR * 8  # 8hs

# Atualiza a cada 29min
DEFAULT_REFRESH_INTERVAL = SEC_INTERVAL / 60.0 - 1.0

NOT_LOGGED = 3
PONTO_OK = 1
PONTO_NOK = 2

AUTHORIZATION_HEADER = 'Authorization'


class SisCopTrayIcon(TrayIcon):
    def onActivate(self, event):
        self.service.showPage()

    def prepareMenu(self, menu):
        TrayIcon.prepareMenu(self, menu)

    def setIcon(self, status):
        iconname = None
        if status == PONTO_OK:
            iconname = 'siscop_idle.png'
            tip = u'Ponto OK'
        elif status == PONTO_NOK:
            iconname = 'siscop_waiting.png'
            timeReturn = self.service.timeReturn
            if timeReturn is not None and timeReturn > datetime.datetime.today():
                tip = u'Aguarde para registrar o ponto ' + timeReturn.strftime('(%H:%M)')
            else:
                tip = u'Registre o ponto'
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
        super(NotLoggedException, self).__init__(self, u"Login required.")


def retryLogin(func):
    def wrapper(*args, **kwargs):
        obj = args[0]
        try:
            return func(*args, **kwargs)
        except NotLoggedException:
            obj.login()
            return func(*args, **kwargs)

    return wrapper


class SisCopService(Service):
    urlSisCop = 'https://siscopweb.serpro'
    urlLoginPage = urlSisCop + '/login.html'
    urlCadRegPonto = urlSisCop + '/registro.html'
    urlAuth = urlSisCop + '/api/auth'
    urlRegistro = urlSisCop + '/api/registro'

    def __init__(self, app, user, passwd):
        Service.__init__(self, app, user, passwd)
        # Os campos do formulário de login
        self.fields = {'username': user, 'password': passwd}
        # Inicialização
        self.token = None
        self.refreshMinutes = DEFAULT_REFRESH_INTERVAL
        self.lastPageId = None
        self.lastProwl = None
        self.logged = False
        self.timeReturn = None

        self.session = requests.Session()

        self.prowl = getProwl()

        self.configHeaders()

    def configHeaders(self):
        self.session.headers.update({
            'User-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
                          ' (KHTML, like Gecko) Chrome/68.0.3440.75 Safari/537.36',
            'Origin': self.urlSisCop,
            'Accept': '*/*'})

    def setToken(self, token):
        self.token = token
        if self.token:
            self.session.headers[AUTHORIZATION_HEADER] = 'Token ' + self.token
        else:
            self.session.headers.pop(AUTHORIZATION_HEADER, None)

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
        try:
            status = self.check()
            self.setIcon(status)
        except NotLoggedException:
            self.setIcon(NOT_LOGGED)

    def sendProwl(self, msg):
        if self.prowl is None:
            return

        # noinspection PyBroadException
        try:
            self.prowl.post("Siscop", "", msg)
        except Exception:
            print "Can't send to Prowl: " + sys.exc_info()[0]

    def showPage(self, pageId=None):
        """ Mostra a página do SisCop se o pageId for diferente do último. """

        if pageId is not None and self != threading.currentThread():
            return

        if pageId is None or pageId != self.lastPageId:
            if pageId is not None:
                self.lastPageId = pageId
            # abre o browser com a página
            procs = commands.getoutput('/bin/ps xo comm').split('\n')
            if 'chrome' in procs:
                execute(["google-chrome", self.buildUrlRegPonto()])
                execute(["wmctrl", "-a", "Chrome"])
            else:
                execute(["firefox", self.buildUrlRegPonto()])
                execute(["wmctrl", "-a", "Firefox"])
        else:
            # o usuário não registrou o ponto no horário adequado, envia um alerta via push
            if self.lastProwl != pageId:
                self.sendProwl("Registre o ponto")
                self.lastProwl = pageId

        # verifica se o usuário está na máquina
        if pageId is not None:
            # noinspection PyBroadException
            try:
                bus = dbus.SessionBus()
                ssaver = bus.get_object('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver')
                # costuma demorar alguns segundos pra retornar
                ssaver.SimulateUserActivity()  # faz aparecer a tela de login caso o screensaver esteja ativado
            except Exception:
                pass  # costuma lançar um erro DBusException: org.freedesktop.DBus.Error.NoReply

    def buildUrlRegPonto(self):
        return self.urlLoginPage
        # passa os cookies para o browser para evitar a tela de login
        # url = self.urlCadRegPonto + "?"
        # cookies = []
        # for cookie in self.session.cookies:
        #     cookies.append("%s=%s" % (cookie.name, cookie.value))
        # url = url + urllib.urlencode({'cookie': '; '.join(cookies), 'token': self.token})

    def isAuthValid(self, resp):
        self.logged = self.token \
                      and resp.status_code != 401 \
                      and not resp.url.startswith(self.urlLoginPage)
        return self.logged

    def assertLogged(self, resp):
        if not self.isAuthValid(resp):
            raise NotLoggedException()
        return resp

    def saveSession(self):
        userHome = os.getenv('USERPROFILE') or os.getenv('HOME') or os.path.abspath(os.path.dirname(sys.argv[0]))

        tokenFileName = os.path.join(userHome, '.siscop_token')
        with open(tokenFileName, 'w') as f:
            f.write("%s\n" % self.token)

        cookieFileName = os.path.join(userHome, '.siscop_cookies')
        with open(cookieFileName, 'w') as f:
            for cookie in self.session.cookies:
                f.write("%s=%s\n" % (cookie.name, cookie.value))

    def login(self):
        if self.logged:
            return True
        self.requestLogin()
        self.saveSession()

    def requestLogin(self):
        self.session.get(self.urlLoginPage)
        self.setToken(None)
        resp = self.session.post(self.urlAuth, json=self.fields)
        self.setToken(resp.headers.get('Set-Token', None))
        return self.assertLogged(resp)

    def requestRegistro(self):
        try:
            resp = self.session.get(self.urlRegistro)
        except Exception, e:
            raise Exception(u"It was not possible to connect at SisCop. Error:\n\n" + str(e))
        return self.assertLogged(resp)

    @retryLogin
    def getRegistros(self):
        """ Obtêm os registros de ponto do dia. Formato:
        {
            "tipo" : "E",
            "hora" : "2018-08-01 09:48:00",
            "registroAutomatico" : true,
            "dataBase" : "2018-08-01 09:48:00",
            "referenteJornadaDiaAnterior" : false,
            "registradoPor" : "11111111111",
            "ipRegistro" : "10.32.129.29"
        }
        """
        resp = self.requestRegistro()

        if resp.status_code == 204 or not resp.text:
            return None

        registros = simplejson.loads(resp.text)

        if len(registros) == 0:
            return None

        for reg in registros:
            reg['hora'] = SisCopService.toDate(reg['hora'])

        return registros

    def checkPeriod(self, registro):
        """ Verifica se já se passou mais de 5 horas da entrada do período. """
        if registro['tipo'] != 'E':
            return True

        dtreg = registro['hora']

        diff = datetime.datetime.today() - dtreg

        return not self.setNextRefreshOrShowPage(SEC_MAX_PERIOD, diff, dtreg, 0.5)

    def checkReturn(self, registro):
        """ Verifica se o retorno do almoço foi registrado. """
        dtreg = registro['hora']

        if registro['tipo'] == 'E' or dtreg.hour < 11 or dtreg.hour >= 15:
            return True

        diff = datetime.datetime.today() - dtreg

        self.timeReturn = dtreg + datetime.timedelta(seconds=SEC_INTERVAL)

        self.setNextRefreshOrShowPage(SEC_INTERVAL, diff, dtreg, 2)
        return False

    def checkDay(self, registros):
        """ Verifica se a jornada de trabalho deve ser concluída. """
        total = datetime.timedelta(0)
        dtstart = None
        for reg in registros:
            dtreg = reg['hora']
            if reg['tipo'] == 'E':
                dtstart = dtreg
            elif dtstart is not None:
                total += dtreg - dtstart
                dtstart = None

        if dtstart is None or total.seconds == 0:
            # o último registro é de saída ou não há registros
            return True

        total += datetime.datetime.today() - dtstart

        return not self.setNextRefreshOrShowPage(SEC_NORMAL_DAY, total, dtstart, 1)

    def setNextRefreshOrShowPage(self, maxSeconds, tdelta, pageId, showPageRefresh):
        """ Define o próximo refresh com base no tdelda (diferença de tempo).
          Se tdelda for maior que maxSeconds dispara a ação para mostrar a página do siscop
          e define o próximo refresh para showPageRefresh.
          Retorna True quando a página foi exibida."""
        if tdelta.seconds < maxSeconds:
            secDiff = maxSeconds - tdelta.seconds + 1  # 1 segundo a mais
            self.setMinRefresh(float(secDiff) / 60.0)
            return False

        self.showPage(pageId)
        self.setMinRefresh(showPageRefresh)
        return True

    def setMinRefresh(self, newRefresh):
        self.refreshMinutes = min(self.refreshMinutes, newRefresh)

    def check(self):
        """ Verifica se já está na hora de bater o ponto, observando os horários de saída e o limite máximo de um
        período. """
        self.refreshMinutes = DEFAULT_REFRESH_INTERVAL

        self.login()
        registros = self.getRegistros()

        self.timeReturn = None

        if registros is None:
            return PONTO_OK

        # todos os registros do dia são obtidos, pegamos só o último
        registro = registros[-1]

        if self.checkPeriod(registro) and self.checkReturn(registro) and self.checkDay(registros):
            return PONTO_OK

        return PONTO_NOK

    @staticmethod
    def toDate(text):
        """ Converte para data. Formatado da entrada: 2018-08-01 09:48:00"""
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


########################################
# main

def run():
    app = MonApp()
    app.appid = 'scc'
    app.name = 'SisCop Checker'
    app.addService(SisCopService)
    MonLoginWindow(app).run()
    app.run()


if __name__ == '__main__':
    from monitors import MonApp, MonLoginWindow

    run()
