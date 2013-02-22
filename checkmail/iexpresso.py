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
import simplejson as json
from cStringIO import StringIO

from email.mime.text import MIMEText
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

###########################################################
# Faz o parse da resposta do expresso.
# Formato:
#   json
#   Saída: dicionário com os valores
def unserialize(text):
    class JSONObj:
        def __init__(self, entries):
            self.__dict__.update(entries)

    return json.loads(text.decode('utf-8'), object_hook=lambda x: JSONObj(x))

def json_default(obj):
    if isinstance(obj, set):
        return list(obj)
    return obj


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

def joinstr(lst):
    return ','.join([str(i) for i in lst])

def replaceinset(_set, find, rep):
    if find in _set:
        _set.remove(find)
        _set.add(rep)
    return _set

class IExpressoError(Exception):
    pass

class RemoteError(Exception):
    def __init__(self, msg, code):
        Exception.__init__(self, msg)
        self.code = code

class SessionExpiredError(IExpressoError):
    def __init__(self):
        IExpressoError.__init__(self, _(u"Session Expired."))

class LoginError(IExpressoError):
    '''
    Exception thrown upon login failures.
    '''
    pass

class ExpressoManager:
    urlExpresso = 'https://expressov3.serpro.gov.br'
    urlIndex = urlExpresso + '/index.php'
    urlLogin = urlIndex
    urlUpload = urlIndex + '?method=Tinebase.uploadTempFile'

    def __init__(self, user, passwd):
        # Os campos do formulário
        self.user = user
        self.passwd = passwd
        self._reset()
        self.callExpresso = self._reconnectDecor(self._callExpresso)
        self.importMsg = self._reconnectDecor(self.importMsg)
        self.getFullMsgs = self._reconnectDecor(self.getFullMsgs)
        self.reconnectDecorCount = 0

    def _reset(self):
        """ Limpa os atributos da conexão. Este método também é chamado durante o logout. """
        self.callid = 0
        self.logged = False
        self.jsonKey = ''

        #Inicialização
        self.cookies = cookielib.CookieJar() #cookies são necessários para a autenticação
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookies), MultipartPostHandler )
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.81 Safari/537.1'),
                                  ('Origin', self.urlExpresso), ('Referer', self.urlExpresso)]

    def _getCookie(self, name):
        for cookie in self.cookies:
            if cookie.name == name:
                return cookie.value
        return None

    def _reconnectDecor(self, func, *args, **kwargs):
        def call(*args, **kwargs):
            self.reconnectDecorCount += 1
            try:
                return func(*args, **kwargs)
            except SessionExpiredError:
                if self.reconnectDecorCount > 1:
                    raise
                log( "Session expired. Reconnecting..." )
                self.login()
                return func(*args, **kwargs)
            finally:
                self.reconnectDecorCount -= 1
        return call

    def _hasUserCookie(self):
        return self._getCookie('usercredentialcache') != None

    def openUrl(self, surl, params, post):
        if params != None and not post:
            if not surl.endswith('&'):
                surl += '&'
            surl += urllib.urlencode(params, True)
            params = None
        #log( surl )
        sessionid = self._getCookie("TINE20SESSID")
        response = self.opener.open(surl, params)
        # reconnects when the session id changes
        if self.logged and sessionid != self._getCookie("TINE20SESSID"):
            self.logged = False
            raise SessionExpiredError()
        return response

    def _checkRemoteError(self, ret):
        if hasattr(ret, "error"):
            log("* Error:", ret.error.message)
            errcode = None
            if ret.error.data != None:
                errcode = ret.error.data.code

                if errcode == 401: # Not Authorised
                    raise SessionExpiredError()

                log(' Code:', ret.error.data.code)
                for trace in ret.error.data.trace:
                    if hasattr(trace, "file"):
                        log(' ', trace.file, trace.line, trace.function)
            raise RemoteError(ret.error.message, errcode)

    def _callExpresso(self, method, *params):
        self.callid += 1
        obj = {'jsonrpc': '2.0', 'method': method, 'id': self.callid, 'params': params}
        headers = {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                   'X-Tine20-JsonKey': self.jsonKey, 'X-Tine20-Request-Type': 'JSON'}
        req = urllib2.Request(self.urlIndex, json.dumps(obj, sort_keys=False, default=json_default), headers=headers)
        if not 'login' in method:
            print method, params
        response = self.openUrl(req, None, True)
        ret = unserialize(response.read())
        response.close()
        self._checkRemoteError(ret)
        return ret.result

    def login(self):
        success = False
        try:
            self._reset()
            response = self.opener.open(self.urlExpresso)
            response.read()
            response.close()
            # login($username, $password, $securitycode=NULL)
            ret = self.callExpresso('Tinebase.login', self.user, self.passwd, '')
            success = ret.success
            if success:
                self.jsonKey = ret.jsonKey
                self.userAccount = ret.account
                ret = self.callExpresso("Felamimail.getRegistryData");
                self.account = ret.accounts.results[0]
                self.supportedFlags = set([flag.id for flag in ret.supportedFlags.results])
        except Exception as e:
            raise LoginError(_(u"It was not possible to connect at Expresso.") + " " + _(u"Error:") + "\n\n" + unicode(e))
        finally:
            self.logged = success
        if not self.logged:
            raise LoginError(_(u"It was not possible to connect at Expresso.") + " " + _(u"Check your password."))

    def logout(self):
        try:
            if self.logged and self._hasUserCookie():
                self._callExpresso("Tinebase.logout") # ignores the reconnect decorator
        except SessionExpiredError:
            pass
        except Exception as e:
            log( u"Logout failed:", unicode(e) )
        finally:
            self._reset()

    def listFolders(self):
        self.foldermap = {}
        self._listFoldersRec("")
        return self.foldermap.keys()

    def _initFolderMap(self):
        if not hasattr(self, "foldermap"):
            self.listFolders()

    def _callSearchFolders(self, parent):
        # searchFolders($filter)
        return self.callExpresso("Felamimail.searchFolders", [{"field":"account_id", "operator":"equals", "value":self.account.id},
                                                              {"field":"globalname", "operator":"equals", "value":parent}])

    def _listFoldersRec(self, parent):
        try:
            ret = self._callSearchFolders(parent)
        except RemoteError as e:
            if u'cannot change folder' in unicode(e):
                log( u"Error listing folders. Reconnecting... " )
                self.logout()
                time.sleep(10) # waits 10 seconds
                self.login()
                ret = self._callSearchFolders(parent)
            else:
                raise
        for folder in ret.results:
            self.foldermap[folder.globalname] = folder
            if folder.has_children:
                self._listFoldersRec(folder.globalname)

    def createFolder(self, path):
        self._initFolderMap()
        parts = path.split('/')
        # addFolder($name, $parent, $accountId)
        newfolder = self.callExpresso("Felamimail.addFolder", parts[-1], "/".join(parts[:-1]), self.account.id)
        self.foldermap[newfolder.globalname] = newfolder

    def deleteFolder(self, path):
        """ Cuidado! Exclui também as mensagens que estão dentro da pasta """
        # deleteFolder($folder, $accountId)
        self.callExpresso("Felamimail.deleteFolder", path, self.account.id)

    def getFullMsgs(self, msgsid):
        # downloadMessage($messageId)
        response = self.openUrl(self.urlIndex, {"method": "Felamimail.downloadMessage", "requestType": "HTTP",
                                           "messageId": joinstr(msgsid)}, True)
        filename = response.info()['Content-Disposition'].split("=")[1].strip('"')

        msgs = {}

        if filename.lower().endswith('.eml'):
            source = response.read()
            if "From:" in source:
                msgs[filename[: -4]] = source
            return msgs

        try:
            zfile = zipfile.ZipFile(StringIO(response.read()))
            for name in zfile.namelist():
                # formato do nome ID.eml, extraí o ID do nome do arquivo
                source = str(zfile.read(name)) # a codificação das mensagens é ASCII
                if not "From:" in source:
                    continue # mensagem inválida
                msgs[name[: -4]] = source
            zfile.close()
        except zipfile.BadZipfile:
            log( "Error downloading full messages." )
            return None
        finally:
            response.close()
        return msgs

    def importMsg(self, msgfolder, source):
        """ A mensagem é importada para a pasta especificada e entra como lida. """
        self._initFolderMap()
        headers = {'X-File-Name': "email.eml", 'X-File-Size': len(source), 'X-File-Type': 'message/rfc822',
                   'X-Requested-With': 'XMLHttpRequest', 'X-Tine20-Request-Type': 'HTTP'}
        req = urllib2.Request(self.urlUpload, source, headers=headers)
        response = self.openUrl(req, None, True)
        ret = unserialize(response.read())
        # verifica se aconteceu algum erro
        if ret.status != 'success':
            log(ret.__dict__)
            raise Exception(_("Import failed."))
        # importMessage($accountId,$folderId, $file)
        ret = self.callExpresso("Felamimail.importMessage", self.account.id, self.foldermap[msgfolder].id, ret.tempFile.path)

    def _makeExpressoFlags(self, flags):
        return replaceinset(set(flags), '$Forwarded', 'Passed') & self.supportedFlags

    def addFlags(self, msgids, flags):
        flags = self._makeExpressoFlags(flags)
        if len(flags) > 0:
            # addFlags($filterData, $flags)
            self.callExpresso("Felamimail.addFlags", [{"field":"id", "operator":"in", "value": msgids}], flags)

    def clearFlags(self, msgids, flags):
        flags = self._makeExpressoFlags(flags)
        if len(flags) > 0:
            # clearFlags($filterData, $flags)
            self.callExpresso("Felamimail.clearFlags", [{"field":"id", "operator":"in", "value": msgids}], flags)

    def calcHashId(self, msg):
        m = hashlib.md5()
        m.update(msg.content_type.encode('utf-8') + '@')
        m.update(msg.sent.encode('utf-8') + '@')
        m.update(msg.from_email.encode('utf-8') + '@')
        for item in msg.to:
            m.update(item.encode('utf-8') + '@')
        m.update(msg.subject.encode('utf-8') + '@')
        m.update(str(msg.size))
        return m.hexdigest()

    def getMsgs(self, criteria, folder):
        """ Por motivos de compatibilidade o atributo criteria deve estar entre: "ALL", "UNSEEN".
        """
        self._initFolderMap()
        filterParam = [{"field":"path", "operator":"in", "value": ["/{0}/{1}".format(self.account.id, self.foldermap[folder].id)]}]
        if criteria == 'UNSEEN':
            filterParam.append({"field":"flags", "operator":"notin", "value":["\\Seen"]})
        msgs = []
        limit = 1000
        start = 0
        while True:
            # searchMessages($filter, $paging)
            ret = self.callExpresso("Felamimail.searchMessages", filterParam, {"sort":"received", "dir":"DESC", "start":start, "limit":limit})

            for msg in ret.results:
                msg.flags = replaceinset(set(msg.flags), 'Passed', '$Forwarded')
                msg.hashid = self.calcHashId(msg)
                msgs.append(msg)

            if len(ret.results) < limit:
                break
            start += limit

        return msgs

    @property
    def quotaLimit(self):
        self._initFolderMap()
        # KBytes
        return int(self.foldermap['INBOX'].quota_limit, 10)

    @property
    def quota(self):
        """ Returns quota usage in percentage. """
        self._initFolderMap()
        return int(100 * int(self.foldermap['INBOX'].quota_usage, 10) / self.quotaLimit)

    def updateQuota(self):
        self._initFolderMap()
        # updateMessageCache($folderId, $time)
        self.foldermap['INBOX'] = self.callExpresso("Felamimail.updateMessageCache", self.foldermap['INBOX'].id, 180)

    def moveMsgs(self, msgids, newfolder):
        self._initFolderMap()
        # moveMessages($filterData, $targetFolderId)
        folders = self.callExpresso("Felamimail.moveMessages", [{"field":"id", "operator":"in", "value": msgids}], self.foldermap[newfolder].id)
        for folder in folders:
            self.foldermap[folder.globalname] = folder

    def deleteMsgs(self, msgids):
        """Cuidado! Exclui permanentente as mensagens."""
        self.addFlags(msgids, ["\\Deleted"])

    def autoClean(self):
        # deleteMsgsBeforeDate($accountId)
        ret = self.callExpresso("Felamimail.deleteMsgsBeforeDate", self.account.id)
        log( "AutoClean response:", ret.msgs )


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
    relevantFlags = set([r'\Seen',r'\Answered',r'\Flagged',r'$Forwarded',r'\Draft'])
    allflags = relevantFlags | set([r'\Deleted'])
    removableFlags = set([r'\Seen',r'\Flagged',r'\Draft'])

    def __init__(self):
        if not os.path.exists(iexpressodir):
            os.mkdir(iexpressodir)
        self.dbpath = os.path.join( iexpressodir, 'msg.db' )
        self.deleteHandler = self
        self.client = None
        self.curday = 0
        self.es = None
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
        except Exception as e:
            raise LoginError(_(u"Error connecting to local IMAP server: \n%s") % \
                                 ', '.join([str(i) for i in e.args]))

    def login(self, user, password):
        self.user = user
        self.password = password
        self.checkPreConditions()
        self.resetExpressoManager()
        self.curday = 0
        self.loginLocal()
        self.db = self.loadDb()
        self.smartFolders = None

    def resetExpressoManager(self):
        if self.es != None:
            self.es.logout()
        else:
            self.es = ExpressoManager(self.user, self.password)

    def close(self):
        log( 'Shutting down ...' )
        self.logoutLocal()
        if self.es != None:
            self.es.logout()

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
        folders = set(self.es.listFolders())
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
                    edb.update(dbid, msg.id, folder_id, msg.flags, msg.hashid) #atualiza os dados da msg
                else:
                    todownload.append(msg)

            if len(todownload) > 0:
                newmsgs = self.es.getFullMsgs([msg.id for msg in todownload])

                #importa as mensagens no banco
                for msg in todownload:
                    if msg.id in newmsgs:
                        eflags = msg.flags
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
            self.resetExpressoManager() # full refresh does a relogin to avoid problems with dirty sessions
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
            self.es.login()

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
                self.smartFolders = ['INBOX'] # somente as pastas com regras são atualizadas

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

            self.es.importMsg(folder, msgheader + msgbody)

            self.staleMsgs[dbid] = folder
            self.db.update(dbid, '', folder, set(['\\Seen']), '')

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
                    ids = [item.eid for item in todelete[folder] if item.eid != '']
                    log( 'Deleting messages from Expresso. Ids: %s   folder: %s' % (joinstr(ids), folder) )
                    self.es.deleteMsgs(ids)
                # atualiza o banco, se skipExpresso for True as mensagens serão recarregadas
                # da próxima vez que houver full refresh
                for item in todelete[folder]:
                    self.db.delete(item.dbid)

    def flagMessagesExpresso(self, toflag, newflags):
        # envia os comandos para alterar os flags no expresso
        for (flag, add), msgs in toflag.items():
            if len(msgs) > 0:
                ids = [i[0] for i in msgs]
                log( 'Updating flags ids: %s  flag: %s  add: %s' % (joinstr(ids), flag, str(add)) )
                if add:
                    self.es.addFlags(ids, [flag])
                else:
                    self.es.clearFlags(ids, [flag])
                for eid, efolder in msgs:
                    dbid = self.db.getId(eid, efolder)
                    if dbid != None and dbid in newflags:
                        self.db.update(dbid, eid, efolder, newflags[dbid] & self.relevantFlags) # atualiza o banco
                    else:
                        log("Message not found:", eid, efolder, dbid, ' '.join(newflags))

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
            ids = [item.eid for item in items]
            log( 'Moving ids: %s   folder: %s   newfolder: %s' % (joinstr(ids), efolder, newfolder) )
            self.createFolderExpresso(newfolder)
            self.es.moveMsgs(ids, newfolder)
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

        for flag in diff.added:
            toflag.setdefault((flag, True), []).append((eid, efolder))
        for flag in diff.removed:
            toflag.setdefault((flag, False), []).append((eid, efolder))

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
    except IExpressoError as e:
        log( "*** Error:", str(e) )
