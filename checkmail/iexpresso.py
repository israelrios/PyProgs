#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 17-nov-2009

import imap4utf7 # pro codec imap4-utf-7 @UnusedImport

from monutil import decode_header, MultipartPostHandler

import sys
import urllib
import urllib2
import cookielib
import re
import os
import datetime
import zipfile
import time, random
import traceback
#import cPickle
from htmlentitydefs import name2codepoint as n2cp
from cStringIO import StringIO
from StringIO import StringIO as pyStringIO

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import email.utils
import email.header
from email.generator import Generator as EmailGenerator

import imaplib
import hashlib

#diretório das configurações e do log
iexpressodir = os.path.join( os.getenv('USERPROFILE') or os.getenv('HOME') or os.path.abspath( os.path.dirname(sys.argv[0]) ), '.iexpresso')
logfile = os.path.join(iexpressodir, 'log.txt')

def log(*params):
    f = open(logfile, 'a+')
    printSpace = False
    for p in params:
        if printSpace:
            f.write(' ');
        else:
            printSpace = True
        if isinstance(p, unicode):
            f.write(p.encode('utf-8'))
        else:
            f.write(str(p))
    f.write('\n')
    f.close()

def logError():
    log(traceback.format_exc())

def compressLog():
    """Compress the log file if it is large enough."""
    # larger than 2MB
    if os.path.exists(logfile) and os.path.getsize(logfile) > (2 * 1024 * 1024):
        logfilezip = logfile + ".zip"
        if os.path.exists(logfilezip):
            os.remove(logfilezip)

        zf = zipfile.ZipFile(logfilezip, 'w', zipfile.ZIP_DEFLATED)
        try:
            zf.write(logfile, os.path.split(logfile)[1])
        finally:
            zf.close()
        os.remove(logfile)

###################################
# Response parser functions
def substitute_entity(match):
    ent = match.group(2)
    if match.group(1) == "#":
        return unichr(int(ent))
    else:
        cp = n2cp.get(ent)

        if cp:
            return unichr(cp)
        else:
            return match.group()

def decode_htmlentities(string):
    entity_re = re.compile("&(#?)(\d{1,5}|\w{1,8});")
    return entity_re.subn(substitute_entity, string)[0]

# Portei este código do arquivo connector.js do expresso.
def matchBracket(text, iniPos):
    nClose = iniPos
    while True:
        nOpen = text.find('{', nClose+1)
        nClose = text.find('}', nClose+1)
        if (nOpen == -1):
            return nClose

        if (nOpen < nClose ):
            nClose = matchBracket(text, nOpen)

        if (nOpen >= nClose):
            return nClose

###########################################################
# Faz o parse da resposta do expresso. Portei este código do arquivo connector.js do expresso.
# Formato:
#   a:n:{s:n:"";i:k;};
#   Saída: dicionário com os valores
def unserialize(text):
    itemtype = text[0]
    if itemtype == 'a':
        n = int( text[text.index(':')+1 : text.index(':',2)] )
        arrayContent = text[text.index('{')+1 : text.rindex('}')]

        data = {}
        for _ in range(n):
            pos = 0

            #/* Process Index */
            indexStr = arrayContent[ : arrayContent.index(';')+1]
            index = unserialize(indexStr)

            pos = arrayContent.index(';', pos)+1

            #/* Process Content */
            subtype = arrayContent[pos]
            if subtype == 'a':
                endpos = matchBracket(arrayContent, arrayContent.index('{', pos))+1
                part = arrayContent[pos: endpos]
                pos = endpos
                data[index] = unserialize(part)

            elif subtype == 's':
                pval = arrayContent.index(':', pos+2)
                val  = int(arrayContent[pos+2 : pval])
                pos = pval + val + 4
                data[index] = arrayContent[pval+2 : pval + 2 + val]

            else:
                endpos = arrayContent.index(';', pos)+1
                part = arrayContent[pos : endpos]
                pos = endpos
                data[index] = unserialize(part)
            arrayContent = arrayContent[pos:]

    elif itemtype == 's':
        pos = text.index(':', 2)
        val = int(text[2 : pos])
        data = text[pos+2 : pos + 2 + val]
        #text = text[pos + 4 + val : ]

    elif itemtype == 'i' or itemtype == 'd':
        pos = text.index(';')
        data = int(text[2  : pos])
        #text = text[pos + 1 : ]

    elif itemtype == 'N':
        data = None
        #text = text[text.index(';') + 1 : ]

    elif itemtype == 'b':
        if text[2] == '1':
            data = True
        else:
            data = False
    else:
        raise Exception(_('Invalid response format from Expresso.'))

    return data

###########################################
# EMAIL Message Helpers
###########################################
# pattern to find "\n" within encoded words
patBrokenEncWord = re.compile( r'=\?([^][\000-\040()<>@,\;:*\"/?.=]+)(?:\*[^?]+)?\?'
                               r'(B\?[+/0-9A-Za-z]*\r*\n[ \t][+/0-9A-Za-z]*=*'
                               r'|Q\?[ ->@-~]*\r*\n[ \t][ ->@-~]*'
                               r')\?=', re.MULTILINE | re.IGNORECASE)
patSubject = re.compile(r'^Subject:((?:[ \t](.+?)\r*\n)+)', re.MULTILINE | re.IGNORECASE)
patEmptyLine = re.compile(r'^\r*\n', re.MULTILINE | re.IGNORECASE)
patSender = re.compile('^Sender: (.+?)[\r\n]', re.MULTILINE | re.IGNORECASE)
# empty Message-Id's wanted too
patMessageId = re.compile('^Message-Id: (.*?)\n', re.MULTILINE | re.IGNORECASE)
#Date: Mon, 21 Jun 2010 10:16:39 -0300
patDate = re.compile(
    r'^Date: (?:(?P<wday>[A-Z][a-z][a-z]), )?(?P<day>[0123]?[0-9])'
    r' (?P<mon>[A-Z][a-z][a-z]) (?P<year>[0-9][0-9][0-9][0-9])'
    r' (?P<hour>[0-9][0-9]):(?P<min>[0-9][0-9]):(?P<sec>[0-9][0-9])'
    r' (?P<zonen>[-+])(?P<zoneh>[0-9][0-9])(?P<zonem>[0-9][0-9])[\r\n]', re.MULTILINE)

def fixEncodedWord(subject):
    return patBrokenEncWord.sub(lambda m: re.sub(r'(\r*\n[ \t]| (?=_))', '', m.group()), subject)

