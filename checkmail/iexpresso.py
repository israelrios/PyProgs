#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 17-nov-2009

import imap4utf7 # pro codec imap4-utf-7

from monutil import decode_header

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

import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import email.utils
import email.header
from email.generator import Generator as EmailGenerator

import imaplib

import mimetypes
import mimetools

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

class IExpressoError(Exception):
    pass

class LoginError(IExpressoError):
    '''
    Exception thrown upon login failures.
    '''
    pass

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


class NamedStringIO(pyStringIO):
    def __init__(self, name, buffer = None):
        self.name = name
        pyStringIO.__init__(self, buffer)

# Controls how sequences are encoded. If true, elements may be given multiple values by
#  assigning a sequence.
doseq = 1

##########################################################
# Peguei na NET esta classe para codificar os campos
# do formulário no formato multipart/form-data
class MultipartPostHandler(urllib2.BaseHandler):
    handler_order = urllib2.HTTPHandler.handler_order - 10 # needs to run first

    def http_request(self, request):
        data = request.get_data()
        if data is not None and type(data) != str:
            v_files = []
            v_vars = []
            try:
                 for(key, value) in data.items():
                     if hasattr(value, 'read'):
                         v_files.append((key, value))
                     else:
                         v_vars.append((key, value))
            except TypeError, e:
                raise TypeError("not a valid non-string sequence or mapping object: " + str(e))

            if len(v_files) == 0:
                data = urllib.urlencode(v_vars, doseq)
            else:
                boundary, data = self.multipart_encode(v_vars, v_files)
                contenttype = 'multipart/form-data; boundary=%s' % boundary
                if request.has_header('Content-Type') and request.get_header('Content-Type').find('multipart/form-data') != 0:
                    log( "Replacing %s with %s" % (request.get_header('content-type'), 'multipart/form-data') )
                request.add_unredirected_header('Content-Type', contenttype)

            request.add_data(data)
        return request

    def multipart_encode(self, vars, files, boundary = None, buffer = None):
        if boundary is None:
            boundary = mimetools.choose_boundary()
        if buffer is None:
            buffer = ''
        for(key, value) in vars:
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; name="%s"' % key
            buffer += '\r\n\r\n' + str(value) + '\r\n'
        for(key, fd) in files:
            fd.seek(0, os.SEEK_END)
            file_size = fd.tell()
            filename = os.path.basename(fd.name)
            contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (key, filename)
            buffer += 'Content-Type: %s\r\n' % contenttype
            buffer += 'Content-Length: %s\r\n' % file_size
            fd.seek(0, os.SEEK_SET)
            buffer += '\r\n' + fd.read() + '\r\n'
        buffer += '--%s--\r\n\r\n' % boundary
        return boundary, buffer

    https_request = http_request
# end


# expresso msg fields:
# ContentType: string
# aux_date: string(dd/mm/yyyy)
# msg_number: number
# Importance: flag
# msg_sample: dict {body : string}
# udate: string
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
            else:
                self.date = datetime.datetime.strptime(values['aux_date'], '%d/%m/%Y')
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
                person = values['from']
                self.sfrom = '%s <%s>' % (email.utils.quote(decode_htmlentities(person['name'])), person['email'])
            else:
                self.sfrom = ''
            if 'toaddress2' in values:
                self.to = decode_htmlentities(values['toaddress2'])
            else:
                person = values['to']
                self.to = '%s <%s>' % (email.utils.quote(decode_htmlentities(person['name'])), person['email'])
            
            if 'attachment' in values and values['attachment']['number_attachments'] > 0:
                self.attachmentNames = values['attachment']['names']
            else:
                self.attachmentNames = ''
            
            if 'cc' in values:
                self.cc = values['cc']
            else:
                self.cc = ''
        except:
            log( values )
            raise
    
