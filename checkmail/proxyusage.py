#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 23-jan-2009

import os
import gtk
from monitors import Service, TrayIcon
import urllib
import urllib2
import cookielib
import time
import locale
import re
from monutil import HtmlTextParser, execute

#####################################################################
#ProxyUsage

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

    def setIcon(self, percent, tip):
        self.percent = percent
        self.icon.update(percent)
        self.set_from_pixbuf(self.icon)
        self.set_tooltip(tip)
        self.set_visible(True)


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
        self.setIcon(percent, texto)

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
        if mo is not None:
            return mo.groups()
        else:
            #O parser não suporta HTML entitys (Ex: &aacute)
            if parser.texto.find('No h registro para seu usurio at o momento') >= 0 :
                return [time.strftime("%d/%m/%Y %H:%M:%S", time.localtime()), '0', 'K', '0']
            raise Exception(u"It was not possible to check your proxy usage.\n" +
                            u"Make sure the entered username and password are correct.")