class MailMessage:
    def __init__(self, msgsrc):
        self.msgsrc = msgsrc
        self.headers = None

    def getHeaders(self):
        if self.headers is None:
            self.headers = self.msgsrc[:self.getHeadersEnd()]
        return self.headers

    def getHeadersEnd(self):
        mo = patEmptyLine.search(self.msgsrc)
        if mo != None:
            return mo.start()
        return len(self.msgsrc)

    def fixSubjectBrokenWord(self):
        """ Fixes bad formatted subjects. Especially the case of "\n" within encoded words. """
        try:
            mo = patSubject.search(self.getHeaders())
            if mo != None:
                subject = mo.group(1)[1:]
                newsubject = fixEncodedWord(subject)
                if subject != newsubject:
                    log( "Fixing Subject: ", subject )
                    subject = decode_header(newsubject.rstrip())
                    subject = email.header.Header(subject, 'utf-8').encode()
                    subject = re.sub(r'(?<!\r)\n', '\r\n', subject) + '\r\n'
                    self.msgsrc = self.msgsrc[:mo.start(1)+1] + subject + self.msgsrc[mo.end():]
        except:
            logError() #ignora exceções nessa parte. (não é fundamental pro funcionamento do sistema)

    def getMessageId(self):
        # se não houver um Message-Id retorna None
        mo = patMessageId.search(self.getHeaders())
        if mo != None:
            return mo.group(1).strip();
        else:
            return None

    def getSender(self):
        mo = patSender.search(self.getHeaders())
        if mo != None:
            return decode_header(mo.group(1).strip())
        return "";

    def setMessageId(self, newid):
        # coloca o Message-Id e na mensagem.
        hend = self.getHeadersEnd()
        self.msgsrc = patMessageId.sub('', self.msgsrc[:hend]) + \
            'Message-Id: ' + newid + "\r\n" + self.msgsrc[hend:]
        self.headers = None

    def getMessageDateAsInt(self):
        """Convert MESSAGE Date to UT.
        Returns Python date as int.
        Adapted from imaplib.Internaldate2tuple
        """
        mo = patDate.search(self.getHeaders())
        if mo is None:
            return None

        mon = imaplib.Mon2num[mo.group('mon')]
        zonen = mo.group('zonen')

        day = int(mo.group('day'))
        year = int(mo.group('year'))
        hour = int(mo.group('hour'))
        minutes = int(mo.group('min'))
        sec = int(mo.group('sec'))
        zoneh = int(mo.group('zoneh'))
        zonem = int(mo.group('zonem'))

        # timezone must be subtracted to get UT

        zone = (zoneh*60 + zonem)*60
        if zonen == '-':
            zone = -zone

        tt = (year, mon, day, hour, minutes, sec, -1, -1, -1)

        utc = time.mktime(tt)

        # Following is necessary because the time module has no 'mkgmtime'.
        # 'mktime' assumes arg in local timezone, so adds timezone/altzone.

        lt = time.localtime(utc)
        if time.daylight and lt[-1]:
            zone = zone + time.altzone
        else:
            zone = zone + time.timezone

        return int(utc - zone)


def msgToStr(msg):
    fp = StringIO()
    g = EmailGenerator(fp, mangle_from_=False) #mangle_from = False para não por o ">" no início.
    g.flatten(msg)
    return fp.getvalue()



###########################################
# HELPERS
##########################################
def checkImapError(typ, resp):
    if typ != 'OK':
        if len(resp) > 0:
            raise Exception(resp[0])
        else:
            raise Exception(_('Bad response.'))


class NamedStringIO(pyStringIO):
    def __init__(self, name, buf = None):
        self.name = name
        pyStringIO.__init__(self, buf)

class IExpressoError(Exception):
    pass

class LoginError(IExpressoError):
    '''
    Exception thrown upon login failures.
    '''
    pass

# expresso msg fields:
# ContentType: string
# smalldate: string(dd/mm/yyyy)
# msg_number: number
# Importance: flag
# timestamp: date in seconds
# msg_sample: dict {body : string}
# udate: date in seconds
# subject: string
# Answered: flag
# Size: string
# Draft: flag
# attachment: dict{names: string, number_attachments: number}
# Unseen: flag
# from: dict {name : string, email: string},
# Deleted: flag
# Flagged: flag
# to: dict {name: string, email: string}
# Recent: flag

def makeEmailDesc(person):
    return '%s <%s>' % (email.utils.quote(decode_htmlentities(person['name'] or '')), person['email'] or '')

class ExpressoMessage:
    def checkFlag(self, flag):
        if isinstance(flag, bool):
            return flag
        return flag.strip() != ''

    def __init__(self, values):
        try:
            if 'ContentType' in values:
                self.contentType = values['ContentType']
            else:
                self.contentType = 'normal'
            if 'msg_day' in values:
                self.date = datetime.datetime.strptime(values['msg_day'] + values['msg_hour'], '%d/%m/%Y%H:%M')
            elif 'timestamp' in values:
                self.date = datetime.datetime.utcfromtimestamp(values['timestamp'])
            else:
                self.date = datetime.datetime.strptime(values['smalldate'], '%d/%m/%Y')
            if 'body' in values:
                self.full = True
                self.body = values['body']
            else:
                self.full = False
                if 'msg_sample' in values:
                    self.body = values['msg_sample']['body'][3:] # retira o " - " do começo
                else:
                    self.body = ''
            self.id = values['msg_number']
            self.subject = values['subject'].replace('\n', ' ')
            # este while é pra corrigir um bug do expresso que coloca html entities no subject indevidamente
            while True:
                newsubj = decode_htmlentities(self.subject)
                if newsubj == self.subject:
                    break
                self.subject = newsubj
            self.size = int(values['Size'])
            self.draft = 'Draft' in values and self.checkFlag(values['Draft'])
            self.answered = 'Answered' in values and self.checkFlag(values['Answered'])
            self.unread = self.checkFlag(values['Unseen']) or values['Recent'] == 'N'
            self.deleted = self.checkFlag(values['Deleted'])
            self.forwarded = 'Forwarded' in values and self.checkFlag(values['Forwarded'])
            #if self.full:
            #    log( values['Flagged'] )
            #    self.flagged = values['Flagged']
            #else:
            self.flagged = self.checkFlag(values['Flagged'])
            self.star = self.flagged
            self.recent = self.checkFlag(values['Recent'])

            if 'from' in values:
                self.sfrom = makeEmailDesc(values['from'])
            else:
                self.sfrom = ''
            if 'toaddress2' in values:
                self.to = decode_htmlentities(values['toaddress2'])
            else:
                self.to = makeEmailDesc(values['to'])

            if 'attachment' in values and values['attachment']['number_attachments'] > 0:
                self.attachmentNames = values['attachment']['names']
            else:
                self.attachmentNames = ''

            if 'cc' in values:
                self.cc = values['cc']
            else:
                self.cc = ''

            self.hashid = self.calcHashId()
        except:
            log( values )
            raise

    def calcHashId(self):
        m = hashlib.md5()
        m.update(self.contentType + '@')
        m.update(self.date.isoformat() + '@')
        m.update(self.sfrom.encode('utf-8') + '@')
        m.update(self.to.encode('utf-8') + '@')
        m.update(self.subject.encode('utf-8') + '@')
        m.update(self.body.encode('utf-8') + '@')
        m.update(self.attachmentNames.encode('utf-8') + '@')
        m.update(str(self.size))
        return m.hexdigest()

    def getFlags(self):
        flags = set()
        if self.answered:
            flags.add(r'\Answered')
        if not self.unread:
            flags.add(r'\Seen')
        if self.deleted:
            flags.add(r'\Deleted')
        if self.draft:
            flags.add(r'\Draft')
        if self.flagged:
            flags.add(r'\Flagged')
        if self.forwarded:
            flags.add(r'$Forwarded')
        return flags

    def createMimeMessage(self, dbid = None):
        # Create the container (outer) email message.
        msg = MIMEMultipart()
        #msg = MIMEText(self.body.encode('iso-8859-1'), 'html', 'iso-8859-1')
        msg['Subject'] = self.subject
        msg['From'] = self.sfrom
        msg['To'] = self.to
        if self.cc != '':
            msg['CC'] = self.cc
        if dbid != None:
            msg['DB-ID'] = str(dbid)
        #msg['Delivered-To'] = 'israel.rios@sepro.gov.br'
        #msg['Message-ID'] = str(self.id) + "@localhost"
        #msg.preamble = 'This is a multi-part message in MIME format.'

        #msg['Received'] = 'by 10.100.4.16 with HTTP; Wed, 4 Nov 2009 02:16:20 -0800 (PST)'
        msg['Date'] = email.utils.formatdate(time.mktime(self.date.timetuple()), True)
        # TODO: Adicionar os anexos
        #for file in pngfiles:
        #    fp = open(file, 'rb')
        #    img = MIMEBase(fp.read())
        #    fp.close()
        #    msg.attach(img)
        text = MIMEText(self.body.encode('utf-8'), 'html', 'UTF-8')

        msg.attach(text)

        #log( str(msg) )

        return str(msg)