#    def hashId(self):
#        m = hashlib.md5()
#        m.update(self.contentType + '@')
#        m.update(self.date.isoformat() + '@')
#        m.update(self.sfrom.encode('utf-8') + '@')
#        m.update(self.to.encode('utf-8') + '@')
#        m.update(self.subject.encode('utf-8') + '@')
#        m.update(self.body.encode('utf-8') + '@')
#        m.update(self.attachmentNames.encode('utf-8') + '@')
#        m.update(str(self.size))
#        return m.hexdigest()
        
    def getFlags(self):
        flags = []
        if self.answered:
            flags.append(r'\Answered')
        if not self.unread:
            flags.append(r'\Seen')
        if self.deleted:
            flags.append(r'\Deleted')
        if self.draft:
            flags.append(r'\Draft')
        if self.flagged:
            flags.append(r'\Flagged')
        if self.forwarded:
            flags.append(r'$Forwarded')
        return '(' + ' '.join(flags) + ')'
    
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
    urlImapFunc = urlExpresso + 'expressoMail1_2/controller.php?action=$this.imap_functions.'
    urlCheck = urlImapFunc + 'get_range_msgs2&msg_range_begin=1&msg_range_end=5000&sort_box_type=SORTARRIVAL&sort_box_reverse=1&'
    urlListFolders = urlImapFunc + 'get_folders_list'
    urlMoveMsgs = urlImapFunc + 'move_messages&border_ID=null&sort_box_type=SORTARRIVAL&search_box_type=ALL&sort_box_reverse=1&reuse_border=null&get_previous_msg=0&'
    urlSetFlags = urlImapFunc + 'set_messages_flag&'
    urlGetMsg = urlImapFunc + 'get_info_msg&'
    urlCreateFolder = urlImapFunc + 'create_mailbox&'
    urlDownloadMessages = urlExpresso + 'expressoMail1_2/inc/gotodownload.php?msg_folder=null&msg_number=null&msg_part=null&newfilename=mensagens.zip&'
    urlMakeEml = urlExpresso + 'expressoMail1_2/controller.php?action=$this.exporteml.makeAll'
    urlExportMsg = urlExpresso + 'expressoMail1_2/controller.php?action=$this.exporteml.export_msg'
    urlImportMsgs = urlExpresso + 'expressoMail1_2/controller.php'
    urlGetReturnExecuteForm = urlExpresso + 'expressoMail1_2/controller.php?action=$this.functions.getReturnExecuteForm'
    urlDeleteMsgs = urlImapFunc + 'delete_msgs&border_ID=null&'
    urlInitRules = urlExpresso + 'expressoMail1_2/controller.php?action=$this.ScriptS.init_a'
    urlAutoClean = urlImapFunc + 'automatic_trash_cleanness&cyrus_delimiter=/&'

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
        
        self.logged = False
        
        self.quota = 0
        self.quotaLimit = 50 #Mega Bytes
        
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
            self.doLogin()
            url = self.opener.open(surl, params)
        return url
    
    def callExpresso(self, surl, params = None, post = False):
        url = self.openUrl(surl, params, post)    
        response = url.read().decode('iso-8859-1')
        return unserialize(response)
    
    def doLogin(self):
        try:
            url = self.opener.open(self.urlLogin, urllib.urlencode(self.fields))
            self.logged = not url.geturl().startswith(self.urlLogin)
        except Exception, e:
            raise LoginError(u"It was not possible to connect at Expresso. Error:\n\n" + str(e))
        if not self.logged:
            raise LoginError(u"It was not possible to connect at Expresso. Check your password.")
    
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
        self.callExpresso(self.urlCreateFolder, {'newp': path.encode('iso-8859-1')})
    
    def getMsg(self, msgfolder, msgid):
        return ExpressoMessage(self.callExpresso(self.urlGetMsg, {'msg_number': msgid, 'msg_folder' : msgfolder.encode('iso-8859-1')}))
    
    def getFullMsgs(self, msgfolder, msgsid):
        idx_file = self.callExpresso(self.urlMakeEml, {'folder': msgfolder.encode('utf-8'), 'msgs_to_export': msgsid}, True)
        
        if not idx_file:
            return None
        
        url = self.opener.open(self.urlDownloadMessages + urllib.urlencode({'idx_file': idx_file}, True))
        try:
            zfile = zipfile.ZipFile(StringIO(url.read()))
            msgs = {}
            for name in zfile.namelist():
                #formato do nome SUBJECT_ID.eml, extraí o ID do nome do arquivo
                msgs[int(name[name.rindex('_') +1 : -4])] = str(zfile.read(name)) # a codificação das mensagens é ASCII
            zfile.close()
        except zipfile.BadZipfile, e:
            log( "Error downloading full messages.", "   idx_file:", idx_file )
            return None
        return msgs
    
    def getFullMsgEspecial(self, msgfolder, msgid):
        #faz o download e uma única mensagem, deve ser usado nos casos em que getFullMsgs não funciona
        idx_file = self.callExpresso(self.urlExportMsg, {'folder': msgfolder.encode('utf-8'), 'msgs_to_export': msgid}, True)
        
        if not idx_file:
            return None
        
        url = self.opener.open(self.urlDownloadMessages + urllib.urlencode({'idx_file': idx_file}, True))
        return str(url.read())
    
    def importMsgs(self, msgfolder, file):
        url = self.openUrl(self.urlImportMsgs, {'folder': msgfolder.encode('iso-8859-1'), '_action': '$this.imap_functions.import_msgs',
                                                    'countFiles': 1, 'file_1' : file}, True)
        #verifica se aconteceu algum erro
        result = self.callExpresso(self.urlGetReturnExecuteForm)
        if 'error' in result and result['error'].strip() != '':
            raise Exception(result['error'])
        
    def setMsgFlag(self, msgfolder, msgid, flag):
        self.callExpresso(self.urlSetFlags, {'flag': flag.lower(), 'msgs_to_set' : msgid, 'folder' : msgfolder.encode('iso-8859-1')})
    
    def getMsgs(self, criteria, folder):
        filterParam = {'search_box_type': criteria.encode('iso-8859-1'), 'folder': folder.encode('iso-8859-1')}
        
        data = self.callExpresso(self.urlCheck, filterParam)
        msgs = []
        # as mensagens vem identificadas por um número (sequêncial) no dict da resposta
        i = 0
        while i in data:
          msgs.append(ExpressoMessage(data[i]))
          i += 1
        
        return msgs
    
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
    
    def autoClean(self, past_days_count):
        data = self.callExpresso(self.urlAutoClean, {'before_date': past_days_count})
        log( "AutoClean response:", data )