class ExpressoManager:
    urlExpresso = 'https://expresso.serpro.gov.br/'
    urlLogin = urlExpresso + 'login.php'
    urlIndex = urlExpresso + 'expressoMail1_2/index.php'
    urlController = urlExpresso + 'expressoMail1_2/controller.php'
    urlAction = urlController + '?action=$this.'
    urlImapFunc = urlAction + 'imap_functions.'
    urlCheck = urlImapFunc + 'get_range_msgs2&msg_range_begin=1&msg_range_end=5000&sort_box_type=SORTARRIVAL&sort_box_reverse=1&'
    urlListFolders = urlImapFunc + 'get_folders_list&onload=true'
    urlMoveMsgs = urlImapFunc + 'move_messages&border_ID=null&sort_box_type=SORTARRIVAL&search_box_type=ALL&sort_box_reverse=1&reuse_border=null&get_previous_msg=0&'
    urlSetFlags = urlImapFunc + 'set_messages_flag&'
    urlGetMsg = urlImapFunc + 'get_info_msg&'
    urlCreateFolder = urlImapFunc + 'create_mailbox&'
    urlDeleteFolder = urlImapFunc + 'delete_mailbox&'
    urlGetQuota = urlImapFunc + 'get_quota&folder_id=INBOX'
    urlDownloadMessages = urlExpresso + 'expressoMail1_2/inc/gotodownload.php?msg_folder=null&msg_number=null&msg_part=null&newfilename=mensagens.zip&'
    urlMakeEml = urlAction + 'exporteml.makeAll'
    urlExportMsg = urlAction + 'exporteml.export_msg'
    urlGetReturnExecuteForm = urlAction + 'functions.getReturnExecuteForm'
    urlDeleteMsgs = urlImapFunc + 'delete_msgs&border_ID=null&'
    urlInitRules = urlAction + 'ScriptS.init_a'
    urlAutoClean = urlImapFunc + 'automatic_trash_cleanness&cyrus_delimiter=/&'
    urlGetPrefs = urlAction + 'functions.get_preferences'

    def __init__(self, user, passwd):
        # Os campos do formulário
        self.user = user
        self.passwd = passwd
        self.fields = {}
        self.fields['passwd_type'] = 'text'
        self.fields['account type'] = 'u'
        self.fields['user'] = user
        self.fields['login'] = user
        self.fields['passwd'] = passwd
        self.fields['certificado'] = ''

        self.logged = False

        self.quota = 0
        self.quotaLimit = 51200 #Kylo Bytes

        #Inicialização
        cookies = cookielib.CookieJar() #cookies são necessários para a autenticação
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookies), MultipartPostHandler )

    def openUrl(self, surl, params, post):
        if params != None and not post:
            if not surl.endswith('&'):
                surl += '&'
            surl += urllib.urlencode(params, True)
            params = None
        #log( surl )
        url = self.opener.open(surl, params)
        if url.geturl().startswith(self.urlLogin):
            url.close()
            self.doLogin()
            url = self.opener.open(surl, params)
        return url

    def callExpresso(self, surl, params = None, post = False):
        url = self.openUrl(surl, params, post)
        response = url.read().decode('iso-8859-1')
        url.close()
        return unserialize(response)

    def doLogin(self):
        try:
            url = self.opener.open(self.urlLogin, urllib.urlencode(self.fields))
            url.close()

            # chama o index para inicializar os atributos na sessão do servidor
            url = self.opener.open(self.urlIndex)
            self.logged = not url.geturl().startswith(self.urlLogin)
            url.close()
        except Exception, e:
            raise LoginError(_(u"It was not possible to connect at Expresso.") + " " + _(u"Error:") + "\n\n" + str(e))
        if not self.logged:
            raise LoginError(_(u"It was not possible to connect at Expresso.") + " " + _(u"Check your password."))

    def listFolders(self):
        data = self.callExpresso(self.urlListFolders)
        folders = set() # usa-se um set porque o expresso pode retornar nomes repetidos
        # as pastas vem indexadas de 0 até n em data
        i = 0
        while i in data:
            folders.add(data[i]['folder_id'])
            i += 1
        # os outros 3 parâmetros são 'quota_limit', 'quota_percent', 'quota_used'
        self.quota = data['quota_percent']
        self.quotaLimit = data['quota_limit']
        return folders

    def createFolder(self, path):
        res = self.callExpresso(self.urlCreateFolder, {'newp': path.encode('utf-8')})
        if res.lower() != 'ok':
            raise Exception(res.replace('<br />', ''))

    def deleteFolder(self, path):
        """ Cuidado! Exclui também as mensagens que estão dentro da pasta """
        res = self.callExpresso(self.urlDeleteFolder, {'del_past': path.encode('utf-8')})
        if res.lower() != 'ok':
            raise Exception(res.replace('<br />', ''))

    def getMsg(self, msgfolder, msgid):
        return ExpressoMessage(self.callExpresso(self.urlGetMsg, {'msg_number': msgid,
                                                                  'msg_folder' : msgfolder.encode('iso-8859-1')}))

    def getFullMsgs(self, msgfolder, msgsid):
        idx_file = self.callExpresso(self.urlMakeEml, {'folder': msgfolder.encode('utf-8'), 'msgs_to_export': msgsid}, True)

        if not idx_file:
            return None
        try:
            url = self.openUrl(self.urlDownloadMessages, {'idx_file': idx_file}, False)
        except urllib2.HTTPError, e:
            # handling errors from expresso when exporting messages, only to small lists
            if (e.code == 404) and (msgsid.count(',') < 2):
                return None
            raise
        except:
            log( "Error downloading full messages.", "   idx_file:", idx_file )
            raise
        try:
            zfile = zipfile.ZipFile(StringIO(url.read()))
            msgs = {}
            for name in zfile.namelist():
                #formato do nome SUBJECT_ID.eml, extraí o ID do nome do arquivo
                source = str(zfile.read(name)) # a codificação das mensagens é ASCII
                if not "From:" in source:
                    continue # mensagem inválida
                idstart = name.rindex('_') + 1
                if idstart <= 0:
                    continue # id não identificado
                msgs[int(name[idstart : -4])] = source
            zfile.close()
        except zipfile.BadZipfile, e:
            log( "Error downloading full messages.", "   idx_file:", idx_file )
            return None
        finally:
            url.close()
        return msgs

    def getFullMsgEspecial(self, msgfolder, msgid):
        #faz o download e uma única mensagem, deve ser usado nos casos em que getFullMsgs não funciona
        idx_file = self.callExpresso(self.urlExportMsg, {'folder': msgfolder.encode('utf-8'), 'msgs_to_export': msgid}, True)

        if not idx_file:
            return None

        url = self.openUrl(self.urlDownloadMessages, {'idx_file': idx_file}, False)
        source = str(url.read())
        url.close()
        if not "From:" in source:
            return None #mensagem inválida
        return source

    def importMsgs(self, msgfolder, msgfile):
        url = self.openUrl(self.urlController, {'folder': msgfolder.encode('iso-8859-1'), '_action': '$this.imap_functions.import_msgs',
                                                    'countFiles': 1, 'file_1' : msgfile}, True)
        url.close()
        #verifica se aconteceu algum erro
        result = self.callExpresso(self.urlGetReturnExecuteForm)
        if 'error' in result and result['error'].strip() != '':
            raise Exception(result['error'])

    def importMsgWithTime(self, msgfolder, source, msgtime, flagset):
        """ Faz o import com o método unarchive_mail.
            Este método possibilita a informação da data da mensagem. """

        # converte os flags para o formato da função do expresso
        flagmap = [('\\Answered','A'), ('\\Draft','X'), ('\\Flagged','F'), ('\\Unseen','U'), ('$Forwarded', 'F')]
        eflags = [];
        for (flagname, flagsymbol) in flagmap:
            if flagname in flagset:
                eflags.append(flagsymbol)
            else:
                eflags.append('')

        url = self.openUrl(self.urlController, {'folder': msgfolder.encode('utf-8'),
                                                '_action': '$this.imap_functions.unarchive_mail', 'id' : '1',
                                                'source': source, 'timestamp' : msgtime, 'flags' : ':'.join(eflags)}, True)
        url.close()
        #verifica se aconteceu algum erro
        result = self.callExpresso(self.urlGetReturnExecuteForm)
        if 'error' in result and not isinstance(result['error'], bool) and result['error'].strip() != '':
            raise Exception(result['error'])
        # o result contem um item 'archived' com o número do mensagem passado no parâmetro 'id'

    def setMsgFlag(self, msgfolder, msgid, flag):
        self.callExpresso(self.urlSetFlags, {'flag': flag.lower(), 'msgs_to_set' : msgid, 'folder' : msgfolder.encode('iso-8859-1')})

    def getMsgs(self, criteria, folder):
        """ Por motivos de compatibilidade o atributo criteria deve estar entre: "ALL", "UNSEEN" e "SEEN".
        """
        filterParam = {'search_box_type': criteria.encode('iso-8859-1'), 'folder': folder.encode('iso-8859-1')}

        data = self.callExpresso(self.urlCheck, filterParam)
        # verifica se a resposta é válida
        if isinstance(data, bool):
            raise Exception(_('Error loading messages from Expresso.'))

        msgs = []
        # as mensagens vem identificadas por um número (sequêncial) no dict da resposta
        i = 0
        while i in data:
            msgs.append(ExpressoMessage(data[i]))
            i += 1

        return msgs

    def updateQuota(self):
        data = self.callExpresso(self.urlGetQuota)
        # os 3 parâmetros são 'quota_limit', 'quota_percent', 'quota_used'
        self.quota = data['quota_percent']
        self.quotaLimit = data['quota_limit']

    def moveMsgs(self, msgid, msgfolder, newfolder):
        if newfolder.upper() == 'INBOX':
            newfoldername = 'Caixa de Entrada'
        else:
            newfoldername = newfolder.split('/')[-1]
        self.callExpresso(self.urlMoveMsgs, {'folder': msgfolder.encode('iso-8859-1'), 'msgs_number': msgid,
                                            'new_folder' : newfolder.encode('iso-8859-1'), 'new_folder_name': newfoldername.encode('iso-8859-1')})

    def deleteMsgs(self, msgid, msgfolder):
        """Cuidado! Exclui permanentente as mensagens."""
        self.callExpresso(self.urlDeleteMsgs, {'folder': msgfolder.encode('iso-8859-1'), 'msgs_number': msgid})

    def getFoldersWithRules(self):
        data = self.callExpresso(self.urlInitRules)
        folders = ['INBOX']
        if 'rule' in data:
            rules = data['rule']
            for i in rules:
                rule = rules[i].split('&&')
                folder = rule[7]
                # só filtros, com pastas que não sejas a lixeira e que começem com INBOX
                if rule[2] == 'ENABLED' and rule[6] == 'folder' and folder != 'INBOX/Trash' \
                   and len(folder) > 0 and not folder in folders and folder.startswith('INBOX'):
                    folders.append(folder)
        return folders

    def getPrefs(self):
        return self.callExpresso(self.urlGetPrefs)

    def autoClean(self):
        prefs = self.getPrefs()
        # verifica qual a configuração do usuário
        past_days_count = int(prefs.get('delete_trash_messages_after_n_days', '0'))
        if past_days_count == 0:
            log( "Skipping trash auto clean" )
            return
        data = self.callExpresso(self.urlAutoClean, {'before_date': past_days_count})
        log( "AutoClean(%d) response:" % past_days_count, data )