# Portei este código do arquivo connector.js do expresso.
def matchBracket(str, iniPos):
    nClose = iniPos
    while True:
        nOpen = str.find('{', nClose+1)
        nClose = str.find('}', nClose+1)
        if (nOpen == -1):
            return nClose

        if (nOpen < nClose ):
            nClose = matchBracket(str, nOpen)
            
        if (nOpen >= nClose):
            return nClose

###########################################################
# Faz o parse da resposta do expresso. Portei este código do arquivo connector.js do expresso.
# Formato:
#   a:n:{s:n:"";i:k;};
#   Saída: dicionário com os valores
def unserialize(str):
    type = str[0]
    if type == 'a':
        n = int( str[str.index(':')+1 : str.index(':',2)] )
        arrayContent = str[str.index('{')+1 : str.rindex('}')]
        
        data = {}
        for i in range(n):
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
            
    elif type == 's':
        pos = str.index(':', 2)
        val = int(str[2 : pos])
        data = str[pos+2 : pos + 2 + val]
        #str = str[pos + 4 + val : ]

    elif type == 'i' or type == 'd':
        pos = str.index(';')
        data = int(str[2  : pos])
        #str = str[pos + 1 : ]
        
    elif type == 'N':
        data = None
        #str = str[str.index(';') + 1 : ]
                    
    elif type == 'b':
        if str[2] == '1':
            data = True
        else:
            data = False
    else:
        raise Exception('Invalid reponse format from Expresso.')
        
    return data    
    
def checkImapError(typ, resp):
    if typ != 'OK':
        if len(resp) > 0:
            raise Exception(resp[0])
        else:
            raise Exception('Bad response.')
        
class MsgItem():
    def __init__(self, msgid, msgfolder, msgflags):
        self.id = msgid
        self.folder = msgfolder
        self.flags = msgflags