##################################################
# MSG DB
##################################################
class MsgItem():
    def __init__(self, msgid, hashid, msgfolder, msgflags):
        self.id = msgid
        self.hashid = hashid
        self.folder = msgfolder
        self.flags = msgflags

class MsgList():
    def __init__(self):
        self.db = {}
        self.eindex = {}
        self.signature = u'<%f_%d@localhost.signature>' % (time.time(), random.randint(0,100000))
        self.isNew = True
        self.folders = set()
        self.updated = True # quando alguma mensagem foi adicionada ou excluída
        self.msgupdated = False # quando algum flag da mensagem foi modificado ou a mensagem foi movida

    def ekey(self, msgid, msgfolder):
        return '{0}@{1}'.format(msgid, msgfolder)

    def add(self, dbid, msgid, hashid, msgfolder, msgflags):
        self.db[dbid] = MsgItem(msgid, hashid, msgfolder, msgflags)
        if msgid != '':
            self.eindex[self.ekey(msgid, msgfolder)] = dbid

    def get(self, dbid):
        msg = self.db[dbid]
        return (msg.id, msg.folder, msg.flags)

    def getHashId(self, dbid):
        return self.db[dbid].hashid

    def getIds(self):
        return set(self.db.keys())

    def getId(self, msgid, msgfolder):
        return self.eindex.get(self.ekey(msgid, msgfolder))

    def isEmpty(self):
        return len(self.db) == 0

    def exists(self, dbid):
        return dbid in self.db

    def clearStats(self):
        self.updated = False
        self.msgupdated = False

    def update(self, dbid, msgid, msgfolder, msgflags, hashid = None):
        if dbid in self.db:
            self.msgupdated = True
            msg = self.db[dbid]
            if msg.id != msgid or msg.folder != msgfolder:
                # remove a chave do índice se ela ainda estiver relacionada a esta mensagem
                if msg.id != '':
                    oldkey = self.ekey(msg.id, msg.folder)
                    if self.eindex[oldkey] == dbid:
                        del self.eindex[oldkey]
                # atualiza a mensagem e o índice
                msg.id = msgid
                msg.folder = msgfolder
                if msgid != '':
                    self.eindex[self.ekey(msgid, msgfolder)] = dbid
            if not hashid is None:
                msg.hashid = hashid
            msg.flags = msgflags
        else:
            if hashid is None:
                raise Exception('HashId is None.')
            self.updated = True
            self.add(dbid, msgid, hashid, msgfolder, msgflags)

    def folderIsEmpty(self, folder):
        for msg in self.db.values():
            if msg.folder == folder:
                return False
        return True

    def delete(self, dbid):
        msg = self.db[dbid]
        if msg.id != '':
            del self.eindex[self.ekey(msg.id, msg.folder)]
        del self.db[dbid]
        self.updated = True

    def wasModified(self):
        return self.updated or self.msgupdated

    def setUpdated(self):
        self.updated = True

    def saveSet(self, setToSave, dbfile):
        if setToSave is None:
            dbfile.write('0\n')
        else:
            dbfile.write(str(len(setToSave)))
            dbfile.write('\n')
            for item in setToSave:
                dbfile.write(item.encode('utf-8'))
                dbfile.write('\n')

    def save(self, dbfile):
        dbfile.write("6\n") # versão
        dbfile.write(self.signature.encode('utf-8'))
        dbfile.write('\n')
        # write folders
        self.saveSet(self.folders, dbfile)
        # write messages
        for dbid, msg in self.db.items():
            dbfile.write(dbid.encode('utf-8'))
            dbfile.write('\x00')
            dbfile.write(str(msg.id))
            dbfile.write('\x00')
            dbfile.write(msg.hashid)
            dbfile.write('\x00')
            dbfile.write(msg.folder.encode('utf-8'))
            dbfile.write('\x00')
            dbfile.write((' '.join(msg.flags)).encode('utf-8'))
            dbfile.write('\n')
        self.isNew = False

    def loadSet(self, dbfile):
        lset = set()
        count = int(dbfile.readline().strip())
        for _ in range(count):
            lset.add(dbfile.readline().strip().decode('utf-8'))
        return lset

    def parseFlags(self, sflags):
        return set(re.sub(r'[\(\)]', '', sflags).strip().split())

    def load(self, dbfile):
        line = dbfile.readline().strip()
        version = int(line)
        if version < 3 or version > 6:
            log( "DB-Version:", line )
            raise IExpressoError(_('Unsupported DB version.'))
        self.signature = dbfile.readline().strip()
        self.isNew = False
        #load folders
        if version >= 4:
            self.folders = self.loadSet(dbfile)
        #load messages
        line = dbfile.readline().strip()
        while line != '':
            parts = line.split('\x00')
            if version >= 5:
                self.add(parts[0].decode('utf-8'), parts[1], parts[2], parts[3].decode('utf-8'), self.parseFlags(parts[4].decode('utf-8')))
            else:
                self.add(parts[0].decode('utf-8'), parts[1], '', parts[2].decode('utf-8'), self.parseFlags(parts[4].decode('utf-8')))
            line = dbfile.readline().strip()


#########################################################
# MailSynchronizer
#########################################################
class MailSynchronizer():
    metadataFolder = 'INBOX/_metadata_dont_delete'
    relevantFlags = set([r'\Seen',r'\Answered',r'\Flagged',r'$Forwarded'])
    allflags = relevantFlags | set([r'\Deleted', r'\Draft'])
    removableFlags = set([r'\Seen',r'\Flagged'])

    def __init__(self):
        if not os.path.exists(iexpressodir):
            os.mkdir(iexpressodir)
        self.dbpath = os.path.join( iexpressodir, 'msg.db' )
        self.deleteHandler = self
        self.client = None
        self.curday = 0
        self.defaultFolders = frozenset(['INBOX', 'INBOX/Sent', 'INBOX/Trash', 'INBOX/Drafts'])
        self.staleMsgs = {}

    def loginLocal(self):
        try:
            if self.client != None and self.client.state in ('AUTH', 'SELECTED'):
                try:
                    self.logoutLocal()
                except:
                    logError()
            self.client = imaplib.IMAP4('localhost')
            self.client.login(self.user, self.password)
        except Exception, e:
            raise LoginError(_(u"Error connecting to local IMAP server: \n%s") % \
                                 ', '.join([str(i) for i in e.args]))

    def login(self, user, password):
        self.user = user
        self.password = password
        self.checkPreConditions()
        self.createExpressoManager()
        self.curday = 0
        self.loginLocal()
        self.db = self.loadDb()
        self.smartFolders = None

    def createExpressoManager(self):
        self.es = ExpressoManager(self.user, self.password)

    def close(self):
        log( 'Shutting down ...' )
        self.logoutLocal()

    def logoutLocal(self):
        if hasattr(self, 'client') and self.client != None:
            self.closeLocalFolder()
            self.client.logout()

    def getLocalFolders(self):
        (typ, imapFolders) = self.client.list('""', '*')
        checkImapError(typ, imapFolders)
        lst = set()
        for imapFolder in imapFolders:
            folder = getFolderPath(imapFolder)
            if not folder.startswith('INBOX'):
                continue
            if folder != self.metadataFolder:
                lst.add(folder)
        if len(lst) == 0 or not 'INBOX' in lst:
            raise IExpressoError(_('Error loading local folders.'))
        self.localFolders = lst
        return lst

    def checkPreConditions(self):
        maildir = '/home/' + self.user + '/Maildir'
        if os.path.exists(maildir):
            if not os.path.exists(self.dbpath):
                raise IExpressoError(_('You must recreate your local INBOX.'))
        elif os.path.exists(self.dbpath):
            raise IExpressoError(_('You must remove the file "%s".') % self.dbpath)

    def getQuotaStr(self):
        return _("%(quota)d%% of %(quotaLimit)dMB") % {"quota": self.es.quota, "quotaLimit": self.es.quotaLimit / (1024)}

    def syncFolders(self):
        self.getLocalFolders()
        # verifica se todas as pastas do expresso existem no imap local
        folders = self.es.listFolders()
        ordFolders = list(folders)
        ordFolders.sort() # ordena para que as pastas sejam criadas na ordem correta
        for folder_id in ordFolders:
            # não recria uma pasta excluída pelo usuário
            if not folder_id in self.db.folders:
                self.createLocalFolder(folder_id)
        self.db.folders = folders

    def iterParents(self, folder):
        '''Retorna todos os pais de uma pasta.'''
        parents = folder.split('/')
        if len(parents) == 1:
            yield folder # must be INBOX
            return
        folder = parents[0]
        for parent in parents[1:]:
            folder = folder + '/' + parent
            yield folder

    def createLocalFolder(self, newfolder):
        for folder in self.iterParents(newfolder):
            if not folder in self.localFolders:
                log( 'Creating folder', folder )
                (typ, data) = self.client.create( folder.encode('imap4-utf-7') )
                checkImapError(typ, data)
                self.client.subscribe( folder.encode('imap4-utf-7') )
                self.localFolders.add(folder)

    def getLocalSignature(self):
        typ, _ = self.client.select(self.metadataFolder, True)
        if typ != 'OK':
            return None
        typ, msg = self.client.fetch('1', '(BODY[HEADER.FIELDS (Message-Id)])')
        if typ != 'OK':
            return None
        return msg[0][1][len('Message-Id:'):].strip()

    def storeLocalSignature(self):
        log( "Storing DB signature ..." )
        (typ, data) = self.client.create( self.metadataFolder )
        checkImapError(typ, data)
        msg = MIMEText('Do not delete or move this message nor its folder.')
        msg['Subject'] = "Metadata Message - Don't Delete or Move"
        msg['From'] = 'iexpresso@localhost'
        msg['To'] = 'iexpresso@localhost'
        msg['Message-ID'] = self.db.signature
        self.client.append(self.metadataFolder, '(\\Seen)', None, msgToStr(msg))

    def saveDb(self):
        f = open(self.dbpath, 'w+b')
        try:
            self.db.save(f)
            #cPickle.dump(self.db, f, 2)
        finally:
            f.close()

    def loadDb(self):
        log( 'Loading DB...' )
        filename = self.dbpath
        if os.path.exists(filename):
            f = open(filename, 'r+b')
            try:
                db = MsgList()
                db.load(f)
                return db
                #return cPickle.load(f)
            finally:
                f.close()
        else:
            return MsgList()

    def unstale(self, dbid):
        self.staleMsgs.pop(dbid, '')

    def refreshSingleFolder(self, localdb, folder):
        edb = self.loadExpressoMessages('ALL', localdb, [folder])

        self.changeLocal(edb, localdb, doDelete=False)

        for dbid, dbfolder in self.staleMsgs.items():
            if dbfolder == folder:
                del self.staleMsgs[dbid]

    def loadLocalMsgs(self):
        self.closeLocalFolder()
        self.getLocalFolders()
        localdb = MsgList()
        localdb.folders = self.localFolders
        for folder in self.localFolders:
            for tryNum in range(2):
                self.client.select(folder.encode('imap4-utf-7'), True)
                typ, msgnums = self.client.search("US-ASCII", 'ALL') # o binc só aceita US-ASCII
                checkImapError(typ, msgnums)

                lenmsgs = len(msgnums[0].split())
                msgcount = 0
                if len(msgnums) > 0 and lenmsgs > 0:
                    typ, msgs = self.client.fetch( msgnums[0].replace(' ', ',') , '(FLAGS BODY[HEADER.FIELDS (Message-Id Sender)])')
                    checkImapError(typ, msgs)
                    for m in msgs:
                        if m != ')' and isinstance(m, tuple):
                            try:
                                localid = int(m[0][:m[0].index('(')])
                                flags = set(imaplib.ParseFlags(m[0]))
                                #extrai o dbid
                                headers = m[1]
                                mailmessage = MailMessage(headers)
                                dbid = self.getDbId(mailmessage)
                                if dbid == None or dbid == '':
                                    raise IExpressoError(_('Error loading local messages.'))

                                localdb.add(dbid, localid, '', folder, flags & self.allflags)
                                msgcount += 1
                            except:
                                log( m )
                                log( msgs )
                                raise
                    #for
                #if
                # verifica se todas as mensagens foram carregadas
                if lenmsgs == msgcount:
                    break
                elif tryNum == 0:
                    log( 'Not all messages loaded from %s. Trying again.' % folder )
                else:
                    raise IExpressoError(_('Error loading local messages.'))
        self.closeLocalFolder()
        localdb.clearStats()
        return localdb

    def getDbId(self, mailmessage, genId = False):
        msgid = mailmessage.getMessageId()
        if msgid != None and msgid != '':
            # o dbid leva em conta o MESSAGE-ID e o SENDER
            return msgid + mailmessage.getSender()
        else:
            if not genId:
                # se não houver um Message-Id retorna None
                return None
            # nunca deveria entrar aqui. Somente no caso da mensagem não ter MESSAGE-ID.
            # gera o Message-Id e coloca na mensagem
            log( " Generating fake MESSAGE-ID." )
            newid = '<%f_%d@localhost>' % (time.time(), random.randint(0,100000))
            mailmessage.setMessageId(newid)
            return newid + mailmessage.getSender()

    def loadExpressoMessages(self, criteria, localdb, folders):
        edb = MsgList()
        for folder_id in folders:
            log( 'Checking', folder_id )
            msgs = self.es.getMsgs(criteria, folder_id)
            todownload = []
            for msg in msgs:
                dbid = self.db.getId(msg.id, folder_id)
                if dbid != None:
                    hashid = self.db.getHashId(dbid)
                    # hashid == '' means "Imported and not synced"
                    if hashid != '' and hashid != msg.hashid:
                        #atualiza toda a pasta
                        log( "Re-downloading entire folder." )
                        todownload = list(msgs)
                        break
                    edb.update(dbid, msg.id, folder_id, msg.getFlags(), msg.hashid) #atualiza os dados da msg
                else:
                    todownload.append(msg)

            if len(todownload) > 0:
                newmsgs = self.es.getFullMsgs(folder_id, ','.join([str(msg.id) for msg in todownload]))
                if newmsgs == None:
                    #download falhou, faz o download de todas as mensagens pelo modo especial
                    newmsgs = {}
                # se nem todas as mensagens foram retornadas faz o download especial
                if len(newmsgs) != len(todownload):
                    # mensagens com caracteres especiais devem ser importadas individualmente
                    for msg in todownload:
                        if not msg.id in newmsgs:
                            log( 'Getting message using alternative way:', msg.id )
                            msgsrc = self.es.getFullMsgEspecial(folder_id, msg.id)
                            if not msgsrc is None:
                                newmsgs[msg.id] = msgsrc

                #importa as mensagens no banco
                for msg in todownload:
                    if msg.id in newmsgs:
                        eflags = msg.getFlags()
                        mailmessage = MailMessage( newmsgs[msg.id] )
                        dbid = self.getDbId(mailmessage, True)
                        strflags = '(' + ' '.join(eflags) + ')'
                        log( '  ', msg.id, strflags, dbid ) #fullmsg['Subject'] )
                        if not self.db.exists(dbid):
                            if not localdb.exists(dbid):
                                self.createLocalFolder(folder_id)
                                mailmessage.fixSubjectBrokenWord()
                                typ, resp = self.client.append(folder_id.encode('imap4-utf-7'), strflags, None, mailmessage.msgsrc)
                                checkImapError(typ, resp)
                                # insert a dummy record that can't be used to update local imap
                                localdb.setUpdated()
                            self.db.update(dbid, msg.id, folder_id, eflags & self.relevantFlags, msg.hashid)
                            self.unstale(dbid)
                        edb.update(dbid, msg.id, folder_id, eflags, msg.hashid)
                #re-verifica se todas as mensagens foram baixadas
                if len(newmsgs) != len(todownload):
                    raise Exception(_('Error loading messages from Expresso.'))
        return edb

    def checkSignature(self, localdb):
        sig = self.getLocalSignature()
        if sig != self.db.signature:
            if sig == None and localdb.isEmpty() and self.db.isNew:
                self.storeLocalSignature()
            else:
                raise IExpressoError(_('DB and INBOX signatures does not match.'))

    def loadAllMsgs(self):
        compressLog()
        log( '* Full refresh -', time.asctime() )
        try:
            self.createExpressoManager() # full refresh does a relogin to avoid problems with dirty sessions
            localdb = self.initUpdate()

            try:
                edb = self.loadExpressoMessages('ALL', localdb, self.db.folders)

                # get local new and changed messages
                localdb = self.loadLocalMsgs()

                #remove as mensagens que não estão mais na caixa do expresso da caixa local
                self.changeLocal(edb, localdb)

                if localdb.wasModified():
                    localdb = self.loadLocalMsgs()

                self.staleMsgs.clear()

                #move, deleta e atualiza as mensagens no expresso
                self.changeExpresso(localdb, doMove = True, doDelete = True, doImport = True)

                self.checkDeletedFolders()
            finally:
                self.saveDb()
                self.closeLocalFolder()

            self.es.updateQuota() # para atualizar a quota
            self.db.clearStats()

        except:
            logError()
            raise
        log( 'OK' )

    def initUpdate(self):

        if not self.es.logged:
            self.es.doLogin()

        try:
            localdb = self.loadLocalMsgs()
        except:
            logError()
            # Reconecta e tenta novamente
            log("Reconnecting to local imap ...")
            self.loginLocal()
            localdb = self.loadLocalMsgs()

        self.checkSignature(localdb)

        day = datetime.date.today().toordinal() # o número de dias desde 1-1-1

        if day != self.curday: # verifica se o dia mudou desde a última iteração
            self.syncFolders()
            self.es.autoClean() # remove da lixeira as mensagens mais antigas.
            self.curday = day

        return localdb

    def loadUnseen(self):
        log( '* Smart refresh -', time.asctime() )
        # somente mensagens não lidas são carregadas
        try:
            if self.smartFolders == None:
                self.smartFolders = self.es.getFoldersWithRules() # somente as pastas com regras são atualizadas

            localdb = self.initUpdate()
            try:
                self.changeExpresso(localdb, doDelete=True) #seta os flags e exclui mensagens no expresso

                self.loadExpressoMessages('UNSEEN', localdb, self.smartFolders)

                if self.db.updated:
                    self.es.updateQuota()

            finally:
                if self.db.wasModified():
                    self.saveDb()
                self.closeLocalFolder()

            self.db.clearStats()
        except:
            logError()
            raise
        log( 'OK' )

    def closeLocalFolder(self):
        if self.client.state == 'SELECTED':
            self.client.close()

    def changeLocal(self, edb, localdb, doDelete = True):
        #seleciona as mensagens a serem excluídas
        folders_expunge = {}
        def deleteAfter(localfolder, localid):
            if localfolder in folders_expunge:
                folders_expunge[localfolder].append(localid)
            else:
                folders_expunge[localfolder] = [localid]

        curids = edb.getIds()

        for dbid in self.db.getIds():
            if not dbid in curids:
                if not doDelete:
                    continue
                #exclui do imap local
                if localdb.exists(dbid):
                    localid, localfolder = localdb.get(dbid)[0:2]
                    log( 'Deleting from local %s dbid %d' % (localfolder, localid) )
                    deleteAfter(localfolder, localid)
                    localdb.delete(dbid)

                self.db.delete(dbid)
                self.unstale(dbid)
            else:
                eid, efolder, eflags = edb.get(dbid)
                hashid = edb.getHashId(dbid)
                if not localdb.exists(dbid):
                    # atualiza o banco
                    self.db.update(dbid, eid, efolder, eflags & self.relevantFlags, hashid)
                    self.unstale(dbid)
                    continue # deve ser uma mensagem excluída localmente

                localid, localfolder, localflags = localdb.get(dbid)
                dbfolder, dbflags = self.db.get(dbid)[1:3]
                if eflags != dbflags and eflags != localflags:
                    diff = FlagsDiff(eflags, dbflags, self.relevantFlags, self.removableFlags)
                    if not diff.isEmpty():
                        self.client.select(localfolder.encode('imap4-utf-7'), False)
                        # NOTE: forwarded não pode ser representando no bincimap (sem as alterações realizadas por mim)
                        log( 'Update local flag. Id: %d   folder: %s   +flags: %s  -flags: %s  localflags: %s'
                                % (localid, localfolder, ' '.join(diff.added), ' '.join(diff.removed), ' '.join(localflags)) )
                        if len(diff.removed) > 0:
                            self.client.store(str(localid), '-FLAGS', ' '.join(diff.removed))
                        if len(diff.added) > 0:
                            self.client.store(str(localid), '+FLAGS', ' '.join(diff.added))
                        localdb.setUpdated()
                        self.closeLocalFolder()
                if efolder != dbfolder and efolder != localfolder:
                    # move a mensagens localmente
                    log( 'Moving local message id: %d  folder: %s  new_folder: %s' % (localid, localfolder.encode('utf-8'), efolder.encode('utf-8')) )
                    self.createLocalFolder(efolder)
                    deleteAfter(localfolder, localid)
                    self.client.select(localfolder.encode('imap4-utf-7'), True)
                    self.client.copy(str(localid), efolder.encode('imap4-utf-7'))
                    localdb.setUpdated()
                # atualiza o banco
                self.db.update(dbid, eid, efolder, eflags & self.relevantFlags, hashid)
                self.unstale(dbid)

        # exclui as mensagens e faz expunge da pasta
        for folder in folders_expunge.keys():
            self.client.select(folder.encode('imap4-utf-7'), False)
            for localid in folders_expunge[folder]:
                self.client.store(str(localid), '+FLAGS', '\\Deleted')
            self.client.expunge()
            self.closeLocalFolder()

    def checkDeletedFolders(self):
        """Remove pastas do expresso que foram excluídas localmente."""
        orderedFolders = list(self.db.folders)
        # ordena para verificar primeiro as subpastas
        orderedFolders.sort(reverse=True)
        for efolder in orderedFolders:
            if not efolder in self.localFolders:
                if not efolder in self.defaultFolders:
                    isEmpty = self.db.folderIsEmpty(efolder)
                    if isEmpty:
                        # verifica se as pastas filhas desta foram removidas
                        prefix = efolder + '/'
                        for f in self.db.folders:
                            if f.startswith(prefix):
                                isEmpty = False
                                break
                        if isEmpty:
                            # re-verifica se não há mensagens no servidor dentro dessa pasta
                            msgs = self.es.getMsgs('ALL', efolder)
                            isEmpty = len(msgs) == 0
                    if isEmpty:
                        log( "Removing folder from expresso:", efolder )
                        self.es.deleteFolder(efolder)
                        self.db.folders.remove(efolder)
                    else:
                        log( "Expresso folder '%s' has messages. Not removing." )
                else:
                    self.createLocalFolder(efolder)

    def importMsgExpresso(self, folder, localid, localflags, dbid):
        log( 'Importing id: %d to folder: %s  dbid: %s' % (localid, folder, dbid) )

        self.client.select(folder.encode('imap4-utf-7'), True)
        msgsrc = self.client.fetch(str(localid), '(RFC822.HEADER RFC822.TEXT)')
        if msgsrc[0] == 'OK' and len(msgsrc[1]) >= 2:

            msgheader = msgsrc[1][0][1]
            msgbody = msgsrc[1][1][1]

            self.createFolderExpresso(folder)
            mailmessage = MailMessage(msgheader)
            date = mailmessage.getMessageDateAsInt()
            if date is None:
                log('Importing message without date info.')
                date = time.mktime(time.localtime())

            flagset = set(localflags)
            if not '\\Seen' in flagset:
                flagset.add('\\Unseen')
            self.es.importMsgWithTime(folder, msgheader + msgbody, date, flagset)

            self.staleMsgs[dbid] = folder
            self.db.update(dbid, '', folder, localflags & self.relevantFlags, '')

        self.closeLocalFolder()

    def askDeleteMessages(self, todelete):
        """ Default method handler used to ask the user before delete messages. Must return True or False to continue or not. """
        return True

    def deleteFromExpresso(self, localdb, todelete):
        if len(todelete) > 0:
            self.checkSignature(localdb)
            skipExpresso = self.deleteHandler != None and not self.deleteHandler.askDeleteMessages(todelete)
            if skipExpresso:
                log("Messages deletion canceled by user action.")
            # se o usuário cancelar a operação, deleta do banco para que as mensagens sejam restauradas dá próxima vez
            for folder in todelete.keys():
                if not skipExpresso:
                    # cuidado! irá excluir permanentemente as mensagens
                    # quando eid == '' deve ser um import que falhou. Então a mensagem não está no Expresso.
                    strids = ','.join([str(item.eid) for item in todelete[folder] if item.eid != ''])
                    log( 'Deleting messages from Expresso. Ids: %s   folder: %s' % (strids, folder) )
                    self.es.deleteMsgs(strids, folder)
                # atualiza o banco, se skipExpresso for True as mensagens serão recarregadas
                # da próxima vez que houver full refresh
                for item in todelete[folder]:
                    self.db.delete(item.dbid)

    def flagMessagesExpresso(self, toflag, newflags):
        # envia os comandos para alterar os flags no expresso
        for folder, flags in toflag.items():
            for flag, msgs in flags.items():
                if len(msgs) > 0:
                    strids = ','.join([str(eid) for eid in msgs])
                    log( 'Updating flags ids: %s  flag: %s  folder: %s' % (strids, flag, folder) )
                    self.es.setMsgFlag(folder, strids, flag)
                    for eid in msgs:
                        dbid = self.db.getId(eid, folder)
                        if dbid != None and dbid in newflags:
                            self.db.update(dbid, eid, folder, newflags[dbid] & self.relevantFlags) # atualiza o banco
                        else:
                            log("Message not found:", eid, folder, dbid, ' '.join(newflags))

    def createFolderExpresso(self, newfolder):
        for folder in self.iterParents(newfolder):
            if not folder in self.db.folders:
                log( "Creating folder on Expresso:", folder )
                self.es.createFolder(folder) #cria a pasta no expresso
                self.db.folders.add(folder)

    class ExMsgItem:
        def __init__(self, dbid, eid):
            self.dbid = dbid
            self.eid = eid

    def moveMessagesExpresso(self, tomove):
        # move as mensagens
        for (efolder, newfolder), items in tomove.items():
            strids = ','.join([str(item.eid) for item in items])
            log( 'Moving ids: %s   folder: %s   newfolder: %s' % (strids, efolder, newfolder) )
            self.createFolderExpresso(newfolder)
            self.es.moveMsgs(strids, efolder, newfolder)
            for item in items:
                self.staleMsgs[item.dbid] = newfolder

    def safeFolderId(self, localdb, dbid):
        if dbid in self.staleMsgs:
            self.refreshSingleFolder(localdb, self.staleMsgs[dbid])
        return self.db.get(dbid)[0:2]

    def changeExpresso(self, localdb, doImport = False, doMove = False, doDelete = False):
        for _ in range(2):
            localdb.clearStats()
            diff = self.computeExpressoDiff(localdb, doImport, doMove, doDelete)
            if not localdb.wasModified():
                break
            else:
                localdb = self.loadLocalMsgs()

        self.deleteFromExpresso(localdb, diff.todelete)

        self.flagMessagesExpresso(diff.toflag, diff.newflags)

        self.moveMessagesExpresso(diff.tomove)

        for dbid in diff.toimport:
            msgid, msgfolder, msgflags = localdb.get(dbid)
            self.importMsgExpresso(msgfolder, msgid, msgflags, dbid)

    class ExpressoDiff:
        def __init__(self):
            self.todelete = {}
            self.toflag = {}
            self.tomove = {}
            self.newflags = {}
            self.toimport = []

        def move(self, dbid, efolder, newfolder, eid):
            pair = (efolder, newfolder)
            if pair in self.tomove:
                self.tomove[pair].append(MailSynchronizer.ExMsgItem(dbid, eid))
            else:
                self.tomove[pair] = [MailSynchronizer.ExMsgItem(dbid, eid)]

        def delete(self, dbid, efolder, eid):
            if efolder in self.todelete:
                self.todelete[efolder].append(MailSynchronizer.ExMsgItem(dbid, eid))
            else:
                self.todelete[efolder] = [MailSynchronizer.ExMsgItem(dbid, eid)]

    def computeExpressoDiff(self, localdb, doImport = False, doMove = False, doDelete = False):
        exdiff = self.ExpressoDiff()

        if doDelete:
            #verifica as mensagens que não existem mais na caixa local
            for dbid in self.db.getIds():
                if not localdb.exists(dbid):
                    eid, efolder = self.safeFolderId(localdb, dbid)
                    # por motivos de segurança só deveria excluir da lixeira,
                    # após algum tempo de teste essa restrição foi removida
                    exdiff.delete(dbid, efolder, eid)
                    #else:
                    #    exdiff.move(efolder, 'INBOX/Trash', dbid, eid) #move pra lixeira quando estiver excluída

        for dbid in localdb.getIds():
            _, localfolder, localflags = localdb.get(dbid)
            eid = ''
            if self.db.exists(dbid):
                eid, efolder, eflags = self.db.get(dbid)
            # eid equals to '' when the import failed or its a new message
            if eid != '':
                #move as mensagens que foram movidas
                if doMove and localfolder != efolder:
                    eid, efolder = self.safeFolderId(localdb, dbid)
                    exdiff.move(dbid, efolder, localfolder, eid)

                #altera os flags das mensagens lidas e respondidas
                if localflags != eflags:
                    fdiff = FlagsDiff(localflags, eflags, self.relevantFlags, self.removableFlags)
                    if not fdiff.isEmpty():
                        eid, efolder = self.safeFolderId(localdb, dbid)
                        exdiff.newflags[dbid] = self.mapFlagsExpresso(exdiff.toflag, eid, efolder, eflags, fdiff)
            elif doImport:
                if not (r'\Deleted' in localflags) and not localfolder.endswith('/Trash'):
                    exdiff.toimport.append(dbid)

        return exdiff

    def mapFlagsExpresso(self, toflag, eid, efolder, eflags, diff):
        newflags = (eflags - diff.removed) | diff.added
        if efolder in toflag:
            flags = toflag[efolder]
        else:
            flags = {'seen': [], 'unseen': [], 'answered': [], 'forwarded': [], 'flagged': [], 'unflagged': []}
            toflag[efolder] = flags

        for flag in diff.added:
            flags[flag[1:].lower()].append(eid)
        for flag in diff.removed:
            flags['un' + flag[1:].lower()].append(eid)

        return newflags

class FlagsDiff:
    def __init__(self, flags1, flags2, insertable, removable):
        self.removed = (flags2 & removable) - flags1
        self.added = (flags1 & insertable) - flags2
    
    def isEmpty(self):
        return len(self.added) == 0 and len(self.removed) == 0

def getFolderPath(imapfolder):
    p1 = imapfolder.rindex('"', 0)
    p2 = imapfolder.rindex('"', 0, p1-1)
    return imapfolder[p2 + 1:p1].decode('imap4-utf-7') # codec definido em imap4utf7

if __name__ == "__main__":
    import getpass

    def _(s):
        return s

    if not os.path.exists(iexpressodir):
        os.mkdir(iexpressodir)

    try:
        sync = MailSynchronizer()
        try:
            sync.login(getpass.getuser(), getpass.getpass())
            refreshcount = 0
            while True:
                if (refreshcount % 20) == 0: # a cada 20 iterações faz um full refresh
                    sync.loadAllMsgs()
                else:
                    sync.loadUnseen()
                refreshcount += 1
                time.sleep(210) # 3 minutos e meio (210 segundos)
        finally:
            sync.close()
    except KeyboardInterrupt:
        pass
    except IExpressoError, e:
        log( "*** Error:", str(e) )