class MsgList():
    def __init__(self):
        self.db = {}
        self.eindex = {}
        self.signature = u'<%f_%d@localhost.signature>' % (time.time(), random.randint(0,100000))
        self.isNew = True 
        
    def ekey(self, msgid, msgfolder):
        return '%d@%s' % (msgid, msgfolder)
    
    def add(self, id, msgid, msgfolder, msgflags):
        self.db[id] = MsgItem(msgid, msgfolder, msgflags)
        self.eindex[self.ekey(msgid, msgfolder)] = id
    
    def get(self, id):
        msg = self.db[id]
        return (msg.id, msg.folder, msg.flags)
    
    def getIds(self):
        return self.db.keys()
    
    def getId(self, msgid, msgfolder):
        return self.eindex.get(self.ekey(msgid, msgfolder))
    
    def isEmpty(self):
        return len(self.db) == 0
    
    def exists(self, id):
        return id in self.db
    
    def update(self, id, msgid, msgfolder, msgflags):
        if id in self.db:
            msg = self.db[id]
            if msg.id != msgid or msg.folder != msgfolder:
                del self.eindex[self.ekey(msg.id, msg.folder)]
                msg.id = msgid
                msg.folder = msgfolder
                self.eindex[self.ekey(msgid, msgfolder)] = id
            msg.flags = msgflags
        else:
            self.add(id, msgid, msgfolder, msgflags)

    def delete(self, id):
        msg = self.db[id]
        del self.eindex[self.ekey(msg.id, msg.folder)]
        del self.db[id]
    
    def save(self, file):
        file.write("3\n") # versão
        file.write(self.signature.encode('utf-8'))
        file.write('\n')
        for id, msg in self.db.items():
            file.write(id.encode('utf-8'))
            file.write('\x00')
            file.write(str(msg.id))
            file.write('\x00')
            file.write(msg.folder.encode('utf-8'))
            file.write('\x00')
            file.write(msg.flags.encode('utf-8'))
            file.write('\n')
        self.isNew = False
    
    def load(self, file):
        line = file.readline().strip()
        if line != '3':
            log( line )
            raise IExpressoError('DB file with wrong version.')
        self.signature = file.readline().strip()
        self.isNew = False
        line = file.readline().strip()
        while line != '':
            parts = line.split('\x00')
            self.add(parts[0].decode('utf-8'), int(parts[1]), parts[2].decode('utf-8'), parts[3].decode('utf-8'))
            line = file.readline().strip()

class MailSynchronizer():
    metadataFolder = 'INBOX/_metadata_dont_delete'
    def __init__(self):
        if not os.path.exists(iexpressodir):
            os.mkdir(iexpressodir)
        self.dbpath = os.path.join( iexpressodir, 'msg.db' )
        self.deleteHandler = self
        self.client = None
        self.curday = 0
        self.patSender = re.compile('^Sender: (.+?)[\r\n]', re.MULTILINE | re.IGNORECASE)
        self.patMessageId = re.compile('^Message-Id: (.+?)[\r\n]', re.MULTILINE | re.IGNORECASE)
        
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
            raise LoginError(e.message)
    
    def login(self, user, password):
        self.user = user
        self.password = password
        self.checkPreConditions()
        self.es = ExpressoManager(user, password)
        self.curday = 0
        self.loginLocal()
        self.es.doLogin()
        self.db = self.loadDb()
        self.smartFolders = None
    
    def close(self):
        log( 'Shutting down ...' )
        self.logoutLocal()
    
    def logoutLocal(self):
        if hasattr(self, 'client') and self.client != None:
            self.closeLocalFolder()
            self.client.logout()
    
    def getLocalFolders(self):
        (typ, list) = self.client.list('""', '*')
        checkImapError(typ, list)
        lst = []
        for item in list:
            folder = getFolderPath(item)
            if not folder.startswith('INBOX'):
                raise IExpressoError('Error loading local folders.')
            if folder != self.metadataFolder:
                lst.append(folder)
        if len(lst) == 0:
            raise IExpressoError('Error loading local folders.')
        return lst
    
    def checkPreConditions(self):
        maildir = '/home/' + self.user + '/Maildir'
        if os.path.exists(maildir):
            if not os.path.exists(self.dbpath):
                raise IExpressoError('You must recreate your local INBOX.')
        elif os.path.exists(self.dbpath):
            raise IExpressoError('You must remove the file "%s".' % self.dbpath)
    
    def getQuotaStr(self):
        return "%d%% of %dMB" % (self.es.quota, self.es.quotaLimit)
        
    def syncFolders(self):
        self.localFolders = self.getLocalFolders()
        # verifica se todas as pastas do expresso existem no imap local
        self.efolders = self.es.listFolders()
        for folder_id in self.efolders:
            hasfolder = False  
            self.createLocalFolder(folder_id)
    
    def createLocalFolder(self, folder):
        if not folder in self.localFolders:
            log( 'Creating folder', folder )
            (typ, data) = self.client.create( folder.encode('imap4-utf-7') )
            checkImapError(typ, data)
            self.localFolders.append(folder)
    
    def getLocalSignature(self):
        typ, msg = self.client.select(self.metadataFolder, True)
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
        self.client.append(self.metadataFolder, '(\\Seen)', None, self.strmsg(msg)) 
    
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
    
    def loadLocalMsgs(self):
        self.closeLocalFolder()
        self.localFolders = self.getLocalFolders()
        localdb = MsgList()
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
                                flags = imaplib.ParseFlags(m[0])
                                #extrai o Message-ID
                                headers = m[1]
                                moId = self.patMessageId.search(headers)
                                if moId == None:
                                    raise IExpressoError('Error loading local messages.')
                                dbid = moId.group(1).strip()
                                if dbid == '':
                                    raise IExpressoError('Error loading local messages.')
                                #if Sender exists put it in the dbid
                                moSender = self.patSender.search(headers)
                                if moSender != None:
                                    dbid += decode_header(moSender.group(1)).strip()
                                if r'\Unseen' in flags:
                                    flags -= (r'\Unseen',)
                                localdb.add(dbid, localid, folder, '(' + ' '.join(flags) + ')')
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
                    raise IExpressoError('Error loading local messages.')
        self.closeLocalFolder()
        return localdb
    
    def fixSubject(self, fullmsg):
        if fullmsg.has_key('Subject'):
            try:
                #substitu o subject pra evitar um problema que acontece as vezes dependendo da formatação do subject
                subject = decode_header(fullmsg.get('Subject', ''))
                #log(subject)
                hsubject = email.header.Header(subject, 'utf-8', continuation_ws=' ')
                fullmsg.replace_header('Subject', hsubject)
            except:
                logError() #ignora exceções nessa parte. (não é fundamental pro funcionamento do sistema)
        
    def getDbId(self, fullmsg):
        #se não houver um Message-Id adiciona um gerado automaticamente
        sender = decode_header(fullmsg.get('Sender', '').strip())
        if fullmsg.has_key('Message-Id'):
            return fullmsg['Message-Id'] + sender
        else:
            hashid = '<%f_%d@localhost>' % (time.time(), random.randint(0,100000))
            fullmsg.add_header('Message-Id', hashid)
            hashid += sender
            return hashid
    
    def strmsg(self, msg):
        fp = StringIO()
        g = EmailGenerator(fp, mangle_from_=False) #mangle_from = False para não por o ">" no início.
        g.flatten(msg)
        return fp.getvalue()
        
    def loadExpressoMessages(self, criteria, localdb, folders):
        curids = set()
        for folder_id in folders:
            log( 'Checking', folder_id )
            msgs = self.es.getMsgs(criteria, folder_id)
            todownload = {}
            todownloadEx = {}
            for msg in msgs:
                dbid = self.db.getId(msg.id, folder_id)
                if dbid != None:
                    self.db.update(dbid, msg.id, folder_id, msg.getFlags()) #atualiza os dados da msg
                    curids.add(dbid)
                else:
                    #mensagens com "'" no subject devem ser importadas individualmente
                    if msg.subject.find("'") >= 0:
                        todownloadEx[msg.id] = msg.getFlags()
                    else:
                        todownload[msg.id] = msg.getFlags()
                    #método alternativo de fazer o download das mensagens. (não trás o Message-Id)
                    #fullmsg = self.es.getMsg(folder_id, msg.id)
                    #if msg.unread:
                    #    fullmsg.unread = msg.unread
                    #    self.es.setMsgFlag(folder_id, msg.id, 'unseen')
                    #msgflags = fullmsg.getFlags()
                    #dbid = self.db.update(msg.id, folder_id, msgflags)
                    #log( '  ', fullmsg.subject.encode('utf-8'), msgflags, dbid )
                    #self.client.append(folder_id.encode('imap4-utf-7'), msgflags, None, fullmsg.createMimeMessage(dbid))
                    
            if len(todownload) + len(todownloadEx) > 0:
                if len(todownload) > 0:
                    newmsgs = self.es.getFullMsgs(folder_id, ','.join([str(key) for key in todownload.keys()]))
                    if newmsgs == None:
                        #download falhou, faz o download de todas as mensagens pelo modo especial
                        todownloadEx.update(todownload)
                        newmsgs = {}
                    # se nem todas as mensagens foram retornadas agenda o download especial
                    elif len(newmsgs) != len(todownload):
                        for eid, eflags in todownload.items():
                            if not eid in newmsgs:
                                todownloadEx[eid] = eflags
                else:
                    newmsgs = {}
                #faz o download das mensagens especiais individualmente
                for eid, eflags in todownloadEx.items():
                    log( 'Getting message using alternative way:', eid )
                    msgsrc = self.es.getFullMsgEspecial(folder_id, eid)
                    if msgsrc:
                        newmsgs[eid] = msgsrc
                        todownload[eid] = eflags
                #importa as mensagens no banco
                for eid, eflags in todownload.items():
                    if eid in newmsgs:
                        fullmsg = email.message_from_string( newmsgs[eid] )
                        dbid = self.getDbId(fullmsg)
                        log( '  ', eid, eflags, dbid ) #fullmsg['Subject'] )
                        if not localdb.exists(dbid):
                            self.fixSubject(fullmsg) #necessário porque senão aparece o subject codificado no thunderbird.
                            self.createLocalFolder(folder_id)
                            typ, resp = self.client.append(folder_id.encode('imap4-utf-7'), eflags, None, self.strmsg(fullmsg))
                            checkImapError(typ, resp)
                        self.db.update(dbid, eid, folder_id, eflags)
                        curids.add(dbid)
        return curids
    
    def checkSignature(self, localdb):
        sig = self.getLocalSignature()
        if sig != self.db.signature:
            if sig == None and localdb.isEmpty() and self.db.isNew:
                self.storeLocalSignature()
            else:
                raise IExpressoError('DB and INBOX signatures does not match.')
    
    def loadAllMsgs(self):
        log( '* Full refresh -', time.asctime() )
        try:
            localdb = self.initUpdate() 
            
            try:
                importedIds = self.changeExpresso(localdb, doMove = True, doDelete = True, doImport = True) #move, deleta e atualiza as mensagens no expresso
                
                curids = self.loadExpressoMessages('ALL', localdb, self.efolders)
                
                if not importedIds.isEmpty():
                    self.changeExpresso(importedIds) # corrige os flags das mensagens importadas
                
                localdb = self.loadLocalMsgs() # carrega as novas mensagens que foram inseridas
                
                #remove as mensagens que não estão mais na caixa do expresso da caixa local
                self.changeLocal(curids, localdb)
            finally:
                self.saveDb()
                self.closeLocalFolder()
            
            self.es.listFolders() # para atualizar a quota
        except:
            logError()
            raise
        log( 'OK' )
        
    def initUpdate(self):
        self.updatedFolders = set()
        
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
            self.curday = day
            self.syncFolders()
            self.es.autoClean(7) # remove da lixeira mensagens mais antigas que 7 dias
            
        return localdb
        
    def loadUnseen(self):
        log( '* Smart refresh -', time.asctime() )
        # somente mensagens não lidas são carregadas
        try:
            if self.smartFolders == None:
                self.smartFolders = self.es.getFoldersWithRules() # somente as pastas com regras são atualizadas
                
            localdb = self.initUpdate()
            try:
                self.changeExpresso(localdb, doDelete=True) #seta os flags das mensagens no expresso
                
                self.loadExpressoMessages('UNSEEN', localdb, self.smartFolders)
                
                #if not importedIds.isEmpty():
                #    self.changeExpresso(importedIds) # corrige os flags das mensagens importadas
            finally:
                self.saveDb()
                self.closeLocalFolder()
        except:
            logError()
            raise
        log( 'OK' )
    
    def closeLocalFolder(self):
        if self.client.state == 'SELECTED':
            self.client.close()
        
    def changeLocal(self, curids, localdb):
        #seleciona as mensagens a serem excluídas
        folders_expunge = {}
        def deleteAfter(msgfolder, msgid):
            if msgfolder in folders_expunge:
                folders_expunge[msgfolder].append(msgid)
            else:
                folders_expunge[msgfolder] = [msgid]
                
        for id in self.db.getIds():
            if not id in curids:
                #exclui do imap local
                if localdb.exists(id):
                    msgid, msgfolder = localdb.get(id)[0:2]
                    log( 'Deleting from local %s id %d' % (msgfolder, msgid) )
                    deleteAfter(msgfolder, msgid)
                    localdb.delete(id)
                    
                self.db.delete(id)
            else:
                if not localdb.exists(id):
                    continue
                msgid, msgfolder, msgflags = localdb.get(id)
                efolder, eflags = self.db.get(id)[1:3]
                if msgflags != eflags:
                    diff = self.flagsdiff(eflags, msgflags)
                    if len(diff) > 0:
                        self.client.select(msgfolder.encode('imap4-utf-7'), False)
                        # TODO: forwarded não pode ser representando no bincimap (sem as alterações realizadas por mim)
                        log( 'Update local flag. Id: %d   folder: %s   flags: %s  localflags: %s' % (msgid, msgfolder, str(' '.join(diff)), msgflags) )
                        if r'\Unseen' in diff:
                            del diff[diff.index(r'\Unseen')]
                            self.client.store(str(msgid), '-FLAGS', r'\Seen')
                        if r'\Unflagged' in diff:
                            del diff[diff.index(r'\Unflagged')]
                            self.client.store(str(msgid), '-FLAGS', r'\Flagged')
                        if len(diff) > 0:
                            self.client.store(str(msgid), '+FLAGS', ' '.join(diff))
                        self.closeLocalFolder()
                if efolder != msgfolder:
                    #move a mensagens localmente
                    log( 'Moving local message id: %d  folder: %s  new_folder: %s' % (msgid, msgfolder.encode('utf-8'), efolder.encode('utf-8')) )
                    self.createLocalFolder(efolder)
                    deleteAfter(msgfolder, msgid)
                    self.client.select(msgfolder.encode('imap4-utf-7'), True)
                    self.client.copy(str(msgid), efolder.encode('imap4-utf-7'))
        
        #exclui as mensagens e faz expunge da pasta
        for folder in folders_expunge.keys():
            self.client.select(folder.encode('imap4-utf-7'), False)
            for msgid in folders_expunge[folder]:
                self.client.store(str(msgid), '+FLAGS', '\\Deleted')
            self.client.expunge()
            self.closeLocalFolder()
            
    def importMsgExpresso(self, folder, localid, localflags, dbid):
        log( 'Importing id: %d to folder: %s  dbid: %s' % (localid, folder, dbid) )
        self.client.select(folder.encode('imap4-utf-7'), True)
        msgsrc = self.client.fetch(str(localid), '(RFC822.HEADER RFC822.TEXT)')
        if msgsrc[0] == 'OK' and len(msgsrc[1]) >= 2:
            msgfile = NamedStringIO('email.eml')
            msgheader = msgsrc[1][0][1]
            if msgheader.startswith('>'): # correção de bug, algumas mensagens eram gravadas com o ">" no começo pelo EmailGenerator
                msgheader = msgheader[1:]
            msgfile.write(msgheader)
            msgfile.write(msgsrc[1][1][1])
            msgfile.seek(0)
            self.createFolderExpresso(folder)
            self.es.importMsgs(folder, msgfile)
            #procura o id da mensagem importada
            moId = self.patMessageId.search(msgheader)
            if moId == None:
                msgid = dbid #nem sempre o dbid é igual ao MESSAGE-ID
            else:
                msgid = moId.group(1).strip()
                log('Searching Message-ID:', msgid) 
            msgs = self.es.getMsgs('RECENT TEXT "Message-ID: %s"' % msgid, folder) # essa busca não é sensível a casa e nem a espaços
            if len(msgs) == 1:
                msg = msgs[0]
                self.db.update(dbid, msg.id, folder, msg.getFlags())
            elif len(msgs) > 1:
                #adiciona com id falso para evitar que o email seja reenviado em caso de erro após esta parte
                self.db.update(dbid, -localid, folder, localflags)
            else:
                self.updatedFolders.add(folder)
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
                    #cuidado! irá excluir permanentemente as mensagens
                    strids = ','.join([str(eid) for eid in todelete[folder]])
                    log( 'Deleting messages from Expresso. Ids: %s   folder: %s' % (strids, folder) )
                    self.es.deleteMsgs(strids, folder)
                    self.updatedFolders.add(folder)
                #atualiza o banco, se skipExpresso for True as mensagens serão recarregadas da próxima vez que houver full refresh
                for eid in todelete[folder]:
                    dbid = self.db.getId(eid, folder)
                    if dbid == None:
                        raise IExpressoError('Error deleting messages from expresso.')
                    self.db.delete(dbid)
    
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
                            self.db.update(dbid, eid, folder, newflags[dbid]) # atualiza o banco
    
    def createFolderExpresso(self, newfolder):
        if not newfolder in self.efolders:
            self.es.createFolder(newfolder) #cria a pasta no expresso
            self.efolders.append(newfolder)
                            
    def moveMessagesExpresso(self, tomove):
        # move as mensagens
        for (efolder, newfolder), eids in tomove.items():
            strids = ','.join([str(eid) for eid in eids])
            log( 'Moving ids: %s   folder: %s   newfolder: %s' % (strids, efolder, newfolder) )
            self.createFolderExpresso(newfolder)
            self.es.moveMsgs(strids, efolder, newfolder)
            self.updatedFolders.add(newfolder)
    
    def changeExpresso(self, localdb, doImport = False, doMove = False, doDelete = False):
        #verifica as mensagens que não existem mais na caixa local
        todelete = {}
        toflag = {}
        tomove = {}
        newflags = {}
        
        importedIds = MsgList()
        
        def moveAfter(efolder, newfolder, eid):
            pair = (efolder, newfolder)
            #log( pair, id )
            if pair in tomove:
                tomove[pair].append(eid)
            else:
                tomove[pair] = [eid]

        if doDelete:
            for id in self.db.getIds():
                if not localdb.exists(id):
                    eid, efolder = self.db.get(id)[0:2]
                    #por motivos de segurança só deveria excluir da lixeira, após algum tempo de teste essa restrição foi removida
                    if efolder in todelete:
                        todelete[efolder].append(eid)
                    else:
                        todelete[efolder] = [eid]
                    #else:
                    #    moveAfter(efolder, 'INBOX/Trash', eid) #move pra lixeira quando estiver excluída
            
            self.deleteFromExpresso(localdb, todelete)
        
        for id in localdb.getIds():
            msgid, msgfolder, msgflags = localdb.get(id)
            if self.db.exists(id):
                eid, efolder, eflags = self.db.get(id)
                #move as mensagens que foram movidas
                if doMove and msgfolder != efolder:
                    moveAfter(efolder, msgfolder, eid)
                
                #altera os flags das mensagens lidas e respondidas
                if msgflags != eflags:
                    #log( "msgflags: %s  eflags: %s" % (msgflags, eflags) )
                    diff = self.flagsdiff(msgflags, eflags)
                    if len(diff) > 0:
                        newflags[id] = self.mapFlagsExpresso(toflag, eid, efolder, eflags, diff)
                        log( diff, msgflags, eflags)
            elif doImport:
                if msgflags.find(r'\Deleted') < 0 and not msgfolder.endswith('/Trash'):
                    #por enquanto só importa itens que tenham um Message-ID
                    self.importMsgExpresso(msgfolder, msgid, msgflags, id)
                    importedIds.add(id, msgid, msgfolder, msgflags)

        self.flagMessagesExpresso(toflag, newflags)
        
        self.moveMessagesExpresso(tomove)
        
        return importedIds
    
    def mapFlagsExpresso(self, toflag, eid, efolder, eflags, diff):
        newflags = set(eflags[1:-1].split())
        if efolder in toflag:
            flags = toflag[efolder]
        else:
            flags = {'seen': [], 'unseen': [], 'answered': [], 'forwarded': [], 'flagged': [], 'unflagged': []}
            toflag[efolder] = flags
        if r'\Seen' in diff:
            flags['seen'].append(eid)
            newflags.add(r'\Seen')
        if r'\Unseen' in diff:
            flags['unseen'].append(eid)
            if r'\Seen' in newflags:
                newflags.remove(r'\Seen')
        if r'\Answered' in diff:
            flags['answered'].append(eid)
            newflags.add(r'\Answered')
        if r'\Flagged' in diff:
            flags['flagged'].append(eid)
            newflags.add(r'\Flagged')
        if r'\Unflagged' in diff:
            flags['unflagged'].append(eid)
            if r'\Flagged' in newflags:
                newflags.remove(r'\Flagged')
        if r'$Forwarded' in diff:
            flags['forwarded'].append(eid)
            newflags.add(r'$Forwarded')
        return '(' + ' '.join(newflags) + ')'

    def flagsdiff(self, sflags1, sflags2):
        flags1 = sflags1[1:-1].split()
        flags2 = sflags2[1:-1].split()
        diff = []
        for f1 in flags1:
            if f1 != '\\Recent' and f1 != '\\Deleted' and not f1 in flags2:
                diff.append(f1)
        if r'\Seen' in flags2 and not r'\Seen' in flags1:
            diff.append(r'\Unseen')
        if r'\Flagged' in flags2 and not r'\Flagged' in flags1:
            diff.append(r'\Unflagged')
        return diff
        
    
def getFolderPath(str):
    p1 = str.rindex('"', 0)
    p2 = str.rindex('"', 0, p1-1)
    return str[p2 + 1:p1].decode('imap4-utf-7') # codec definido em imap4utf7
    
if __name__ == "__main__":
    import getpass
    
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
        log( "*** Error:", e.message )


